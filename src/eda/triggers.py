"""Gestión de frases-disparador persistentes en SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
import difflib
from contextlib import closing
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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=3.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _bootstrap(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trigger_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trigger_runs_tid ON trigger_runs(trigger_id)")
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
        with closing(self._connect()) as conn:
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
        with closing(self._connect()) as conn:
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
        with closing(self._connect()) as conn:
            cur = conn.execute("UPDATE triggers SET active=? WHERE id=?", (1 if active else 0, int(trigger_id)))
            conn.commit()
            return (cur.rowcount or 0) > 0

    def set_active_all(self, active: bool) -> int:
        with closing(self._connect()) as conn:
            cur = conn.execute("UPDATE triggers SET active=?", (1 if active else 0,))
            conn.commit()
            return int(cur.rowcount or 0)

    def get_trigger(self, trigger_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT id,phrase,match_type,fuzzy_threshold,action_type,action_payload,require_confirm,owner,active,created_at
                FROM triggers WHERE id=?
                """,
                (int(trigger_id),),
            ).fetchone()
        if not row:
            return None
        payload = {}
        try:
            payload = json.loads(row[5] or "{}")
        except Exception:
            payload = {}
        return {
            "id": int(row[0]),
            "phrase": str(row[1]),
            "match_type": str(row[2]),
            "fuzzy_threshold": float(row[3] or 0),
            "action_type": str(row[4]),
            "action_payload": payload if isinstance(payload, dict) else {},
            "require_confirm": bool(row[6]),
            "owner": str(row[7]),
            "active": bool(row[8]),
            "created_at": str(row[9]),
        }

    def delete_trigger(self, trigger_id: int) -> bool:
        with closing(self._connect()) as conn:
            cur = conn.execute("DELETE FROM triggers WHERE id=?", (int(trigger_id),))
            conn.execute("DELETE FROM trigger_runs WHERE trigger_id=?", (int(trigger_id),))
            conn.commit()
            return (cur.rowcount or 0) > 0

    def update_trigger(
        self,
        trigger_id: int,
        *,
        phrase: str,
        action_type: str,
        action_payload: dict[str, Any],
        require_confirm: bool,
        match_type: str | None = None,
        fuzzy_threshold: float | None = None,
    ) -> bool:
        ph = normalize_phrase(phrase)
        if not ph:
            return False
        mt = "fuzzy" if str(match_type or "fuzzy").lower() == "fuzzy" else "exact"
        threshold = float(fuzzy_threshold if fuzzy_threshold is not None else config.TRIGGERS_FUZZY_THRESHOLD)
        with closing(self._connect()) as conn:
            cur = conn.execute(
                """
                UPDATE triggers
                SET phrase=?, match_type=?, fuzzy_threshold=?, action_type=?, action_payload=?, require_confirm=?
                WHERE id=?
                """,
                (
                    ph,
                    mt,
                    threshold,
                    str(action_type).strip(),
                    json.dumps(action_payload or {}, ensure_ascii=False),
                    1 if require_confirm else 0,
                    int(trigger_id),
                ),
            )
            conn.commit()
            return (cur.rowcount or 0) > 0

    def log_trigger_run(self, trigger_id: int, *, status: str, detail: str, source: str = "local") -> None:
        tid = int(trigger_id)
        if tid <= 0:
            return
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO trigger_runs(trigger_id,status,detail,source,created_at)
                VALUES(?,?,?,?,?)
                """,
                (
                    tid,
                    str(status or "unknown")[:32],
                    str(detail or "")[:600],
                    str(source or "local")[:64],
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()

    def get_last_run_map(self) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT r.trigger_id, r.status, r.detail, r.source, r.created_at
                FROM trigger_runs r
                INNER JOIN (
                    SELECT trigger_id, MAX(id) AS max_id
                    FROM trigger_runs
                    GROUP BY trigger_id
                ) m ON r.id = m.max_id
                """
            ).fetchall()
        for row in rows:
            tid = int(row[0])
            out[tid] = {
                "status": str(row[1]),
                "detail": str(row[2]),
                "source": str(row[3]),
                "created_at": str(row[4]),
            }
        return out

    def list_trigger_runs(self, trigger_id: int, limit: int = 20) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit or 20), 100))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, trigger_id, status, detail, source, created_at
                FROM trigger_runs
                WHERE trigger_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(trigger_id), lim),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": int(row[0]),
                    "trigger_id": int(row[1]),
                    "status": str(row[2]),
                    "detail": str(row[3]),
                    "source": str(row[4]),
                    "created_at": str(row[5]),
                }
            )
        return out

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
