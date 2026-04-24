"""Percepción multimodal básica de contexto local (pantalla/ventanas/clipboard)."""

from __future__ import annotations

from typing import List

from . import config
from .logger import get_logger

log = get_logger("multimodal")

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    import pygetwindow as gw
except Exception:
    gw = None

try:
    import pyperclip
except Exception:
    pyperclip = None


class MultimodalContextCollector:
    """Recolecta señales de entorno para enriquecer decisiones conversacionales."""

    def collect_summary(self) -> str:
        parts: List[str] = []

        if config.MULTIMODAL_ENABLE_SCREEN_CONTEXT and pyautogui is not None:
            try:
                size = pyautogui.size()
                parts.append(f"Pantalla: {size.width}x{size.height}")
            except Exception as exc:
                log.debug("No pude obtener tamaño de pantalla: %s", exc)

        if config.MULTIMODAL_ENABLE_WINDOW_CONTEXT and gw is not None:
            try:
                active = gw.getActiveWindow()
                active_title = (active.title or "").strip() if active else ""
                if active_title:
                    parts.append(f"Ventana activa: {active_title}")
                windows = [w.title.strip() for w in gw.getAllWindows() if (w.title or "").strip()]
                if windows:
                    parts.append(f"Ventanas visibles: {len(windows)}")
            except Exception as exc:
                log.debug("No pude obtener contexto de ventanas: %s", exc)

        if config.MULTIMODAL_ENABLE_CLIPBOARD_CONTEXT and pyperclip is not None:
            try:
                clip = (pyperclip.paste() or "").strip()
                if clip:
                    preview = clip[:120].replace("\n", " ")
                    parts.append(f"Clipboard: {preview}")
            except Exception as exc:
                log.debug("No pude obtener clipboard: %s", exc)

        return " | ".join(parts).strip()
