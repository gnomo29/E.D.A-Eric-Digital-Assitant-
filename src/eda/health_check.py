"""Chequeo rápido de salud del entorno de E.D.A."""

from __future__ import annotations

import sys
import time
import threading
from importlib.util import find_spec
from pathlib import Path
from typing import Dict

import requests

from . import config
from . import remote_llm

_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SEC = 30.0
_CACHE_AT = 0.0
_CACHE_VALUE: Dict[str, str] = {}


def _check_module(module_name: str) -> bool:
    return find_spec(module_name) is not None


def _check_windows_audio_stack() -> str:
    """pycaw requiere comtypes en Windows; sin ellos el volumen falla."""
    if not sys.platform.startswith("win"):
        return "n/a"
    if not _check_module("comtypes"):
        return "missing_comtypes"
    if not _check_module("pycaw"):
        return "missing_pycaw"
    try:
        from pycaw.pycaw import AudioUtilities

        devices = AudioUtilities.GetSpeakers()
        if devices is None:
            return "no_device"
        return "ok"
    except Exception as exc:
        return f"warn:{exc.__class__.__name__}"


def _writable_dir(path: Path) -> str:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".eda_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return "ok"
    except OSError as exc:
        return f"error:{exc.__class__.__name__}"


def run_health_check(force: bool = False) -> Dict[str, str]:
    global _CACHE_AT, _CACHE_VALUE
    now = time.time()
    with _CACHE_LOCK:
        if not force and _CACHE_VALUE and (now - _CACHE_AT) <= _CACHE_TTL_SEC:
            return dict(_CACHE_VALUE)

    checks: Dict[str, str] = {}

    required_modules = [
        "requests",
        "urllib3",
        "certifi",
        "bs4",
        "pyttsx3",
        "speech_recognition",
        "bleak",
        "pyautogui",
        "pygetwindow",
        "PIL",
        "duckduckgo_search",
        "obsws_python",
    ]
    for mod in required_modules:
        checks[f"module:{mod}"] = "ok" if _check_module(mod) else "missing"

    optional_modules = [
        ("comtypes", "Windows audio API"),
        ("pycaw", "Windows master volume"),
        ("screen_brightness_control", "Brillo de pantalla"),
        ("pyperclip", "Portapapeles multimodal"),
        ("win32api", "pywin32 (Win32 opcional)"),
        ("spotipy", "Spotify Web API opcional"),
    ]
    for mod, _label in optional_modules:
        checks[f"optional:{mod}"] = "ok" if _check_module(mod) else "missing"

    checks["windows:audio_stack"] = _check_windows_audio_stack()

    try:
        response = requests.get(config.OLLAMA_HEALTH_URL, timeout=3)
        checks["ollama"] = "ok" if response.status_code < 500 else "error"
    except Exception:
        checks["ollama"] = "offline"

    checks["memory_file"] = "ok" if config.MEMORY_FILE.exists() else "missing"
    checks["dir:logs"] = _writable_dir(Path(config.LOGS_DIR))
    checks["dir:memory"] = _writable_dir(Path(config.MEMORY_DIR))
    checks["dir:backups"] = _writable_dir(Path(config.BACKUPS_DIR))
    checks["dir:suggestions"] = _writable_dir(Path(config.SUGGESTIONS_DIR))
    checks["permissions_mode"] = "strict" if config.ASK_PERMISSION_FOR_SENSITIVE_ACTIONS else "relaxed"
    checks["remote_llm"] = remote_llm.health_status()
    checks["remote_llm_mode"] = remote_llm.remote_llm_mode()

    try:
        from eda import spotify_web

        checks["spotify_web"] = spotify_web.describe_integration_status()
    except Exception as exc:
        checks["spotify_web"] = f"error:{exc.__class__.__name__}"

    checks["dir:.cache"] = _writable_dir(Path(config.BASE_DIR) / ".cache")
    with _CACHE_LOCK:
        _CACHE_VALUE = dict(checks)
        _CACHE_AT = time.time()
    return checks


def main() -> None:
    results = run_health_check()
    print("=== E.D.A. Health Check ===")
    for key, value in results.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
