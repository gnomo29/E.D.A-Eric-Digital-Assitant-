"""Visión de pantalla: captura optimizada + consulta a Ollama Vision."""

from __future__ import annotations

import base64
import io
from typing import Optional, Sequence

from . import config
from .logger import get_logger
from .utils import build_http_session

log = get_logger("vision")

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    from PIL import Image
except Exception:
    Image = None  # type: ignore[assignment]


class VisionService:
    """Servicio liviano para capturar y analizar pantalla con Ollama."""

    DEFAULT_MODELS: Sequence[str] = ("llava", "moondream")
    MAX_WIDTH = 1280
    MAX_HEIGHT = 720
    JPEG_QUALITY = 72

    def __init__(self) -> None:
        self.http = build_http_session()
        self.tags_endpoint = config.OLLAMA_TAGS_URL
        self.generate_endpoint = config.OLLAMA_URL

    def capture_screen(self, region: Optional[tuple[int, int, int, int]] = None) -> bytes:
        """Captura pantalla completa o región y la comprime para uso de RAM controlado."""
        if pyautogui is None or Image is None:
            raise RuntimeError("Captura de pantalla no disponible (pyautogui/Pillow no instalados).")

        image = pyautogui.screenshot(region=region)
        if image is None:
            raise RuntimeError("No se pudo capturar la pantalla.")

        optimized = self._optimize_image(image)
        buffer = io.BytesIO()
        optimized.save(buffer, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)
        return buffer.getvalue()

    def analyze_screen(
        self,
        prompt: str = "¿Qué hay en mi pantalla?",
        *,
        region: Optional[tuple[int, int, int, int]] = None,
        preferred_model: str = "",
    ) -> dict[str, str]:
        """Captura y consulta un modelo de visión de Ollama."""
        try:
            payload_image = self.capture_screen(region=region)
        except Exception as exc:
            return {"status": "error", "message": f"No pude capturar pantalla: {exc}"}

        model = preferred_model.strip() or self._pick_vision_model()
        if not model:
            return {
                "status": "error",
                "message": "No encontré modelos de visión en Ollama. Instala uno como llava o moondream.",
            }

        encoded = base64.b64encode(payload_image).decode("ascii")
        payload = {
            "model": model,
            "prompt": prompt.strip() or "Describe esta captura.",
            "images": [encoded],
            "stream": False,
        }
        try:
            response = self.http.post(self.generate_endpoint, json=payload, timeout=40)
            response.raise_for_status()
            data = response.json() if response.content else {}
            answer = (data.get("response") or "").strip()
            if not answer:
                return {"status": "error", "message": f"El modelo {model} no devolvió una respuesta útil."}
            return {"status": "ok", "message": answer, "model": model}
        except Exception as exc:
            log.warning("Fallo consulta vision model=%s: %s", model, exc)
            return {"status": "error", "message": f"No pude analizar la captura con {model}: {exc}"}

    def _pick_vision_model(self) -> str:
        try:
            response = self.http.get(self.tags_endpoint, timeout=6)
            response.raise_for_status()
            data = response.json() if response.content else {}
            models = data.get("models") or []
            names = [str(item.get("name", "")).split(":")[0].lower() for item in models if isinstance(item, dict)]
            for preferred in self.DEFAULT_MODELS:
                if preferred in names:
                    return preferred
        except Exception:
            pass
        return ""

    def _optimize_image(self, image: "Image.Image") -> "Image.Image":
        """Redimensiona con límite conservador para evitar picos de memoria."""
        if Image is None:
            return image
        optimized = image.convert("RGB")
        optimized.thumbnail((self.MAX_WIDTH, self.MAX_HEIGHT), Image.Resampling.LANCZOS)
        return optimized
