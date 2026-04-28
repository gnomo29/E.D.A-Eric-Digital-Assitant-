"""Gestión de frases-disparador persistentes en SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
import difflib
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config

try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    fuzz = None


def normalize_phrase(text: str) -> str:
    clean = re.sub(r"[^\w\sáéíóúñ]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", clean).strip()


class TriggerStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or config.LONG_TERM_DB_FILE
        self._bootstrap()

    def _bootstrap(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS triggers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phrase TEXT NOT NULL,
                    match_type TEXT NOT NULL,
                    fuzzy_threshold REAL NOT NULL,
                    action_type TEXT NOT NULL,
                    action_payload TEXT NOT NULL,
                    require_confirm INTEGER NOT NULL,
                    owner TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_triggers_phrase ON triggers(phrase)")
            conn.commit()

    def create_trigger(
        self,
        *,
        phrase: str,
        match_type: str,
        action_type: str,
        action_payload: dict[str, Any],
        require_confirm: bool,
        owner: str = "local",
        fuzzy_threshold: float | None = None,
    ) -> int:
        ph = normalize_phrase(phrase)
        if not ph:
            return -1
        mt = "fuzzy" if str(match_type).lower() == "fuzzy" else "exact"
        threshold = float(fuzzy_threshold if fuzzy_threshold is not None else config.TRIGGERS_FUZZY_THRESHOLD)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO triggers(phrase,match_type,fuzzy_threshold,action_type,action_payload,require_confirm,owner,active,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    ph,
                    mt,
                    threshold,
                    str(action_type).strip(),
                    json.dumps(action_payload or {}, ensure_ascii=False),
                    1 if require_confirm else 0,
                    str(owner or "local"),
                    1,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
            return int(cur.lastrowid or -1)

    def list_triggers(self, active_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE active=1" if active_only else ""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT id,phrase,match_type,fuzzy_threshold,action_type,action_payload,require_confirm,owner,active,created_at
                FROM triggers {where} ORDER BY id DESC
                """
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            payload = {}
            try:
                payload = json.loads(r[5] or "{}")
            except Exception:
                payload = {}
            out.append(
                {
                    "id": int(r[0]),
                    "phrase": str(r[1]),
                    "match_type": str(r[2]),
                    "fuzzy_threshold": float(r[3] or 0),
                    "action_type": str(r[4]),
                    "action_payload": payload if isinstance(payload, dict) else {},
                    "require_confirm": bool(r[6]),
                    "owner": str(r[7]),
                    "active": bool(r[8]),
                    "created_at": str(r[9]),
                }
            )
        return out

    def set_active(self, trigger_id: int, active: bool) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("UPDATE triggers SET active=? WHERE id=?", (1 if active else 0, int(trigger_id)))
            conn.commit()
            return (cur.rowcount or 0) > 0

    def delete_trigger(self, trigger_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM triggers WHERE id=?", (int(trigger_id),))
            conn.commit()
            return (cur.rowcount or 0) > 0

    def _score(self, text: str, phrase: str) -> float:
        if fuzz is not None:
            return float(fuzz.ratio(text, phrase))
        return 100.0 * difflib.SequenceMatcher(a=text, b=phrase).ratio()

    def match(self, text: str) -> dict[str, Any] | None:
        normalized = normalize_phrase(text)
        if not normalized:
            return None
        triggers = self.list_triggers(active_only=True)
        # exact first
        for t in triggers:
            if t["match_type"] == "exact" and normalized == t["phrase"]:
                return {"trigger": t, "score": 100.0, "phrase_matched": t["phrase"]}
        # then fuzzy
        best: tuple[float, dict[str, Any] | None] = (0.0, None)
        for t in triggers:
            if t["match_type"] != "fuzzy":
                continue
            s = self._score(normalized, t["phrase"])
            if s >= float(t.get("fuzzy_threshold", config.TRIGGERS_FUZZY_THRESHOLD)) and s > best[0]:
                best = (s, t)
        if best[1] is None:
            return None
        return {"trigger": best[1], "score": best[0], "phrase_matched": best[1]["phrase"]}
