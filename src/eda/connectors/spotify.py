"""Integración Spotify: caché ligera, auditoría y ruteo NLU → Web API."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict
from typing import Any

from .. import config
from ..logger import get_logger
from ..nlp_utils import detect_confirmation
from ..nlu.spotify_intent import SpotifyParsedIntent, fuzzy_ratio, normalize_for_fuzzy, parse_spotify_utterance, score_candidate
from ..spotify_web import get_spotify_client, is_web_api_configured

log = get_logger("connectors.spotify")

_CONF_AUTO = lambda: float(getattr(config, "EDA_SPOTIFY_CONF_AUTO", 0.82))
_CONF_LOW = lambda: float(getattr(config, "EDA_SPOTIFY_CONF_AMBIG_LOW", 0.50))
_TTL = lambda: int(getattr(config, "EDA_SPOTIFY_CACHE_TTL_SECONDS", 900))
_TRANSFER_CONFIRM = lambda: bool(getattr(config, "EDA_SPOTIFY_TRANSFER_REQUIRES_CONFIRM", True))

_ALT_VERSION_MARKERS = (
    "remix",
    "live",
    "cover",
    "karaoke",
    "instrumental",
    "slowed",
    "reverb",
    "8d",
    "sped up",
    "mashup",
    "tribute",
    "edit",
    "version",
)

_ALT_VERSION_REQUEST_MARKERS = (
    "remix",
    "live",
    "cover",
    "acustic",
    "acoustic",
    "karaoke",
    "instrumental",
    "slowed",
    "reverb",
    "mashup",
    "version",
    "versión",
    "tribute",
)


def _norm_text(text: str) -> str:
    return normalize_for_fuzzy(text or "")


def _split_track_and_artist(query: str) -> tuple[str, str]:
    q = (query or "").strip()
    m = re.match(r"^\s*(.+?)\s+(?:de|by)\s+(.+?)\s*$", q, flags=re.IGNORECASE)
    if not m:
        return q, ""
    title = m.group(1).strip(" '\"«»")
    artist = m.group(2).strip(" '\"«»")
    if len(title) < 2 or len(artist) < 2:
        return q, ""
    return title, artist


def _query_requests_alt_version(query: str) -> bool:
    qn = _norm_text(query)
    if not bool(getattr(config, "EDA_SPOTIFY_PREFER_OFFICIAL", True)):
        return True
    return any(marker in qn for marker in _ALT_VERSION_REQUEST_MARKERS)


def _track_title_penalty(title: str, *, allow_alt_version: bool) -> float:
    if allow_alt_version:
        return 0.0
    tn = _norm_text(title)
    penalty = 0.0
    for marker in _ALT_VERSION_MARKERS:
        if marker in tn:
            penalty += 0.10
    # Penalización extra para resultados de humor/parodia que suelen colarse.
    if "muppet" in tn:
        penalty += 0.25
    return min(0.45, penalty)


def _score_track_result(
    *,
    query: str,
    title: str,
    artists: str,
    artist_hint: str,
    allow_alt_version: bool,
) -> float:
    sc = score_candidate(query, title, artists)
    if artist_hint:
        artist_match = fuzzy_ratio(artist_hint, artists)
        if artist_match >= 0.70:
            sc += 0.18
        elif artist_match < 0.35:
            sc -= 0.28
    sc -= _track_title_penalty(title, allow_alt_version=allow_alt_version)
    return max(0.0, min(1.0, sc))


def _audit_path() -> Any:
    p = getattr(config, "EDA_SPOTIFY_AUDIT_JSONL", config.LOGS_DIR / "spotify_actions.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(x in lk for x in ("token", "secret", "authorization", "refresh")):
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def append_spotify_audit(record: dict[str, Any]) -> None:
    row = dict(record)
    row = _redact(row)
    row.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    try:
        with open(_audit_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.debug("[SPOTIFY] audit skip: %s", exc)


class _TTLCache:
    def __init__(self, ttl_sec: int) -> None:
        self.ttl = max(30, ttl_sec)
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        exp, val = item
        if time.time() > exp:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, val: Any) -> None:
        self._data[key] = (time.time() + self.ttl, val)


class SpotifyBridge:
    """Encapsula spotipy + caché; sp es el cliente de spotipy o un MagicMock en tests."""

    def __init__(self, sp: Any) -> None:
        self.sp = sp
        self._cache = _TTLCache(_TTL())

    def _cget(self, key: str) -> Any | None:
        return self._cache.get(key)

    def _cset(self, key: str, val: Any) -> None:
        self._cache.set(key, val)

    def me_id(self) -> str:
        u = self.sp.current_user()
        return str((u or {}).get("id") or "")

    def devices(self) -> list[dict[str, Any]]:
        key = "devices:list"
        got = self._cget(key)
        if got is not None:
            return got
        data = self.sp.devices() or {}
        devs = list(data.get("devices") or [])
        self._cset(key, devs)
        return devs

    def pick_device_id(self, hint: str | None, active_fallback: bool = True) -> str | None:
        devs = self.devices()
        if not devs:
            return None
        if not (hint or "").strip():
            if active_fallback:
                for d in devs:
                    if d.get("is_active") and d.get("id"):
                        return str(d["id"])
                if len(devs) == 1:
                    return str(devs[0].get("id") or "") or None
            return None
        hi = (hint or "").strip().lower()
        scored: list[tuple[float, str]] = []
        for d in devs:
            name = (d.get("name") or "").strip()
            ratio = fuzzy_ratio(hi, name)
            scored.append((ratio, str(d.get("id") or "")))
        scored.sort(key=lambda x: -x[0])
        if scored and scored[0][0] >= 0.45 and scored[0][1]:
            return scored[0][1]
        return None

    def search(self, q: str, stype: str, limit: int = 8) -> dict[str, Any]:
        key = f"search:{stype}:{q}:{limit}"
        got = self._cget(key)
        if got is not None:
            return got
        res = self.sp.search(q=q, type=stype, limit=limit)
        self._cset(key, res or {})
        return res or {}

    def saved_albums(self, limit: int = 50) -> list[dict[str, Any]]:
        key = f"me:albums:{limit}"
        got = self._cget(key)
        if got is not None:
            return got
        out: list[dict[str, Any]] = []
        cur = self.sp.current_user_saved_albums(limit=min(limit, 50))
        while cur and len(out) < limit:
            for it in (cur.get("items") or []):
                al = (it or {}).get("album") or {}
                if al:
                    out.append(al)
            nxt = cur.get("next")
            if not nxt or len(out) >= limit:
                break
            cur = self.sp.next(cur)  # type: ignore[no-untyped-call]
        self._cset(key, out)
        return out

    def saved_track_uris(self, max_n: int = 100) -> list[str]:
        key = f"me:tracks:{max_n}"
        got = self._cget(key)
        if got is not None:
            return got
        uris: list[str] = []
        cur = self.sp.current_user_saved_tracks(limit=min(50, max_n))
        while cur and len(uris) < max_n:
            for it in (cur.get("items") or []):
                tr = (it or {}).get("track") or {}
                u = tr.get("uri")
                if u:
                    uris.append(str(u))
            nxt = cur.get("next")
            if not nxt or len(uris) >= max_n:
                break
            cur = self.sp.next(cur)  # type: ignore[no-untyped-call]
        self._cset(key, uris)
        return uris[:max_n]

    def my_playlists(self, limit: int = 50) -> list[dict[str, Any]]:
        key = f"me:pl:{limit}"
        got = self._cget(key)
        if got is not None:
            return got
        pl: list[dict[str, Any]] = []
        cur = self.sp.current_user_playlists(limit=min(50, limit))
        while cur and len(pl) < limit:
            for p in (cur.get("items") or []):
                if p:
                    pl.append(p)
            nxt = cur.get("next")
            if not nxt or len(pl) >= limit:
                break
            cur = self.sp.next(cur)  # type: ignore[no-untyped-call]
        self._cset(key, pl)
        return pl

    def start(self, **kwargs: Any) -> None:
        self.sp.start_playback(**{k: v for k, v in kwargs.items() if v is not None})

    def set_shuffle(self, state: bool, device_id: str | None) -> None:
        self.sp.shuffle(state, device_id=device_id)

    def set_repeat(self, mode: str, device_id: str | None) -> None:
        # track | context | off
        self.sp.repeat(mode, device_id=device_id)

    def transfer(self, device_id: str, force_play: bool = True) -> None:
        self.sp.transfer_playback(device_id, force_play=force_play)

    def recommendations(self, **kwargs: Any) -> list[str]:
        rec = self.sp.recommendations(**kwargs) or {}
        uris: list[str] = []
        for t in (rec.get("tracks") or []):
            u = t.get("uri")
            if u:
                uris.append(str(u))
        return uris

    def artist_top_track_uri(self, artist_id: str) -> str | None:
        top = self.sp.artist_top_tracks(artist_id) or {}
        tracks = (top.get("tracks") or [])
        if not tracks:
            return None
        u = tracks[0].get("uri")
        return str(u) if u else None

    def latest_album_uri(self, artist_id: str) -> str | None:
        albums = self.sp.artist_albums(artist_id, album_type="album", country="ES", limit=50)
        items = (albums or {}).get("items") or []
        if not items:
            return None
        def _key(a: dict[str, Any]) -> str:
            return (a.get("release_date") or "0000")[:10]

        items.sort(key=_key, reverse=True)
        u = items[0].get("uri")
        return str(u) if u else None


def _top_from_search_albums(bridge: SpotifyBridge, q: str) -> list[tuple[dict[str, Any], float]]:
    res = bridge.search(q, "album", limit=8)
    items = ((res.get("albums") or {}).get("items")) or []
    scored: list[tuple[dict[str, Any], float]] = []
    for it in items:
        name = (it.get("name") or "").strip()
        artists = it.get("artists") or []
        sub = ", ".join((a.get("name") or "") for a in artists[:2])
        sc = score_candidate(q, name, sub)
        scored.append((it, sc))
    scored.sort(key=lambda x: -x[1])
    return scored


def _top_from_search_tracks(bridge: SpotifyBridge, q: str, artist_hint: str = "") -> list[tuple[dict[str, Any], float]]:
    queries = [q]
    if artist_hint:
        title_hint, _ = _split_track_and_artist(q)
        if title_hint:
            queries.insert(0, f'track:"{title_hint}" artist:"{artist_hint}"')

    allow_alt = _query_requests_alt_version(q)
    by_uri: dict[str, tuple[dict[str, Any], float]] = {}
    for qq in queries[:2]:
        res = bridge.search(qq, "track", limit=10)
        items = ((res.get("tracks") or {}).get("items")) or []
        for it in items:
            uri = str(it.get("uri") or "")
            if not uri:
                continue
            name = (it.get("name") or "").strip()
            artists = it.get("artists") or []
            sub = ", ".join((a.get("name") or "") for a in artists[:2])
            sc = _score_track_result(
                query=q,
                title=name,
                artists=sub,
                artist_hint=artist_hint,
                allow_alt_version=allow_alt,
            )
            cur = by_uri.get(uri)
            if cur is None or sc > cur[1]:
                by_uri[uri] = (it, sc)
    scored = list(by_uri.values())
    scored.sort(key=lambda x: -x[1])
    return scored


def _top_from_search_playlists(bridge: SpotifyBridge, q: str, me: str) -> list[tuple[dict[str, Any], float, bool]]:
    res = bridge.search(q, "playlist", limit=12)
    items = ((res.get("playlists") or {}).get("items")) or []
    mine: list[tuple[dict[str, Any], float, bool]] = []
    for it in items:
        name = (it.get("name") or "").strip()
        owner = ((it.get("owner") or {}).get("id") or "").strip()
        is_me = owner == me
        base = score_candidate(q, name, owner)
        if is_me:
            base = min(1.0, base + 0.12)
        mine.append((it, base, is_me))
    mine.sort(key=lambda x: -x[1])
    return mine


def _format_pick(cands: list[tuple[str, str, str]], call_id: str) -> str:
    lines = [f"Encontré varias coincidencias (ref. {call_id[:8]}). Decime el número o reformulá con artista:"]
    for i, (a, b, c) in enumerate(cands[:3], start=1):
        lines.append(f"  {i}. {a} — {b} ({c})")
    return "\n".join(lines)


def _run_post_play(
    bridge: SpotifyBridge,
    parsed: SpotifyParsedIntent,
    device_id: str | None,
) -> None:
    if parsed.shuffle is not None:
        bridge.set_shuffle(bool(parsed.shuffle), device_id)
    if parsed.repeat_mode:
        bridge.set_repeat(parsed.repeat_mode, device_id)


def _play_album_or_ask(
    bridge: SpotifyBridge,
    parsed: SpotifyParsedIntent,
    q: str,
    prefer_saved: bool,
    device_id: str | None,
    orch: Any,
) -> str:
    call_id = str(uuid.uuid4())
    saved: list[tuple[dict[str, Any], float]] = []
    if prefer_saved:
        for al in bridge.saved_albums(30):
            t = (al.get("name") or "").strip()
            artists = al.get("artists") or []
            sub = ", ".join((a.get("name") or "") for a in artists[:2])
            sc = score_candidate(q, t, sub)
            if sc >= 0.35:
                saved.append((al, sc))
        saved.sort(key=lambda x: -x[1])
    if saved and saved[0][1] >= _CONF_AUTO() - 0.02:
        al = saved[0][0]
        uri = al.get("uri")
        if uri:
            append_spotify_audit(
                {
                    "event": "play_album_saved",
                    "call_id": call_id,
                    "uri": uri,
                    "confidence": saved[0][1],
                }
            )
            bridge.start(context_uri=str(uri), device_id=device_id)
            _run_post_play(bridge, parsed, device_id)
            return f"Reproduciendo el álbum **{al.get('name') or 'álbum'}** (tu biblioteca)."

    scored = _top_from_search_albums(bridge, q)
    if not scored:
        return "No encontré ese álbum. Probá con el nombre del artista o verificá en Spotify."

    top, c = scored[0]
    if c >= _CONF_AUTO():
        uri = top.get("uri")
        if uri:
            append_spotify_audit({"event": "play_album", "call_id": call_id, "q": q, "score": c, "uri": uri})
            bridge.start(context_uri=str(uri), device_id=device_id)
            _run_post_play(bridge, parsed, device_id)
            return f"Reproduciendo el álbum **{top.get('name') or q}** en Spotify."
    if c >= _CONF_LOW() and len(scored) >= 2:
        options: list[dict[str, Any]] = []
        cands: list[tuple[str, str, str]] = []
        for it, sc in scored[:3]:
            ars = ", ".join((a.get("name") or "") for a in (it.get("artists") or [])[:2])
            cands.append((it.get("name") or "?", ars, f"{int(sc * 100)}% match"))
            options.append({"type": "context", "context_uri": it.get("uri"), "parsed": asdict(parsed), "device_id": device_id})
        orch._spotify_pending = {  # type: ignore[attr-defined]
            "kind": "pick",
            "options": options,
            "call_id": call_id,
        }
        append_spotify_audit({"event": "ambig_album", "call_id": call_id, "candidates": cands})
        return _format_pick(cands, call_id)
    return "No encontré un álbum claro con ese nombre; ¿podés decirme el artista?"


def _play_playlist_or_ask(
    bridge: SpotifyBridge,
    parsed: SpotifyParsedIntent,
    q: str,
    device_id: str | None,
    orch: Any,
) -> str:
    call_id = str(uuid.uuid4())
    me = bridge.me_id()
    mine = bridge.my_playlists(80)
    scored_loc: list[tuple[dict[str, Any], float]] = []
    for pl in mine:
        name = (pl.get("name") or "").strip()
        sc = score_candidate(q, name, "")
        scored_loc.append((pl, sc))
    scored_loc.sort(key=lambda x: -x[1])
    if scored_loc and scored_loc[0][1] >= _CONF_AUTO() - 0.02:
        pl = scored_loc[0][0]
        uri = pl.get("uri")
        if uri:
            append_spotify_audit({"event": "play_playlist_mine", "call_id": call_id, "uri": uri})
            bridge.start(context_uri=str(uri), device_id=device_id)
            _run_post_play(bridge, parsed, device_id)
            return f"Reproduciendo tu playlist **{pl.get('name') or q}**."

    s = _top_from_search_playlists(bridge, q, me)
    if not s:
        return "No encontré esa playlist."

    top, c, is_m = s[0]
    if c >= _CONF_AUTO():
        uri = top.get("uri")
        if uri:
            append_spotify_audit({"event": "play_playlist", "call_id": call_id, "uri": uri, "owner_mine": is_m})
            bridge.start(context_uri=str(uri), device_id=device_id)
            _run_post_play(bridge, parsed, device_id)
            return f"Reproduciendo la playlist **{top.get('name') or q}**."
    if c >= _CONF_LOW() and len(s) >= 2:
        cands = []
        options: list[dict[str, Any]] = []
        for it, sc, im in s[:3]:
            own = (it.get("owner") or {}).get("display_name") or "?"
            cands.append((it.get("name") or "?", own, f"{'tuya' if im else 'pública'} {int(sc * 100)}%"))
            options.append({"type": "context", "context_uri": it.get("uri"), "parsed": asdict(parsed), "device_id": device_id})
        orch._spotify_pending = {"kind": "pick", "options": options, "call_id": call_id}  # type: ignore[attr-defined]
        return _format_pick(cands, call_id)
    return "No encontré una playlist con ese nombre. Reformulá o abrí el enlace en Spotify."


def _play_liked(bridge: SpotifyBridge, parsed: SpotifyParsedIntent, device_id: str | None) -> str:
    call_id = str(uuid.uuid4())
    uris = bridge.saved_track_uris(100)
    if not uris:
        return "No tengo canciones en “Tus me gusta” o faltan permisos (revisá login y scopes)."
    append_spotify_audit({"event": "play_liked", "call_id": call_id, "n": len(uris)})
    bridge.start(uris=uris, device_id=device_id)
    _run_post_play(bridge, parsed, device_id)
    return f"Reproduciendo **Tus me gusta** ({len(uris)} pistas en cola inicial)."


def _play_similar(bridge: SpotifyBridge, parsed: SpotifyParsedIntent, q: str, device_id: str | None) -> str:
    call_id = str(uuid.uuid4())
    s1 = bridge.search(q, "artist", limit=3)
    artists = ((s1.get("artists") or {}).get("items")) or []
    if not artists:
        s2 = bridge.search(q, "track", limit=1)
        trs = ((s2.get("tracks") or {}).get("items")) or []
        if trs:
            tid = (trs[0].get("id") or "") or str(trs[0].get("uri", "")).rsplit(":", 1)[-1]
            if tid:
                rec = bridge.recommendations(seed_tracks=[tid], limit=25)
                if rec:
                    append_spotify_audit({"event": "play_similar_track", "call_id": call_id, "n": len(rec)})
                    bridge.start(uris=rec, device_id=device_id)
                    _run_post_play(bridge, parsed, device_id)
                    return f"Reproduciendo pistas similares a **{q}** (recomendaciones)."
        return "No encontré un artista o tema base para similares."
    aid = artists[0].get("id")
    if not aid:
        return "No pude resolver el artista."
    rec = bridge.recommendations(seed_artists=[str(aid)], limit=25)
    if not rec:
        return "Spotify no devolvió recomendaciones; probá otra búsqueda."
    append_spotify_audit({"event": "play_similar_artist", "call_id": call_id, "n": len(rec)})
    bridge.start(uris=rec, device_id=device_id)
    _run_post_play(bridge, parsed, device_id)
    return f"Reproduciendo radio basada en **{artists[0].get('name') or q}**."


def _play_track(bridge: SpotifyBridge, parsed: SpotifyParsedIntent, q: str, device_id: str | None) -> str:
    q_clean, artist_hint = _split_track_and_artist(q)
    if not artist_hint:
        artist_hint = (parsed.artist_hint or "").strip()
    scored = _top_from_search_tracks(bridge, q_clean or q, artist_hint=artist_hint)
    if not scored:
        return "No encontré esa canción."
    t, c = scored[0]
    if c < _CONF_LOW():
        return "No tengo una coincidencia clara; decime artista y título (por ejemplo: canción X de artista Y)."
    uri = t.get("uri")
    if not uri:
        return "Error al leer el track."
    append_spotify_audit({"event": "play_track", "q": q, "artist_hint": artist_hint, "uri": uri, "score": c})
    bridge.start(uris=[str(uri)], device_id=device_id)
    _run_post_play(bridge, parsed, device_id)
    return f"Reproduciendo **{t.get('name') or q}**."


def _play_generic(bridge: SpotifyBridge, parsed: SpotifyParsedIntent, q: str, device_id: str | None, orch: Any) -> str:
    if parsed.prefer_saved and "playlist" in (q or "").lower():
        return _play_playlist_or_ask(bridge, parsed, q, device_id, orch)
    # En peticiones genéricas ("reproduce X") priorizar pista evita abrir álbumes equivocados.
    tr = _play_track(bridge, parsed, q, device_id)
    if not tr.startswith("No encontré esa canción"):
        return tr
    album_ans = _play_album_or_ask(bridge, parsed, q, True, device_id, orch)
    if "varias coincidencias" in album_ans or "No encontré un álbum claro" in album_ans:
        return album_ans
    if album_ans.startswith("Reproduciendo el álbum") or album_ans.startswith("Reproduciendo"):
        return album_ans
    if "No encontré esa canción" in tr and "No encontré ese álbum" in album_ans:
        return album_ans
    if not tr.startswith("No encontré esa canción"):
        return tr
    return album_ans


def _handle_transfer(
    bridge: SpotifyBridge,
    device_name: str,
) -> tuple[str | None, str | None]:
    devs = bridge.devices()
    if not devs:
        return "No veo dispositivos activos; abrí Spotify en teléfono o PC.", None
    did = bridge.pick_device_id(device_name, active_fallback=True)
    if not did:
        return "No enlacé un dispositivo con ese nombre. Listá nombres en la app Spotify (Conecta a un dispositivo).", None
    if _TRANSFER_CONFIRM():
        return None, did
    bridge.transfer(did, force_play=True)
    return f"Reproducción movida a **{device_name}**.", None


def _parsed_from_dict(p: dict[str, Any]) -> SpotifyParsedIntent:
    return SpotifyParsedIntent(
        kind=p.get("kind", "generic_play"),  # type: ignore[arg-type]
        primary_query=str(p.get("primary_query", "")),
        artist_hint=str(p.get("artist_hint", "")),
        device_hint=str(p.get("device_hint", "")),
        shuffle=p.get("shuffle"),
        repeat_mode=p.get("repeat_mode"),
        prefer_saved=bool(p.get("prefer_saved", False)),
        raw=str(p.get("raw", "")),
    )


def play_option(_orch: Any, opt: dict[str, Any]) -> str:
    sp = get_spotify_client()
    if not sp:
        return "Spotify no está autenticado. Ejecutá `python scripts/spotify_login.py`."
    b = SpotifyBridge(sp)
    p = opt.get("parsed") or {}
    parsed = _parsed_from_dict(p) if isinstance(p, dict) else SpotifyParsedIntent(
        kind="generic_play",
        primary_query="",
        artist_hint="",
        device_hint="",
        shuffle=None,
        repeat_mode=None,
        prefer_saved=False,
        raw="",
    )
    did = opt.get("device_id")
    t = opt.get("type")
    if t == "context" and opt.get("context_uri"):
        b.start(context_uri=str(opt["context_uri"]), device_id=did)
        _run_post_play(b, parsed, did)
        return "Reproduciendo la opción elegida."
    if t == "uris" and opt.get("uris"):
        b.start(uris=list(opt["uris"]), device_id=did)
        _run_post_play(b, parsed, did)
        return "Reproduciendo la lista elegida."
    return "No pude completar la reproducción (payload inválido)."


def try_handle_spotify_pending(orch: Any, text: str) -> str | None:
    p = getattr(orch, "_spotify_pending", None)
    if not p:
        return None
    t = text.strip().lower()
    if p.get("kind") == "pick":
        m = re.match(r"^\s*([123])\s*$", t)
        if m:
            idx = int(m.group(1)) - 1
            opts = p.get("options") or []
            if 0 <= idx < len(opts):
                orch._spotify_pending = None  # type: ignore[attr-defined]
                return play_option(orch, opts[idx])
        if t in ("no", "cancela", "cancelar", "mejor no"):
            orch._spotify_pending = None  # type: ignore[attr-defined]
            return "Listo, no reproduje nada."
        return None
    if p.get("kind") == "transfer":
        d = detect_confirmation(text)
        if d is False:
            orch._spotify_pending = None  # type: ignore[attr-defined]
            return "No moví la reproducción."
        if d is None:
            return "Responde Sí o No para confirmar el dispositivo."
        sp = get_spotify_client()
        if not sp:
            orch._spotify_pending = None  # type: ignore[attr-defined]
            return "Sesión Spotify no disponible."
        b = SpotifyBridge(sp)
        b.transfer(str(p.get("device_id")), force_play=bool(p.get("force_play", True)))
        orch._spotify_pending = None  # type: ignore[attr-defined]
        append_spotify_audit({"event": "transfer_confirmed", "device": p.get("device_name")})
        return f"Listo, reproducción en **{p.get('device_name') or 'dispositivo'}**."
    return None


def route_spotify_natural(orch: Any, utterance: str, entity_query: str) -> str | None:
    """
    None → dejar que el orquestador use el fallback `try_play_via_web_api` (una pista).
    str → respuesta final.
    """
    if not is_web_api_configured():
        return None
    sp = get_spotify_client()
    if not sp:
        return None
    parsed = parse_spotify_utterance(utterance or entity_query)
    bridge = SpotifyBridge(sp)

    dev_hint = (parsed.device_hint or "").strip()
    device_id = bridge.pick_device_id(dev_hint, active_fallback=True)
    if dev_hint and not device_id:
        return f"No veo un dispositivo que coincida con «{dev_hint}». Abrí Spotify en ese equipo o revisá el nombre en “Conectar a un dispositivo”."

    if parsed.kind == "transfer_query":
        msg, need = _handle_transfer(bridge, parsed.primary_query or parsed.device_hint or "")
        if msg:
            return msg
        if need and _TRANSFER_CONFIRM():
            dname = parsed.primary_query or dev_hint
            orch._spotify_pending = {  # type: ignore[attr-defined]
                "kind": "transfer",
                "device_id": need,
                "device_name": dname,
                "force_play": True,
            }
            return f"¿Confirmás **mover la reproducción** al dispositivo «{dname}»? (Sí/No)"
        return "Listo."

    if parsed.kind == "shuffle_only" and parsed.shuffle is not None:
        did = device_id or bridge.pick_device_id("", active_fallback=True)
        if not did:
            return "No hay dispositivo activo para shuffle."
        bridge.set_shuffle(bool(parsed.shuffle), did)
        append_spotify_audit({"event": "set_shuffle", "state": parsed.shuffle})
        return f"Shuffle: **{'activado' if parsed.shuffle else 'desactivado'}**."

    if parsed.kind in ("repeat_only",) and parsed.repeat_mode:
        did = device_id or bridge.pick_device_id("", active_fallback=True)
        if not did:
            return "No hay dispositivo activo."
        bridge.set_repeat(str(parsed.repeat_mode), did)
        return f"Repetición: **{parsed.repeat_mode}**."

    if device_id is None and not dev_hint and len(bridge.devices()) > 1:
        return "Hay varios dispositivos. Decime en cuál reproducir (por nombre) o abrí Spotify en uno y reintenta."

    if parsed.kind == "liked":
        return _play_liked(bridge, parsed, device_id)

    if parsed.kind == "similar":
        if not parsed.primary_query:
            return "Decime a qué artista o tema te refieres."
        return _play_similar(bridge, parsed, parsed.primary_query, device_id)

    if parsed.kind == "latest_album":
        s = bridge.search(parsed.primary_query, "artist", limit=1)
        ars = ((s.get("artists") or {}).get("items")) or []
        if not ars:
            return f"No encontré al artista «{parsed.primary_query}»."
        aid = ars[0].get("id")
        if not aid:
            return "No pude leer el id de artista."
        uri = bridge.latest_album_uri(str(aid))
        if not uri:
            return "No hallé un álbum publicado."
        append_spotify_audit({"event": "play_latest_album", "artist": parsed.primary_query, "uri": uri})
        bridge.start(context_uri=uri, device_id=device_id)
        _run_post_play(bridge, parsed, device_id)
        return f"Reproduciendo el **último álbum** de {ars[0].get('name') or parsed.primary_query}."

    if parsed.kind == "album":
        return _play_album_or_ask(bridge, parsed, parsed.primary_query, parsed.prefer_saved, device_id, orch)

    if parsed.kind == "playlist":
        return _play_playlist_or_ask(bridge, parsed, parsed.primary_query, device_id, orch)

    if parsed.kind == "track":
        return _play_track(bridge, parsed, parsed.primary_query, device_id)

    if parsed.kind == "artist_top":
        s = bridge.search(parsed.primary_query, "artist", limit=1)
        ars = ((s.get("artists") or {}).get("items")) or []
        if not ars or not ars[0].get("id"):
            return "No encontré ese artista."
        aid = str(ars[0].get("id"))
        topu = bridge.artist_top_track_uri(aid)
        if not topu:
            return "No pude obtener el top del artista."
        append_spotify_audit({"event": "artist_top", "uri": topu})
        bridge.start(uris=[topu], device_id=device_id)
        _run_post_play(bridge, parsed, device_id)
        return f"Reproduciendo un hit de **{ars[0].get('name') or parsed.primary_query}**."

    if parsed.kind == "generic_play":
        q = (entity_query or parsed.primary_query or "").strip()
        if not q:
            return "Decime qué reproducir."
        return _play_generic(bridge, parsed, q, device_id, orch)

    return None
