"""Text-to-speech ligero y no bloqueante."""

from __future__ import annotations

import queue
import threading
from typing import Optional

from .logger import get_logger

log = get_logger("tts")

try:
    import pyttsx3
except Exception:
    pyttsx3 = None


class TTSManager:
    """TTS offline con pyttsx3, carga perezosa y cola asíncrona."""

    def __init__(
        self,
        language: str = "es",
        rate: int = 175,
        volume: float = 1.0,
        pitch: int = 0,
        max_queue_size: int = 5,
    ) -> None:
        self.language = language
        self.rate = int(rate)
        self.volume = max(0.0, min(1.0, float(volume)))
        self.pitch = int(pitch)
        self.enabled = True
        self.max_queue_size = max(2, int(max_queue_size))

        self._engine = None
        self._queue: "queue.Queue[tuple[int, str]]" = queue.Queue()
        self._lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._available = pyttsx3 is not None

        self._start_worker()

    @property
    def available(self) -> bool:
        return self._available

    def _ensure_engine(self) -> bool:
        if not self._available:
            return False
        if self._engine is not None:
            return True
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)
            self._select_voice(engine)
            self._engine = engine
            return True
        except Exception as exc:
            log.error("No pude iniciar TTS: %s", exc)
            self._engine = None
            self._available = False
            return False

    def _select_voice(self, engine) -> None:
        target = "spanish" if self.language.lower().startswith("es") else "english"
        try:
            for voice in engine.getProperty("voices"):
                name = str(getattr(voice, "name", "")).lower()
                vid = str(getattr(voice, "id", "")).lower()
                if target in name or target in vid:
                    engine.setProperty("voice", voice.id)
                    return
        except Exception:
            pass

    def _start_worker(self) -> None:
        def runner() -> None:
            while True:
                item = self._queue.get()
                if not item:
                    self._queue.task_done()
                    continue
                priority, text = item
                if text == "__STOP__":
                    self._queue.task_done()
                    break
                self._speak_now(text)
                self._queue.task_done()

        self._worker = threading.Thread(target=runner, daemon=True)
        self._worker.start()

    def set_language(self, language: str) -> None:
        self.language = language
        self._reconfigure()

    def set_rate(self, rate: int) -> None:
        self.rate = int(rate)
        self._reconfigure()

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, float(volume)))
        self._reconfigure()

    def set_pitch(self, pitch: int) -> None:
        # pyttsx3 no expone pitch portable; lo guardamos para proveedores futuros.
        self.pitch = int(pitch)

    def _reconfigure(self) -> None:
        if not self._ensure_engine() or self._engine is None:
            return
        try:
            self._engine.setProperty("rate", self.rate)
            self._engine.setProperty("volume", self.volume)
            self._select_voice(self._engine)
        except Exception:
            pass

    def speak_async(self, text: str) -> None:
        if not self.enabled or not text.strip():
            return
        self._enqueue(text.strip(), priority=10)

    def speak_error(self, text: str) -> None:
        """Encola mensajes críticos por delante de respuestas normales."""
        if not text.strip():
            return
        self._enqueue(text.strip(), priority=1)

    def _enqueue(self, text: str, priority: int) -> None:
        with self._queue_lock:
            items: list[tuple[int, str]] = []
            while not self._queue.empty():
                try:
                    items.append(self._queue.get_nowait())
                    self._queue.task_done()
                except queue.Empty:
                    break

            # Evitar saturación: conservar mensajes más prioritarios y recientes.
            items.append((int(priority), text))
            items.sort(key=lambda x: x[0])
            if len(items) > self.max_queue_size:
                items = items[: self.max_queue_size]

            for item in items:
                self._queue.put(item)

    def stop(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass

    def shutdown(self) -> None:
        self.stop()
        self.clear_queue()
        self._queue.put((0, "__STOP__"))

    def clear_queue(self) -> None:
        with self._queue_lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break

    def _speak_now(self, text: str) -> None:
        if not self.enabled:
            return
        if not self._ensure_engine() or self._engine is None:
            return
        try:
            with self._lock:
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception as exc:
            log.warning("Error en TTS, reiniciando engine: %s", exc)
            self._engine = None
