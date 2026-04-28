"""Especialista gaming para Steam/Epic con detección local."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


COMMON_STEAM_PATHS = [
    r"C:\Program Files\Steam\steam.exe",
    r"C:\Program Files (x86)\Steam\steam.exe",
]
COMMON_EPIC_PATHS = [
    r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
    r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
]


def detect_gaming_clients() -> dict[str, str | bool]:
    steam = any(Path(p).exists() for p in COMMON_STEAM_PATHS)
    epic = any(Path(p).exists() for p in COMMON_EPIC_PATHS)
    return {"steam_installed": steam, "epic_installed": epic}


def launch_steam_game(app_id: int) -> dict[str, str]:
    uri = f"steam://run/{int(app_id)}"
    try:
        os.startfile(uri)  # type: ignore[attr-defined]
        return {"status": "ok", "message": f"Lanzando juego Steam {app_id}"}
    except Exception:
        try:
            subprocess.run(["cmd", "/c", "start", "", uri], check=False, timeout=8)
            return {"status": "ok", "message": f"Lanzando juego Steam {app_id}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


def install_or_open_steam_store(app_id: int) -> dict[str, str]:
    uri = f"steam://store/{int(app_id)}"
    try:
        os.startfile(uri)  # type: ignore[attr-defined]
        return {"status": "ok", "message": f"Abriendo tienda Steam para {app_id}"}
    except Exception:
        return {"status": "error", "message": "No pude abrir Steam Store URI."}

