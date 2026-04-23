"""Información del sistema, red y clima."""

from __future__ import annotations

from datetime import datetime
from typing import Dict

import requests

import config

try:
    import psutil
except Exception:
    psutil = None

from logger import get_logger

log = get_logger("system_info")


class SystemInfo:
    """Recolector de estado del sistema."""

    def get_metrics(self) -> Dict[str, str]:
        if psutil is None:
            return {
                "cpu": "N/D",
                "ram": "N/D",
                "time": datetime.now().strftime("%H:%M:%S"),
                "bluetooth": "Desconocido",
                "ollama": "N/D",
            }

        vm = psutil.virtual_memory()
        bt_status = "Activo" if psutil.net_if_stats() else "N/D"
        return {
            "cpu": f"{psutil.cpu_percent(interval=0.25):.0f}%",
            "ram": f"{vm.used // (1024**3):.1f}GB/{vm.total // (1024**3)}GB",
            "time": datetime.now().strftime("%H:%M:%S"),
            "bluetooth": bt_status,
            "ollama": "Activo" if self.is_ollama_up() else "Inactivo",
        }

    def is_ollama_up(self) -> bool:
        try:
            r = requests.get(config.OLLAMA_HEALTH_URL, timeout=2)
            return r.status_code < 500
        except Exception:
            return False

    def get_weather(self, city: str = "La Paz") -> str:
        """Obtiene clima rápido desde wttr.in (sin API key)."""
        try:
            url = f"https://wttr.in/{city}?format=3"
            r = requests.get(url, timeout=8)
            if r.ok:
                return r.text.strip()
        except Exception as exc:
            log.warning("No se pudo obtener clima: %s", exc)
        return "Clima no disponible"
