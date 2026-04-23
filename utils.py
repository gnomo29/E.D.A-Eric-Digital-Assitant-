"""Utilidades comunes para E.D.A."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

import config
import requests
from logger import get_logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = get_logger("utils")


def ensure_project_dirs() -> None:
    """Crea carpetas base del proyecto si no existen."""
    for path in [
        config.MEMORY_DIR,
        config.SOLUTIONS_DIR,
        config.CAPTURES_DIR,
        config.BACKUPS_DIR,
        config.LOGS_DIR,
        config.SUGGESTIONS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    """Retorna timestamp simple para nombres de archivo."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def safe_json_load(path: Path, default: Any) -> Any:
    """Lee JSON con fallback robusto."""
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.error("Error leyendo JSON %s: %s", path, exc)
        return default


def safe_json_save(path: Path, data: Any) -> bool:
    """Guarda JSON de forma segura usando escritura atómica."""
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
    """Ejecuta comando del sistema de forma protegida."""
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": completed.returncode == 0,
            "code": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except Exception as exc:
        return {"ok": False, "code": -1, "stdout": "", "stderr": str(exc)}


def detect_platform() -> str:
    """Detecta plataforma principal."""
    return platform.system().lower()


def is_windows() -> bool:
    """Indica si el sistema actual es Windows."""
    return os.name == "nt"


def user_desktop_dir() -> Path:
    """Retorna escritorio del usuario actual de forma multiplataforma."""
    return Path.home() / "Desktop"


def guarded_call(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Ejecuta una función y captura errores uniformemente."""
    try:
        return {"ok": True, "result": action(*args, **kwargs)}
    except Exception as exc:
        log.exception("Fallo en guarded_call")
        return {"ok": False, "error": str(exc)}


def build_http_session() -> requests.Session:
    """Crea una sesión HTTP con retries y headers comunes."""
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
