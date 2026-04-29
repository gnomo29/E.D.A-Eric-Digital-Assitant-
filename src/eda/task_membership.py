"""Biblioteca ligera de tareas aprendidas (SQLite)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from . import config
from .logger import get_logger

log = get_logger("task_membership")


@dataclass
class LearnedTask:
    """Representa una tarea reutilizable."""

    name: str
    trigger: str
    steps: List[Dict[str, Any]]
    source: str = "manual"
    use_count: int = 0
    updated_at: str = ""
    variables: Dict[str, Any] | None = None
    context: Dict[str, Any] | None = None


@dataclass
class ExecutionLog:
    """Registro de ejecución de una tarea."""

    task_trigger: str
    intent: str
    parameters: Dict[str, Any]
    result: str
    success: bool
    error: str = ""
    context: str = ""


class TaskMembershipStore:
    """Persistencia SQLite para habilidades/flujo de acciones."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (config.MEMORY_DIR / "task_membership.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._bootstrap()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=4.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _bootstrap(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learned_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    trigger TEXT NOT NULL UNIQUE,
                    steps_json TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # Migraciones no destructivas.
            try:
                conn.execute("ALTER TABLE learned_tasks ADD COLUMN variables_json TEXT NOT NULL DEFAULT '{}'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE learned_tasks ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE learned_tasks ADD COLUMN plan_json TEXT NOT NULL DEFAULT '{}'")
            except Exception:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_learned_tasks_trigger ON learned_tasks(trigger)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_learned_tasks_updated ON learned_tasks(updated_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_trigger TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    result TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    context TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_logs_trigger ON execution_logs(task_trigger)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_logs_success ON execution_logs(success)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generalized_skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_key TEXT NOT NULL UNIQUE,
                    skill_name TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    template_json TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_generalized_skills_key ON generalized_skills(pattern_key)")

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def save_task(
        self,
        name: str,
        trigger: str,
        steps: List[Dict[str, Any]],
        source: str = "manual",
        variables: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
        plan: Dict[str, Any] | None = None,
    ) -> bool:
        norm_trigger = self._normalize(trigger)
        clean_name = (name or norm_trigger or "tarea").strip()
        if not norm_trigger or not isinstance(steps, list) or not steps:
            return False
        now = datetime.now().isoformat(timespec="seconds")
        payload = json.dumps(steps, ensure_ascii=False)
        var_payload = json.dumps(variables or {}, ensure_ascii=False)
        ctx_payload = json.dumps(context or {}, ensure_ascii=False)
        plan_payload = json.dumps(plan or {"steps": steps}, ensure_ascii=False)
        try:
            with closing(self._connect()) as conn:
                conn.execute(
                    """
                    INSERT INTO learned_tasks(name, trigger, steps_json, source, created_at, updated_at, variables_json, context_json, plan_json)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trigger) DO UPDATE SET
                        name=excluded.name,
                        steps_json=excluded.steps_json,
                        source=excluded.source,
                        variables_json=excluded.variables_json,
                        context_json=excluded.context_json,
                        plan_json=excluded.plan_json,
                        updated_at=excluded.updated_at
                    """,
                    (clean_name, norm_trigger, payload, source, now, now, var_payload, ctx_payload, plan_payload),
                )
            return True
        except Exception as exc:
            log.error("No pude guardar tarea aprendida '%s': %s", norm_trigger, exc)
            return False

    def get_task_by_trigger(self, user_text: str) -> LearnedTask | None:
        normalized_text = self._normalize(user_text)
        if not normalized_text:
            return None
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT name, trigger, steps_json, source, use_count, updated_at, variables_json, context_json "
                    "FROM learned_tasks ORDER BY LENGTH(trigger) DESC"
                ).fetchall()
        except Exception as exc:
            log.error("No pude consultar tareas aprendidas: %s", exc)
            return None

        for row in rows:
            trigger = str(row[1] or "")
            if trigger and trigger in normalized_text:
                try:
                    steps = json.loads(str(row[2] or "[]"))
                except Exception:
                    steps = []
                if not isinstance(steps, list) or not steps:
                    continue
                return LearnedTask(
                    name=str(row[0] or "tarea"),
                    trigger=trigger,
                    steps=steps,
                    source=str(row[3] or "manual"),
                    use_count=int(row[4] or 0),
                    updated_at=str(row[5] or ""),
                    variables=self._safe_json_dict(row[6]),
                    context=self._safe_json_dict(row[7]),
                )
        return None

    @staticmethod
    def _safe_json_dict(raw: Any) -> Dict[str, Any]:
        try:
            obj = json.loads(str(raw or "{}"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def mark_used(self, trigger: str) -> None:
        norm_trigger = self._normalize(trigger)
        if not norm_trigger:
            return
        try:
            with closing(self._connect()) as conn:
                conn.execute(
                    "UPDATE learned_tasks SET use_count = use_count + 1, updated_at=? WHERE trigger=?",
                    (datetime.now().isoformat(timespec="seconds"), norm_trigger),
                )
        except Exception as exc:
            log.debug("No pude actualizar use_count de '%s': %s", norm_trigger, exc)

    def log_execution(self, payload: ExecutionLog) -> None:
        try:
            with closing(self._connect()) as conn:
                conn.execute(
                    """
                    INSERT INTO execution_logs(
                        task_trigger, intent, parameters_json, result, success, error, context, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._normalize(payload.task_trigger),
                        self._normalize(payload.intent),
                        json.dumps(payload.parameters, ensure_ascii=False),
                        (payload.result or "")[:800],
                        1 if payload.success else 0,
                        (payload.error or "")[:500],
                        (payload.context or "")[:250],
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
        except Exception as exc:
            log.debug("No pude guardar execution_log: %s", exc)

    def learn_generalized_skill(
        self,
        pattern_key: str,
        skill_name: str,
        intent: str,
        template: Dict[str, Any],
        success: bool,
        error: str = "",
    ) -> None:
        key = self._normalize(pattern_key)
        if not key:
            return
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with closing(self._connect()) as conn:
                conn.execute(
                    """
                    INSERT INTO generalized_skills(pattern_key, skill_name, intent, template_json, use_count, success_count, last_error, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(pattern_key) DO UPDATE SET
                        skill_name=excluded.skill_name,
                        intent=excluded.intent,
                        template_json=excluded.template_json,
                        use_count=generalized_skills.use_count + 1,
                        success_count=generalized_skills.success_count + excluded.success_count,
                        last_error=CASE
                            WHEN excluded.last_error <> '' THEN excluded.last_error
                            ELSE generalized_skills.last_error
                        END,
                        updated_at=excluded.updated_at
                    """,
                    (
                        key,
                        (skill_name or key)[:120],
                        self._normalize(intent or "general"),
                        json.dumps(template, ensure_ascii=False),
                        1 if success else 0,
                        (error or "")[:400],
                        now,
                    ),
                )
        except Exception as exc:
            log.debug("No pude actualizar generalized_skill '%s': %s", key, exc)

    def find_generalized_skill(self, user_text: str) -> Dict[str, Any] | None:
        normalized = self._normalize(user_text)
        if not normalized:
            return None
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    """
                    SELECT pattern_key, skill_name, intent, template_json, use_count, success_count, last_error
                    FROM generalized_skills
                    ORDER BY success_count DESC, use_count DESC
                    """
                ).fetchall()
        except Exception as exc:
            log.debug("No pude consultar generalized_skills: %s", exc)
            return None
        for row in rows:
            pattern_key = str(row[0] or "")
            if pattern_key and pattern_key in normalized:
                try:
                    template = json.loads(str(row[3] or "{}"))
                except Exception:
                    template = {}
                return {
                    "pattern_key": pattern_key,
                    "skill_name": str(row[1] or ""),
                    "intent": str(row[2] or ""),
                    "template": template if isinstance(template, dict) else {},
                    "use_count": int(row[4] or 0),
                    "success_count": int(row[5] or 0),
                    "last_error": str(row[6] or ""),
                }
        return None

    def score_task_similarity(self, user_text: str, variables: Dict[str, Any]) -> LearnedTask | None:
        normalized = self._normalize(user_text)
        if not normalized:
            return None
        candidate = self.get_task_by_trigger(user_text)
        if candidate is None:
            return None
        score = 0
        if candidate.trigger in normalized:
            score += 4
        cvars = candidate.variables or {}
        for k, v in (variables or {}).items():
            if str(cvars.get(k, "")).lower() == str(v).lower() and str(v).strip():
                score += 2
        return candidate if score >= 4 else None
