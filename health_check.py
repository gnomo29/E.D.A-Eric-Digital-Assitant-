"""Chequeo rápido de salud del entorno de E.D.A."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Dict

import requests

import config


def _check_module(module_name: str) -> bool:
    return find_spec(module_name) is not None


def run_health_check() -> Dict[str, str]:
    checks: Dict[str, str] = {}

    required_modules = [
        "requests",
        "bs4",
        "pyttsx3",
        "speech_recognition",
        "bleak",
    ]
    for mod in required_modules:
        checks[f"module:{mod}"] = "ok" if _check_module(mod) else "missing"

    try:
        response = requests.get(config.OLLAMA_HEALTH_URL, timeout=3)
        checks["ollama"] = "ok" if response.status_code < 500 else "error"
    except Exception:
        checks["ollama"] = "offline"

    checks["memory_file"] = "ok" if config.MEMORY_FILE.exists() else "missing"
    checks["permissions_mode"] = "strict" if config.ASK_PERMISSION_FOR_SENSITIVE_ACTIONS else "relaxed"
    return checks


def main() -> None:
    results = run_health_check()
    print("=== E.D.A. Health Check ===")
    for key, value in results.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
