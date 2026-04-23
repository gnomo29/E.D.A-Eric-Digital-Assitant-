"""Control de mouse y teclado mediante pyautogui."""

from __future__ import annotations

from typing import Dict, Tuple

from logger import get_logger

log = get_logger("mouse_keyboard")

try:
    import pyautogui
except Exception:
    pyautogui = None


class MouseKeyboardController:
    """Envoltura segura para automatización de entrada."""

    def __init__(self) -> None:
        self.available = pyautogui is not None
        if self.available:
            pyautogui.FAILSAFE = True

    def position(self) -> Tuple[int, int] | None:
        if not self.available:
            return None
        return pyautogui.position()

    def move(self, x: int, y: int, duration: float = 0.2) -> Dict[str, str]:
        if not self.available:
            return {"status": "error", "message": "pyautogui no disponible"}
        try:
            pyautogui.moveTo(x, y, duration=duration)
            return {"status": "ok", "message": f"Mouse movido a ({x}, {y})"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def click(self, x: int | None = None, y: int | None = None, button: str = "left") -> Dict[str, str]:
        if not self.available:
            return {"status": "error", "message": "pyautogui no disponible"}
        try:
            pyautogui.click(x=x, y=y, button=button)
            return {"status": "ok", "message": "Click ejecutado"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def type_text(self, text: str, interval: float = 0.02) -> Dict[str, str]:
        if not self.available:
            return {"status": "error", "message": "pyautogui no disponible"}
        try:
            pyautogui.write(text, interval=interval)
            return {"status": "ok", "message": "Texto escrito"}
        except Exception as exc:
            log.error("Error escribiendo texto: %s", exc)
            return {"status": "error", "message": str(exc)}

    def hotkey(self, *keys: str) -> Dict[str, str]:
        if not self.available:
            return {"status": "error", "message": "pyautogui no disponible"}
        try:
            pyautogui.hotkey(*keys)
            return {"status": "ok", "message": f"Hotkey ejecutada: {'+'.join(keys)}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
