"""Control de OBS por websocket (v5) con fallback seguro."""

from __future__ import annotations

from typing import Dict

from . import config
from .logger import get_logger

log = get_logger("obs_controller")

try:
    from obsws_python import ReqClient
except Exception:
    ReqClient = None


class OBSController:
    """Wrapper mínimo para cambiar escena en OBS vía websocket."""

    def __init__(self) -> None:
        self.available = ReqClient is not None

    def set_scene(self, scene_name: str) -> Dict[str, str]:
        if not self.available:
            return {"status": "error", "message": "obsws-python no disponible"}
        name = (scene_name or "").strip()
        if not name:
            return {"status": "error", "message": "Nombre de escena vacío"}
        try:
            client = ReqClient(
                host=config.OBS_WS_HOST,
                port=int(config.OBS_WS_PORT),
                password=config.OBS_WS_PASSWORD,
                timeout=3,
            )
            client.set_current_program_scene(name)
            return {"status": "ok", "message": f"Escena cambiada a {name}"}
        except Exception as exc:
            log.warning("No pude cambiar escena en OBS vía websocket: %s", exc)
            return {"status": "error", "message": str(exc)}
