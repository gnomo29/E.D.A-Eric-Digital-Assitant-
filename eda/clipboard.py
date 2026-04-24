"""Gestión de portapapeles."""

from __future__ import annotations

import tkinter as tk
from typing import Dict

from .logger import get_logger

log = get_logger("clipboard")

try:
    import pyperclip
except Exception:
    pyperclip = None


class ClipboardManager:
    """Copia y pega texto con fallback a tkinter."""

    def copy(self, text: str) -> Dict[str, str]:
        try:
            if pyperclip is not None:
                pyperclip.copy(text)
            else:
                root = tk.Tk()
                root.withdraw()
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update()
                root.destroy()
            return {"status": "ok", "message": "Texto copiado"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def paste(self) -> Dict[str, str]:
        try:
            if pyperclip is not None:
                value = pyperclip.paste()
            else:
                root = tk.Tk()
                root.withdraw()
                value = root.clipboard_get()
                root.destroy()
            return {"status": "ok", "content": value}
        except Exception as exc:
            log.error("Error leyendo portapapeles: %s", exc)
            return {"status": "error", "message": str(exc)}
