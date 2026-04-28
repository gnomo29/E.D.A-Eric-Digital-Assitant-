"""Helpers seguros para reproducción y búsqueda de YouTube."""

from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, urlparse
from typing import Any

import requests

from .. import config
from .. import remote_llm

YOUTUBE_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)

_YT_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}


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
    now = time.time()
    cached = _YT_CACHE.get(key)
    if cached and now - cached[0] < 900:
        return cached[1]
    if remote_llm.remote_deep_research_pipeline_available():
        prompt = f"Devuelve solo URLs de YouTube (máx 3) para: {query}"
        answer = remote_llm.synthesize_filtered_web_answer(
            question=prompt,
            sources_digest=f"Consulta objetivo: {query}\nSitio preferente: youtube.com y youtu.be",
        )
        cands = extract_youtube_candidates_from_text(answer or "")
        _YT_CACHE[key] = (now, cands)
        return cands
    return []


def detect_youtube_intent(text: str) -> bool:
    low = (text or "").strip().lower()
    if "youtube.com/watch" in low or "youtu.be/" in low:
        return True
    if "youtube" in low:
        return True
    if "muestrame un video" in low or "muéstrame un video" in low or "abre un video" in low:
        return True
    if re.search(r"^\s*reproduce\s+[a-z0-9áéíóúñ_. -]{2,}$", low) and "spotify" not in low:
        return True
    return False
