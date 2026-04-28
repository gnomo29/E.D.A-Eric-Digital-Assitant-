"""ACL para comandos remotos (Telegram)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config
from ..utils import safe_json_load, safe_json_save

ALLOWED_LEVELS = {"info", "safe", "critical"}

DEFAULT_ACL = {
    "default_level": "info",
    "commands": [
        {"pattern": "estado", "level": "info", "enabled": True},
        {"pattern": "listar recordatorios", "level": "info", "enabled": True},
        {"pattern": "cancelar recordatorio", "level": "safe", "enabled": True},
        {"pattern": "reproduce", "level": "safe", "enabled": True},
        {"pattern": "abre", "level": "safe", "enabled": True},
        {"pattern": "mueve archivo", "level": "critical", "enabled": True},
        {"pattern": "organiza", "level": "critical", "enabled": True},
        {"pattern": "borra", "level": "critical", "enabled": True},
        {"pattern": "elimina", "level": "critical", "enabled": True},
        {"pattern": "ejecuta comando", "level": "critical", "enabled": True},
    ],
}


@dataclass
class ACLDecision:
    allowed: bool
    level: str
    pattern: str
    reason: str = ""


class RemoteACL:
    def __init__(self, acl_path: Path | None = None) -> None:
        self.acl_path = acl_path or getattr(config, "REMOTE_ACL_FILE", config.CONFIG_DIR / "remote_acl.json")
        self._config = self._load_or_init()

    def _load_or_init(self) -> dict[str, Any]:
        if not self.acl_path.exists():
            safe_json_save(self.acl_path, DEFAULT_ACL)
            return dict(DEFAULT_ACL)
        loaded = safe_json_load(self.acl_path, dict(DEFAULT_ACL))
        if not isinstance(loaded, dict):
            return dict(DEFAULT_ACL)
        return loaded

    def reload(self) -> None:
        self._config = self._load_or_init()

    def classify(self, command: str) -> ACLDecision:
        text = (command or "").strip().lower()
        if not text:
            return ACLDecision(False, "info", "", "empty_command")

        entries = self._config.get("commands", [])
        if not isinstance(entries, list):
            entries = []

        for raw in entries:
            if not isinstance(raw, dict):
                continue
            pattern = str(raw.get("pattern", "")).strip().lower()
            if not pattern:
                continue
            enabled = bool(raw.get("enabled", True))
            level = str(raw.get("level", "info")).strip().lower()
            if level not in ALLOWED_LEVELS:
                level = "info"
            if text.startswith(pattern):
                if not enabled:
                    return ACLDecision(False, level, pattern, "command_disabled")
                return ACLDecision(True, level, pattern, "")

        default_level = str(self._config.get("default_level", "info")).strip().lower()
        if default_level not in ALLOWED_LEVELS:
            default_level = "info"
        return ACLDecision(True, default_level, "__default__", "")

