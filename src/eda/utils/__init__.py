"""Utilidades comunes para E.D.A."""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .. import config
from .security import redact_sensitive_data, sanitize_user_input, validate_shell_command

log = logging.getLogger("EDA.utils")


def load_env_dotfile() -> None:
    path = config.BASE_DIR / ".env"
    if not path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        log.debug("python-dotenv no instalado; no se cargó .env")
        return
    load_dotenv(path, override=False)


def ensure_project_dirs() -> None:
    for path in [
        config.MEMORY_DIR,
        config.SOLUTIONS_DIR,
        config.CAPTURES_DIR,
        config.BACKUPS_DIR,
        config.LOGS_DIR,
        config.SUGGESTIONS_DIR,
        config.EXPORTS_DIR,
        config.TEMP_DIR,
        config.CONFIG_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def safe_json_load(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.error("Error leyendo JSON %s: %s", path, exc)
        return default


def safe_json_save(path: Path, data: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.replace(path)
        return True
    except Exception as exc:
        log.error("Error guardando JSON %s: %s", path, exc)
        return False


def run_command(command: str, timeout: int = 20) -> Dict[str, Any]:
    """Ejecuta comando del sistema con validación Zero-Trust."""
    validation = validate_shell_command(command)
    if not validation.allowed:
        return {"ok": False, "code": 403, "stdout": "", "stderr": validation.reason}
    try:
        completed = subprocess.run(
            validation.sanitized,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": completed.returncode == 0,
            "code": completed.returncode,
            "stdout": redact_sensitive_data((completed.stdout or "").strip()),
            "stderr": redact_sensitive_data((completed.stderr or "").strip()),
        }
    except Exception as exc:
        return {"ok": False, "code": -1, "stdout": "", "stderr": redact_sensitive_data(str(exc))}


def detect_platform() -> str:
    return platform.system().lower()


def is_windows() -> bool:
    return os.name == "nt"


def user_desktop_dir() -> Path:
    return Path.home() / "Desktop"


def guarded_call(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    try:
        return {"ok": True, "result": action(*args, **kwargs)}
    except Exception as exc:
        log.exception("Fallo en guarded_call")
        return {"ok": False, "error": redact_sensitive_data(str(exc))}


def build_http_session() -> requests.Session:
    retry = Retry(
        total=config.HTTP_RETRY_TOTAL,
        backoff_factor=config.HTTP_RETRY_BACKOFF,
        status_forcelist=config.HTTP_RETRY_STATUS_CODES,
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def has_internet_connectivity(timeout_sec: float = 1.2) -> bool:
    """Chequeo rápido de conectividad sin llamadas HTTP costosas."""
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=timeout_sec):
            return True
    except Exception:
        return False

