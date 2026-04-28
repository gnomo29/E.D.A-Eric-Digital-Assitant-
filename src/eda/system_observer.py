"""Observación de sistema de bajo consumo."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from . import config
from .logger import get_logger

log = get_logger("system_observer")


class SystemObserver:
    """Recolector ligero de estado del sistema para decisiones del agente."""

    def __init__(self, captures_dir: Path | None = None) -> None:
        self.captures_dir = captures_dir or config.CAPTURES_DIR
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(self, include_processes: bool = False, include_dir: str = "", include_screenshot: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "memory": {},
            "cpu_percent": None,
            "processes": [],
            "directory_sample": [],
            "screenshot_path": "",
        }

        try:
            import psutil

            vm = psutil.virtual_memory()
            payload["memory"] = {
                "total_mb": int(vm.total / (1024 * 1024)),
                "used_mb": int(vm.used / (1024 * 1024)),
                "available_mb": int(vm.available / (1024 * 1024)),
                "percent": float(vm.percent),
            }
            payload["cpu_percent"] = float(psutil.cpu_percent(interval=0.1))
            if include_processes:
                procs: List[Dict[str, Any]] = []
                for proc in psutil.process_iter(["name", "memory_info"]):
                    try:
                        info = proc.info
                        rss = int((info.get("memory_info").rss if info.get("memory_info") else 0) / (1024 * 1024))
                        procs.append({"name": str(info.get("name", "")), "rss_mb": rss})
                    except Exception:
                        continue
                payload["processes"] = sorted(procs, key=lambda x: x.get("rss_mb", 0), reverse=True)[:8]
        except Exception as exc:
            log.debug("psutil no disponible para observer: %s", exc)

        if include_dir:
            try:
                p = Path(include_dir).expanduser()
                if p.exists() and p.is_dir():
                    payload["directory_sample"] = [item.name for item in sorted(p.iterdir())[:25]]
            except Exception as exc:
                log.debug("No pude listar directorio '%s': %s", include_dir, exc)

        if include_screenshot:
            shot = self._capture_compressed()
            if shot:
                payload["screenshot_path"] = shot

        return payload

    def _capture_compressed(self) -> str:
        try:
            import pyautogui
            from PIL import Image

            image = pyautogui.screenshot()
            image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
            out = self.captures_dir / f"screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            image.save(out, format="JPEG", optimize=True, quality=45)
            image.close()
            return str(out)
        except Exception as exc:
            log.debug("Captura comprimida no disponible: %s", exc)
            return ""
