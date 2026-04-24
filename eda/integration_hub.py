"""Estado de integraciones nativas (health/status)."""

from __future__ import annotations

from typing import Dict

from . import config
from .logger import get_logger
from .utils import build_http_session

log = get_logger("integration_hub")


class IntegrationHub:
    def __init__(self) -> None:
        self.http = build_http_session()

    def get_status(self) -> Dict[str, str]:
        status = {
            "ollama": "unknown",
            "obs_websocket": "unknown",
            "spotify_desktop": "unknown",
        }
        # Ollama
        try:
            r = self.http.get(config.OLLAMA_HEALTH_URL, timeout=2)
            status["ollama"] = "online" if r.status_code < 500 else "offline"
        except Exception:
            status["ollama"] = "offline"

        # OBS websocket (check TCP availability via obs controller dependency presence)
        try:
            from obs_controller import OBSController

            status["obs_websocket"] = "ready" if OBSController().available else "missing_dependency"
        except Exception as exc:
            log.debug("OBS status error: %s", exc)
            status["obs_websocket"] = "error"

        # Spotify desktop (best effort by where)
        try:
            import shutil

            spot = shutil.which("spotify") or shutil.which("spotify.exe")
            status["spotify_desktop"] = "found" if spot else "not_found"
        except Exception:
            status["spotify_desktop"] = "unknown"

        return status
