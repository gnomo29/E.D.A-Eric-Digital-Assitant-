"""Tareas en segundo plano: recordatorios locales con notificación Windows."""

from __future__ import annotations

import threading
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from . import config
from .logger import get_logger

log = get_logger("background_tasks")

try:
    from win10toast import ToastNotifier
except Exception:
    ToastNotifier = None  # type: ignore[assignment]


class BackgroundReminderWorker:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (config.DATA_DIR / "reminders.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._items: List[Dict[str, str | float]] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._toaster = ToastNotifier() if ToastNotifier is not None else None
        self._init_db()
        self._restore_from_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    due_ts REAL NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _restore_from_db(self) -> None:
        now = time.time()
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id, message, due_ts FROM reminders WHERE due_ts >= ?", (now,)).fetchall()
        finally:
            conn.close()
        with self._lock:
            self._items = [{"id": int(r[0]), "message": str(r[1]), "due_ts": float(r[2])} for r in rows]

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def add_reminder(self, message: str, due_ts: float) -> None:
        conn = self._connect()
        try:
            cur = conn.execute("INSERT INTO reminders(message, due_ts) VALUES (?, ?)", (message[:300], float(due_ts)))
            reminder_id = int(cur.lastrowid)
            conn.commit()
        finally:
            conn.close()
        with self._lock:
            self._items.append({"id": reminder_id, "message": message[:300], "due_ts": float(due_ts)})

    def list_reminders(self) -> List[Dict[str, str]]:
        with self._lock:
            ordered = sorted(self._items, key=lambda x: float(x.get("due_ts", 0.0)))
            return [
                {
                    "id": str(item.get("id", "")),
                    "message": str(item.get("message", "")),
                    "due_ts": str(item.get("due_ts", "")),
                }
                for item in ordered
            ]

    def cancel_reminder(self, reminder_id: int) -> bool:
        rid = int(reminder_id)
        conn = self._connect()
        try:
            conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
            conn.commit()
        finally:
            conn.close()
        with self._lock:
            before = len(self._items)
            self._items = [x for x in self._items if int(x.get("id", -1)) != rid]
            return len(self._items) < before

    def _loop(self) -> None:
        while self._running:
            due: List[Dict[str, str | float]] = []
            now = time.time()
            with self._lock:
                pending: List[Dict[str, str | float]] = []
                for item in self._items:
                    if float(item.get("due_ts", now + 1)) <= now:
                        due.append(item)
                    else:
                        pending.append(item)
                self._items = pending
            for item in due:
                msg = str(item.get("message", "Recordatorio"))
                rid = int(item.get("id", -1))
                if rid >= 0:
                    conn = self._connect()
                    try:
                        conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
                        conn.commit()
                    finally:
                        conn.close()
                self._notify(msg)
            time.sleep(1.0)

    def _notify(self, message: str) -> None:
        title = f"E.D.A. • {datetime.now().strftime('%H:%M')}"
        if self._toaster is not None:
            try:
                self._toaster.show_toast(title, message, threaded=True, duration=6)
                return
            except Exception as exc:
                log.warning("No pude mostrar toast Windows: %s", exc)
        log.info("Recordatorio local: %s", message)

