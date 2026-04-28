"""Gestión de revocación de skills firmadas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .. import config
from . import safe_json_load, safe_json_save


def _default_payload() -> dict[str, Any]:
    return {"revoked": {}}


def load_revocations(path: Path | None = None) -> dict[str, Any]:
    target = path or config.REVOCATIONS_FILE
    payload = safe_json_load(target, _default_payload())
    if not isinstance(payload, dict):
        return _default_payload()
    revoked = payload.get("revoked")
    if not isinstance(revoked, dict):
        payload["revoked"] = {}
    return payload


def is_revoked(skill_file: str, path: Path | None = None) -> bool:
    payload = load_revocations(path)
    revoked = payload.get("revoked", {})
    return str(skill_file) in revoked


def revoke_skill(skill_file: str, reason: str = "", path: Path | None = None) -> bool:
    target = path or config.REVOCATIONS_FILE
    payload = load_revocations(target)
    revoked = payload.get("revoked", {})
    revoked[str(skill_file)] = {
        "reason": reason.strip() or "manual_revoke",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    payload["revoked"] = revoked
    return safe_json_save(target, payload)


def unrevoke_skill(skill_file: str, path: Path | None = None) -> bool:
    target = path or config.REVOCATIONS_FILE
    payload = load_revocations(target)
    revoked = payload.get("revoked", {})
    revoked.pop(str(skill_file), None)
    payload["revoked"] = revoked
    return safe_json_save(target, payload)


def list_revoked(path: Path | None = None) -> dict[str, Any]:
    payload = load_revocations(path)
    revoked = payload.get("revoked", {})
    return revoked if isinstance(revoked, dict) else {}

