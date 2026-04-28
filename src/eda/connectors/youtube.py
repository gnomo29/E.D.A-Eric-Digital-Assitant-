"""Helpers seguros para reproducción y búsqueda de YouTube."""

from __future__ import annotations

import re
import time
import threading
from collections import OrderedDict
from urllib.parse import parse_qs, urlparse
from typing import Any

import requests

from .. import config
from .. import remote_llm

YOUTUBE_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)

_YT_CACHE: "OrderedDict[str, tuple[float, list[dict[str, str]]]]" = OrderedDict()
_YT_REMOTE_LIMIT = threading.Semaphore(2)
_RICKROLL_MARKERS = (
    "never gonna give you up",
    "rick astley",
    "rickroll",
)


def is_allowed_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.netloc or "").lower()
    return any(host == d or host.endswith("." + d) for d in config.YT_DOMAIN_WHITELIST)


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "youtu.be" in host:
        vid = parsed.path.strip("/")
        return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or "") else ""
    qs = parse_qs(parsed.query)
    vid = (qs.get("v", [""])[0] or "").strip()
    return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or "") else ""


def validate_youtube_url(url: str, timeout: float = 3.0) -> bool:
    if not is_allowed_youtube_url(url):
        return False
    if not extract_video_id(url):
        return False
    oembed = f"https://www.youtube.com/oembed?url={url}&format=json"
    try:
        r = requests.get(oembed, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def classify_youtube_intent(text: str) -> str:
    low = (text or "").strip().lower()
    if not low:
        return ""
    urls = extract_urls_from_text(low)
    if any(is_allowed_youtube_url(u) and extract_video_id(u) for u in urls):
        return "play_youtube_url"
    if re.search(r"^\s*reproduce\s+[a-z0-9_.-]{3,}\s*$", low) and re.search(r"\d", low):
        return "channel_lookup"
    if re.search(r"^\s*reproduce\s+.+\s+(?:en\s+youtube|canal|creator|creador)\b", low):
        return "channel_lookup"
    if (
        "youtube" in low
        or "muestrame un video" in low
        or "muéstrame un video" in low
        or "abre un video de" in low
    ):
        return "search_youtube_query"
    return ""


def fetch_youtube_oembed(url: str, timeout: float = 3.0) -> dict[str, str]:
    """Obtiene metadatos básicos (título/canal/thumbnail) de un video válido."""
    if not is_allowed_youtube_url(url):
        return {}
    oembed = f"https://www.youtube.com/oembed?url={url}&format=json"
    try:
        r = requests.get(oembed, timeout=timeout)
        if r.status_code != 200:
            return {}
        data = r.json() if hasattr(r, "json") else {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "title": str(data.get("title", "") or "").strip(),
        "channel": str(data.get("author_name", "") or "").strip(),
        "thumbnail": str(data.get("thumbnail_url", "") or "").strip(),
    }


def _normalize_tokens(text: str) -> set[str]:
    parts = re.findall(r"[a-z0-9áéíóúñ]{3,}", (text or "").lower())
    return set(parts)


def is_suspicious_result_for_query(query: str, title: str, channel: str = "") -> bool:
    q = (query or "").strip().lower()
    t = (title or "").strip().lower()
    c = (channel or "").strip().lower()
    if not q:
        return False
    hay = f"{t} {c}".strip()
    if any(marker in hay for marker in _RICKROLL_MARKERS):
        return True
    q_tokens = _normalize_tokens(q)
    if not q_tokens:
        return False
    hay_tokens = _normalize_tokens(hay)
    overlap = len(q_tokens.intersection(hay_tokens))
    # Si la consulta tiene un identificador fuerte (ej: vegeta777), exigimos verlo en metadatos.
    strong = any(re.search(r"[a-z]+\d+|\d+[a-z]+", tok) for tok in q_tokens)
    if strong:
        return overlap == 0
    return overlap == 0 and len(q_tokens) >= 2


def _parse_iso8601_duration(raw: str) -> str:
    text = (raw or "").strip().upper()
    if not text.startswith("PT"):
        return ""
    h = m = s = 0
    mh = re.search(r"(\d+)H", text)
    mm = re.search(r"(\d+)M", text)
    ms = re.search(r"(\d+)S", text)
    if mh:
        h = int(mh.group(1))
    if mm:
        m = int(mm.group(1))
    if ms:
        s = int(ms.group(1))
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _compute_confidence(*, query: str, title: str, channel: str, published_at: str = "", views: int = 0) -> float:
    q_tokens = _normalize_tokens(query)
    hay = _normalize_tokens(f"{title} {channel}")
    overlap = len(q_tokens.intersection(hay))
    text_score = overlap / max(1, len(q_tokens)) if q_tokens else 0.4
    recency_bonus = 0.05 if str(published_at).strip() else 0.0
    views_bonus = min(0.15, max(0.0, (views / 1_000_000.0) * 0.15))
    score = 0.55 * text_score + 0.30 * (text_score > 0) + recency_bonus + views_bonus
    return round(max(0.0, min(1.0, score)), 3)


def _cache_get(key: str) -> list[dict[str, str]] | None:
    cached = _YT_CACHE.get(key)
    if not cached:
        return None
    ts, items = cached
    if time.time() - ts > int(getattr(config, "YT_CACHE_TTL", 900)):
        _YT_CACHE.pop(key, None)
        return None
    _YT_CACHE.move_to_end(key)
    return items


def _cache_put(key: str, items: list[dict[str, str]]) -> None:
    _YT_CACHE[key] = (time.time(), items)
    _YT_CACHE.move_to_end(key)
    while len(_YT_CACHE) > 64:
        _YT_CACHE.popitem(last=False)


def _youtube_api_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    api_key = str(getattr(config, "YOUTUBE_API_KEY", "") or "").strip()
    if not api_key:
        return []
    try:
        sr = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max(1, min(max_results, 5)),
                "key": api_key,
            },
            timeout=5,
        )
        if sr.status_code != 200:
            return []
        items = (sr.json() or {}).get("items", [])
    except Exception:
        return []
    ids = []
    out: list[dict[str, str]] = []
    for item in items:
        vid = str(((item or {}).get("id") or {}).get("videoId", "")).strip()
        sn = (item or {}).get("snippet") or {}
        if not vid:
            continue
        ids.append(vid)
        out.append(
            {
                "video_id": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": str(sn.get("title", "") or "").strip(),
                "channel": str(sn.get("channelTitle", "") or "").strip(),
                "thumbnail": str((((sn.get("thumbnails") or {}).get("high") or {}).get("url", ""))).strip(),
                "published_at": str(sn.get("publishedAt", "") or "").strip(),
            }
        )
    details: dict[str, dict[str, str]] = {}
    if ids:
        try:
            vr = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "contentDetails,statistics", "id": ",".join(ids), "key": api_key},
                timeout=5,
            )
            if vr.status_code == 200:
                for it in (vr.json() or {}).get("items", []):
                    vid = str((it or {}).get("id", "")).strip()
                    details[vid] = {
                        "duration": _parse_iso8601_duration(
                            str(((it or {}).get("contentDetails") or {}).get("duration", ""))
                        ),
                        "views": str(((it or {}).get("statistics") or {}).get("viewCount", "0")),
                    }
        except Exception:
            pass
    ranked: list[dict[str, str]] = []
    for row in out:
        det = details.get(str(row.get("video_id", "")), {})
        views = int(str(det.get("views", "0") or "0")) if str(det.get("views", "0")).isdigit() else 0
        conf = _compute_confidence(
            query=query,
            title=str(row.get("title", "")),
            channel=str(row.get("channel", "")),
            published_at=str(row.get("published_at", "")),
            views=views,
        )
        ranked.append(
            {
                **row,
                "duration": str(det.get("duration", "")),
                "confidence": str(conf),
                "source": "api",
                "views": str(views),
            }
        )
    ranked.sort(key=lambda x: float(str(x.get("confidence", "0.0"))), reverse=True)
    return ranked[:5]


def extract_urls_from_text(text: str) -> list[str]:
    return [u.strip(".,);]") for u in YOUTUBE_URL_RE.findall(text or "")]


def extract_youtube_candidates_from_text(text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for url in extract_urls_from_text(text):
        if not is_allowed_youtube_url(url):
            continue
        vid = extract_video_id(url)
        if not vid:
            continue
        candidates.append(
            {
                "url": url,
                "video_id": vid,
                "title": f"YouTube video {vid}",
                "channel": "unknown",
                "thumbnail": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
            }
        )
    dedup: dict[str, dict[str, str]] = {}
    for c in candidates:
        dedup[c["url"]] = c
    return list(dedup.values())[:3]


def search_youtube_candidates(query: str) -> list[dict[str, str]]:
    key = (query or "").strip().lower()
    if not key:
        return []
    cached = _cache_get(key)
    if cached is not None:
        return cached
    from_api = _youtube_api_search(query, max_results=5)
    if from_api:
        _cache_put(key, from_api)
        return from_api
    if remote_llm.remote_deep_research_pipeline_available():
        prompt = f"Devuelve solo URLs de YouTube (máx 5) para: {query}"
        answer = ""
        with _YT_REMOTE_LIMIT:
            answer = remote_llm.synthesize_filtered_web_answer(
                question=prompt,
                sources_digest=f"Consulta objetivo: {query}\nSitio preferente: youtube.com y youtu.be",
            )
        cands = extract_youtube_candidates_from_text(answer or "")
        enriched: list[dict[str, str]] = []
        for cand in cands[:5]:
            url = str(cand.get("url", "")).strip()
            meta = fetch_youtube_oembed(url)
            title = meta.get("title") or str(cand.get("title", "")).strip() or "Video de YouTube"
            channel = meta.get("channel") or str(cand.get("channel", "")).strip() or "unknown"
            conf = _compute_confidence(query=key, title=title, channel=channel)
            enriched.append(
                {
                    "url": url,
                    "video_id": str(cand.get("video_id", "")).strip(),
                    "title": title,
                    "channel": channel,
                    "thumbnail": meta.get("thumbnail") or str(cand.get("thumbnail", "")).strip(),
                    "duration": "",
                    "confidence": str(conf),
                    "source": "remote",
                    "views": "0",
                }
            )
        enriched.sort(key=lambda x: float(str(x.get("confidence", "0.0"))), reverse=True)
        _cache_put(key, enriched[:5])
        return enriched[:5]
    return []


def detect_youtube_intent(text: str) -> bool:
    return bool(classify_youtube_intent(text))


def channel_lookup_candidates(creator_query: str) -> list[dict[str, str]]:
    # Estrategia simple: reutilizar ranking general y priorizar canal/título que contenga el creador.
    query = (creator_query or "").strip()
    if not query:
        return []
    cands = search_youtube_candidates(query)
    ranked = sorted(
        cands,
        key=lambda c: (
            query.lower() in str(c.get("channel", "")).lower(),
            query.lower() in str(c.get("title", "")).lower(),
            float(str(c.get("confidence", "0.0"))),
        ),
        reverse=True,
    )
    return ranked[:5]
