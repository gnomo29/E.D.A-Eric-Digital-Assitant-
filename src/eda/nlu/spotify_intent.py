"""NLU heurística para comandos de Spotify (ES/EN coloquial)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

SpotifyIntentKind = Literal[
    "liked",
    "album",
    "playlist",
    "track",
    "artist_top",
    "similar",
    "shuffle_only",
    "repeat_only",
    "transfer_query",
    "latest_album",
    "generic_play",
]


def strip_accents(s: str) -> str:
    nk = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nk if not unicodedata.combining(c))


_STOP_PREFIX = re.compile(
    r"^\s*(?:por\s+favor|please|oye|hey|eda|e\.d\.a\.|jarvis)\s*[,:]?\s*",
    flags=re.IGNORECASE,
)


def normalize_for_fuzzy(s: str) -> str:
    t = strip_accents((s or "").lower())
    t = re.sub(r"[^a-z0-9áéíóúüñ\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for w in (
        "el ",
        "la ",
        "los ",
        "las ",
        "un ",
        "una ",
        "the ",
        "a ",
        "de ",
        "del ",
        "por ",
        "para ",
        "mi ",
        "mis ",
        "tu ",
    ):
        if t.startswith(w):
            t = t[len(w) :].strip()
    return t


def fuzzy_ratio(a: str, b: str) -> float:
    na, nb = normalize_for_fuzzy(a), normalize_for_fuzzy(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def score_candidate(query: str, title: str, subtitle: str = "") -> float:
    """Mezcla fuzzy del título + fuzzy combinado con subtítulo (artista)."""
    base = fuzzy_ratio(query, title)
    if subtitle:
        combo = fuzzy_ratio(query, f"{title} {subtitle}")
        return max(base, combo * 0.98)
    return base


@dataclass
class SpotifyParsedIntent:
    kind: SpotifyIntentKind
    primary_query: str
    artist_hint: str
    device_hint: str
    shuffle: bool | None
    repeat_mode: str | None  # "track"|"context"|"off" via Spotify API
    prefer_saved: bool
    raw: str


_LIKED_RE = re.compile(
    r"\b(?:mis\s+me\s+gusta|mis\s+favoritos|mis\s+favoritas|me\s+gusta\b|me\s+gustan\b|"
    r"liked\s+songs|canciones\s+que\s+me\s+gustan)\b",
    re.I,
)

_SIM_RE = re.compile(
    r"\b(?:algo\s+similar\s+a|algo\s+parecido\s+a|algo\s+como|similar\s+a|parecido\s+a|"
    r"radio\s+(?:de\s+)?|pon\s+(?:algo\s+)?similar)\s*(?:a\s+)?(.+)$",
    re.I,
)

_ALBUM_SPLIT_RE = re.compile(
    r"\b(?:álbum|album)\s+(.+?)\s+(?:de|by)\s+(.+)$",
    re.I,
)

_PLAYLIST_Q_RE = re.compile(
    r"\b(?:mi\s+)?(?:playlist|lista(?:\s+de\s+reproducción)?)\s*[«\"']?\s*(.+?)\s*[»\"']?\s*$",
    re.I,
)

_DEVICE_TAIL_RE = re.compile(
    r"\b(?:en|al)\s+(?:el\s+)?(?:altavoz|dispositivo|speaker)\s+(?:de\s+)?(?:la\s+)?(.+)$",
    re.I,
)

_TRACK_Q_RE = re.compile(
    r"\b(?:la\s+)?(?:canción|pista|tema|track)\s+[«\"']?(.+?)[»\"']?\s*$",
    re.I,
)

_LATEST_ALBUM_RE = re.compile(
    r"\b(?:último|ultimo|última|ultima|newest|latest)\s+(?:álbum|album)\s+(?:de\s+)?(.+)$",
    re.I,
)

_SHUFFLE_RE = re.compile(
    r"\b(?:activa|activar|pon|ponme|enable|turn\s+on)\s+(?:el\s+)?(?:modo\s+)?shuffle\b|"
    r"\bshuffle\b|\baleatori[ao]\b|\bmodo\s+shuffle\b",
    re.I,
)

_REPEAT_RE = re.compile(
    r"\b(?:activa|activar|pon|enable)\s+(?:la\s+)?(?:repetición|repeticion|repeat)\b|"
    r"\brepetir\b|\brepeat\b|\b(?:modo\s+)?(?:una\s+vez\s+y\s+otra|loop)\b",
    re.I,
)

_TRANSFER_RE = re.compile(
    r"\b(?:pasa|pasar|transfer(?:ir)?|mueve|mover)\s+(?:la\s+)?(?:reproducción|reproduccion|playback)\b|"
    r"\b(?:en\s+(?:el\s+)?)?(?:altavoz|speaker)\s+(?:de\s+)?(?:la\s+)?(.+)$|"
    r"\b(?:reproduce|reproducir|play)\s+(?:en\s+(?:el\s+)?)?(?:dispositivo|device)\s+(.+)$|"
    r"\b(?:en\s+(?:el\s+)?)?(?:dispositivo|device)\s+(.+)$",
    re.I,
)

_ARTIST_TOP_RE = re.compile(
    r"\b(?:top|éxitos|exitos|hits)\s+(?:de\s+)?(.+)$",
    re.I,
)


def parse_spotify_utterance(raw: str) -> SpotifyParsedIntent:
    """Interpretación ligera; primary_query puede estar vacío si la frase solo pide estado."""
    text = _STOP_PREFIX.sub("", (raw or "").strip())
    _dt = _DEVICE_TAIL_RE.search(text)
    core = text[: _dt.start()].strip() if _dt else text
    _tail_dev = _dt.group(1).strip(" '\"«»") if _dt else ""
    low = core.lower()
    full_low = text.lower()

    shuffle_on = None
    if _SHUFFLE_RE.search(low) or _SHUFFLE_RE.search(full_low):
        shuffle_on = True
    if re.search(r"\b(?:desactiva|apaga|off)\s+(?:el\s+)?shuffle\b|\bsin\s+shuffle\b", full_low):
        shuffle_on = False

    repeat_mode: str | None = None
    if re.search(r"\b(?:desactiva|apaga)\s+(?:la\s+)?repetición\b|\brepeat\s+off\b", full_low):
        repeat_mode = "off"
    elif _REPEAT_RE.search(full_low) or re.search(r"\b(?:modo\s+)?(?:cola|canción)\s+repeat\b", full_low):
        repeat_mode = "context"

    prefer_saved = bool(
        re.search(
            r"\b(?:mis|mi|mi\s+biblioteca|en\s+mi\s+biblioteca|saved\s+library)\b",
            full_low,
        )
    )

    device_hint = ""
    tm = _TRANSFER_RE.search(text)
    if tm:
        for g in tm.groups():
            if g:
                device_hint = g.strip(" '\"«»")
                break
    if not device_hint and _tail_dev:
        device_hint = _tail_dev

    transferish = bool(device_hint) or bool(
        re.search(r"\b(?:transferir|transfer|pasar\s+(?:la\s+)?(?:sonido|audio))\b", full_low)
    )

    if _LIKED_RE.search(full_low):
        return SpotifyParsedIntent(
            kind="liked",
            primary_query="",
            artist_hint="",
            device_hint=device_hint,
            shuffle=shuffle_on,
            repeat_mode=repeat_mode,
            prefer_saved=True,
            raw=raw,
        )

    if transferish and not _LIKED_RE.search(full_low):
        q = device_hint or ""
        if not q:
            mdev = re.search(
                r"\b(?:altavoz|speaker|dispositivo|device|caja|chromecast)\s+(?:de\s+)?(?:la\s+)?(?:el\s+)?(.+)$",
                full_low,
            )
            if mdev:
                q = mdev.group(1).strip()
        # Solo transferencia sin contenido musical nuevo
        content_hint = re.search(
            r"\b(?:reproduce|pon|toca|similar|álbum|album|playlist|canción)\b",
            full_low,
        )
        if q and not content_hint:
            return SpotifyParsedIntent(
                kind="transfer_query",
                primary_query=q,
                artist_hint="",
                device_hint=q,
                shuffle=shuffle_on,
                repeat_mode=repeat_mode,
                prefer_saved=False,
                raw=raw,
            )

    ms = _SIM_RE.search(core.strip())
    if ms:
        tail = ms.group(1).strip()
        return SpotifyParsedIntent(
            kind="similar",
            primary_query=tail,
            artist_hint="",
            device_hint=device_hint,
            shuffle=shuffle_on,
            repeat_mode=repeat_mode,
            prefer_saved=False,
            raw=raw,
        )

    la = _LATEST_ALBUM_RE.search(core.strip())
    if la:
        artist = la.group(1).strip()
        return SpotifyParsedIntent(
            kind="latest_album",
            primary_query=artist,
            artist_hint="",
            device_hint=device_hint,
            shuffle=shuffle_on,
            repeat_mode=repeat_mode,
            prefer_saved=prefer_saved,
            raw=raw,
        )

    asp = _ALBUM_SPLIT_RE.search(core.strip())
    if asp:
        tit, art = asp.group(1).strip(), asp.group(2).strip()
        pq = f"{tit} {art}".strip()
        return SpotifyParsedIntent(
            kind="album",
            primary_query=pq,
            artist_hint=art,
            device_hint=device_hint,
            shuffle=shuffle_on,
            repeat_mode=repeat_mode,
            prefer_saved=prefer_saved,
            raw=raw,
        )

    pl = _PLAYLIST_Q_RE.search(core.strip())
    if pl and ("playlist" in low or "lista" in low):
        return SpotifyParsedIntent(
            kind="playlist",
            primary_query=pl.group(1).strip(" '\"«»"),
            artist_hint="",
            device_hint=device_hint,
            shuffle=shuffle_on,
            repeat_mode=repeat_mode,
            prefer_saved=prefer_saved or True,
            raw=raw,
        )

    tt = _TRACK_Q_RE.search(core.strip())
    if tt:
        return SpotifyParsedIntent(
            kind="track",
            primary_query=tt.group(1).strip(" '\"«»"),
            artist_hint="",
            device_hint=device_hint,
            shuffle=shuffle_on,
            repeat_mode=repeat_mode,
            prefer_saved=False,
            raw=raw,
        )

    at = _ARTIST_TOP_RE.search(core.strip())
    if at:
        return SpotifyParsedIntent(
            kind="artist_top",
            primary_query=at.group(1).strip(),
            artist_hint="",
            device_hint=device_hint,
            shuffle=shuffle_on,
            repeat_mode=repeat_mode,
            prefer_saved=False,
            raw=raw,
        )

    if re.search(r"\b(?:álbum|album)\b", low):
        mq = re.split(r"\b(?:álbum|album)\s+", core, maxsplit=1, flags=re.I)
        rest = mq[1].strip() if len(mq) > 1 else ""
        rest = re.sub(r"^\s*(?:el|la)\s+", "", rest, flags=re.I)
        return SpotifyParsedIntent(
            kind="album",
            primary_query=rest,
            artist_hint="",
            device_hint=device_hint,
            shuffle=shuffle_on,
            repeat_mode=repeat_mode,
            prefer_saved=prefer_saved,
            raw=raw,
        )

    # Shuffle / repeat solo
    if shuffle_on is not None and len(normalize_for_fuzzy(core)) < 80:
        only_controls = not re.search(r"\b(?:reproduce|pon|álbum|album|playlist|canción|similar)\b", low)
        if only_controls:
            return SpotifyParsedIntent(
                kind="shuffle_only",
                primary_query="",
                artist_hint="",
                device_hint=device_hint,
                shuffle=shuffle_on,
                repeat_mode=repeat_mode,
                prefer_saved=False,
                raw=raw,
            )

    # Fallback: reproducir texto residual (playlist/album deducido en runtime por ranking)
    stripped = re.sub(
        r"^\s*(?:reproduce|reproducir|pon|ponme|toca|play|escucha)\s+",
        "",
        core,
        flags=re.I,
    ).strip()

    return SpotifyParsedIntent(
        kind="generic_play",
        primary_query=stripped or core.strip(),
        artist_hint="",
        device_hint=device_hint,
        shuffle=shuffle_on,
        repeat_mode=repeat_mode,
        prefer_saved=prefer_saved,
        raw=raw,
    )


def utterance_might_be_spotify(text: str) -> bool:
    """True si conviene enviar la frase al pipeline Spotify antes del fallback simple."""
    low = (text or "").lower()
    if not low.strip():
        return False
    keys = (
        "playlist",
        "álbum",
        "album",
        "me gusta",
        "mis favoritos",
        "liked",
        "shuffle",
        "repetir",
        "similar",
        "radio",
        "altavoz",
        "dispositivo",
        "transfer",
        "último álbum",
        "ultimo album",
        "canción",
        "pista",
        "track",
    )
    return any(k in low for k in keys)
