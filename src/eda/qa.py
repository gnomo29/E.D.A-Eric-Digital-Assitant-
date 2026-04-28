"""Q&A ligero: KB local + fallback a Wikipedia."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

import requests

from . import config
from .logger import get_logger

log = get_logger("qa")


class QAService:
    def __init__(self) -> None:
        self._kb = self._load_kb()

    @staticmethod
    def _norm(text: str) -> str:
        raw = (text or "").strip().lower()
        decomp = unicodedata.normalize("NFKD", raw)
        no_acc = "".join(ch for ch in decomp if not unicodedata.combining(ch))
        clean = re.sub(r"[^\w\s]", " ", no_acc)
        return re.sub(r"\s+", " ", clean).strip()

    def _load_kb(self) -> dict[str, str]:
        default = {
            "quien descubrio america": "Cristobal Colon, en 1492.",
            "quien invento la bombilla": "Se atribuye principalmente a Thomas Edison, con aportes clave de otros inventores.",
            "capital de espana": "La capital de Espana es Madrid.",
        }
        kb_path = config.DATA_DIR / "resources" / "qa_kb.json"
        try:
            if kb_path.exists():
                payload = json.loads(kb_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    for k, v in payload.items():
                        if isinstance(k, str) and isinstance(v, str):
                            default[self._norm(k)] = v.strip()
        except Exception as exc:
            log.warning("No pude cargar KB local: %s", exc)
        return default

    def answer(self, question: str) -> tuple[str, str]:
        q_norm = self._norm(question)
        if not q_norm:
            return "", ""
        local = self._kb.get(q_norm, "")
        if local:
            out = f"{local} Fuente: KB local."
            self._log_qa(question, out, "kb_local")
            return out, "qa_kb_local"
        web = self._wikipedia_fallback(q_norm)
        if web:
            self._log_qa(question, web, "wikipedia")
            return web, "qa_wikipedia"
        return "", ""

    def _wikipedia_fallback(self, normalized_question: str) -> str:
        subject = re.sub(
            r"^(que|quien|quienes|cuando|donde|como|por que|por que|cual|cuales)\s+",
            "",
            normalized_question,
        ).strip()
        subject = re.sub(r"\b(descubrio|descubrieron|es|fue|son)\b", " ", subject)
        subject = re.sub(r"\s+", " ", subject).strip()
        if not subject:
            subject = normalized_question
        title = subject.replace(" ", "_")
        url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code != 200:
                return ""
            data = resp.json()
            extract = str(data.get("extract", "")).strip()
            if not extract:
                return ""
            short = extract.split(". ")[0].strip()
            if not short.endswith("."):
                short += "."
            return f"{short} Fuente: Wikipedia."
        except Exception:
            return ""

    @staticmethod
    def _log_qa(question: str, answer: str, source: str) -> None:
        path = config.LOGS_DIR / "qa_answers.jsonl"
        row = {"q": question[:220], "a": answer[:360], "source": source}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass
