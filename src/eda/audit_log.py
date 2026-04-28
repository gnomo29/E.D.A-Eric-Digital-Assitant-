"""Registro append-only de acciones sensibles (autoaprendizaje, scraping)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from . import config
from .logger import get_logger

log = get_logger("audit_log")


def audit_event(event_type: str, **fields: Any) -> None:
    """Escribe una línea JSON en logs/eda_audit.jsonl (no falla la app si disco lleno)."""
    payload: Dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "type": str(event_type),
    }
    for k, v in fields.items():
        if v is not None:
            payload[str(k)] = v
    path = Path(config.LOGS_DIR) / "eda_audit.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("[AUDIT] No se pudo escribir: %s", exc)
