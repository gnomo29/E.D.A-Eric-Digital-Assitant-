"""Búsqueda web básica para E.D.A."""

from __future__ import annotations

import re
from typing import Dict, List
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

import config
from logger import get_logger
from utils import build_http_session

log = get_logger("web_search")

try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None


class WebSearch:
    """Búsqueda web con fallback robusto."""

    def __init__(self) -> None:
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }
        self.http = build_http_session()

    def _normalize_results(self, items: List[Dict[str, str]], max_results: int) -> List[Dict[str, str]]:
        """Limpia, deduplica y limita resultados para mejorar estabilidad."""
        seen_urls = set()
        output: List[Dict[str, str]] = []
        for item in items:
            raw_url = (item.get("url", "") or "").strip()
            title = self._clean_text(item.get("title", "") or "Sin título")
            snippet = self._clean_text(item.get("snippet", ""))
            if not raw_url:
                continue
            normalized_url = raw_url.split("#", 1)[0].rstrip("/")
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            output.append(
                {
                    "title": title[:180] or "Sin título",
                    "url": raw_url,
                    "snippet": snippet[:500],
                }
            )
            if len(output) >= max_results:
                break
        return output

    def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        if DDGS is not None:
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=max_results))
                parsed = [
                    {
                        "title": item.get("title", "Sin título"),
                        "url": item.get("href", ""),
                        "snippet": item.get("body", ""),
                    }
                    for item in results
                    if item.get("href")
                ]
                return self._normalize_results(parsed, max_results=max_results)
            except Exception as exc:
                log.warning("Fallo DDGS: %s", exc)

        # Fallback simple usando endpoint html de DuckDuckGo
        try:
            parsed = self._search_duckduckgo_html(query, max_results=max_results * 2)
            return self._normalize_results(parsed, max_results=max_results)
        except Exception as exc:
            log.error("Fallo búsqueda web: %s", exc)
            return []

    def _search_duckduckgo_html(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        r = self.http.get(url, headers=self.headers, timeout=10)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        output: List[Dict[str, str]] = []

        for result in soup.select("div.result"):
            a = result.select_one("a.result__a")
            snippet_node = result.select_one("a.result__snippet") or result.select_one("div.result__snippet")
            if not a:
                continue
            output.append(
                {
                    "title": a.get_text(" ", strip=True) or "Sin título",
                    "url": a.get("href", ""),
                    "snippet": (snippet_node.get_text(" ", strip=True) if snippet_node else "").strip(),
                }
            )
            if len(output) >= max_results:
                break

        return output

    def search_google_snippets(self, query: str, max_results: int = 3) -> List[Dict[str, str]]:
        """Busca en Google (modo background) y extrae snippets cortos."""
        search_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=es"

        try:
            response = self.http.get(search_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            results: List[Dict[str, str]] = []

            # Featured snippet / answer box más común
            featured = soup.select_one("div.kp-wholepage") or soup.select_one("div.IZ6rdc")
            if featured:
                featured_text = self._clean_text(featured.get_text(" ", strip=True))
                if len(featured_text) > 30:
                    results.append(
                        {
                            "title": "Respuesta destacada",
                            "url": search_url,
                            "snippet": featured_text,
                        }
                    )

            # Resultados orgánicos
            for block in soup.select("div.tF2Cxc"):
                title_node = block.select_one("h3")
                link_node = block.select_one("a")
                snippet_node = block.select_one("div.VwiC3b") or block.select_one("span.aCOpRe")
                if not title_node or not link_node:
                    continue

                title = self._clean_text(title_node.get_text(" ", strip=True))
                url = (link_node.get("href") or "").strip()
                snippet = self._clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")

                if title and url and snippet:
                    results.append({"title": title, "url": url, "snippet": snippet})

                if len(results) >= max_results:
                    break

            if results:
                return self._normalize_results(results, max_results=max_results)

        except Exception as exc:
            log.warning("Google scraping falló, uso fallback DDG: %s", exc)

        # Fallback seguro: resultados de DDG si Google bloquea/parcial
        return self.search(query, max_results=max_results)

    def build_short_answer(self, query: str, results: List[Dict[str, str]], max_sentences: int = 3) -> str:
        """Construye una respuesta corta (2-3 oraciones) desde snippets."""
        snippets: List[str] = []

        for item in results[:3]:
            text = self._clean_text(item.get("snippet", ""))
            if len(text) >= 30:
                snippets.append(text)

        if not snippets:
            return (
                "Según mi búsqueda en línea, no encontré un resumen confiable en este momento. "
                "Puedo intentar una consulta más específica si desea."
            )

        merged = " ".join(snippets)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", merged) if s.strip()]

        if not sentences:
            compact = merged[:320].strip()
            return f"Según mi búsqueda en línea, {compact}"

        selected = sentences[:max(1, min(max_sentences, 3))]
        answer = " ".join(selected)
        if not answer.endswith((".", "!", "?")):
            answer += "."

        return f"Según mi búsqueda en línea, {answer}"

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip())
