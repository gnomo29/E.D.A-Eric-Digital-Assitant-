"""Gestor de deshacer para operaciones de archivos."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from . import config


class UndoManager:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (config.DATA_DIR / "undo_history.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=3.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS undo_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    src TEXT NOT NULL,
                    dst TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def record_move(self, src: str, dst: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO undo_history(action_type, src, dst) VALUES (?, ?, ?)",
                ("move", src, dst),
            )
            conn.commit()
        finally:
            conn.close()

    def undo_last(self) -> dict[str, str]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, action_type, src, dst FROM undo_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return {"status": "error", "message": "No hay acciones para deshacer."}
            rec_id, action_type, src, dst = row
            if action_type != "move":
                return {"status": "error", "message": "Tipo de acción no soportado para deshacer."}
            from pathlib import Path as _Path
            import shutil

            try:
                target = _Path(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(dst, src)
            except Exception as exc:
                return {"status": "error", "message": f"No pude deshacer: {exc}"}
            conn.execute("DELETE FROM undo_history WHERE id=?", (rec_id,))
            conn.commit()
            return {"status": "ok", "message": f"Deshecho: {dst} -> {src}"}
        finally:
            conn.close()

