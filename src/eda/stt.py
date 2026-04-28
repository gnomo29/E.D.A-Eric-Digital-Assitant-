"""Speech-to-text ligero con carga bajo demanda."""

from __future__ import annotations

import threading
import time
import re
import unicodedata
from typing import Callable, Optional

from .logger import get_logger
from . import config

log = get_logger("stt")

try:
    import speech_recognition as sr
except Exception:
    sr = None


class STTManager:
    """STT local-first (Sphinx si está), con fallback de red mínima."""

    def __init__(self, language: str = "es-ES") -> None:
        self.language = language
        self.enabled = True
        self.listening = False
        self.available = False
        self.unavailable_reason = ""

        self._recognizer = None
        self._microphone = None
        self._listen_thread: Optional[threading.Thread] = None
        self._continuous_thread: Optional[threading.Thread] = None
        self._continuous_stop = threading.Event()
        self._continuous_active = False

    def _ensure_backend(self) -> bool:
        if not getattr(config, "VOICE_INPUT_ENABLED", True):
            self.unavailable_reason = "Entrada de voz deshabilitada por configuración."
            self.available = False
            return False
        if self._recognizer is not None and self._microphone is not None:
            return True
        if sr is None:
            self.unavailable_reason = "speech_recognition no está instalado."
            return False
        try:
            recognizer = sr.Recognizer()
            recognizer.dynamic_energy_threshold = True
            recognizer.energy_threshold = 280
            recognizer.pause_threshold = 0.75
            recognizer.non_speaking_duration = 0.35
            microphone = sr.Microphone()
            self._recognizer = recognizer
            self._microphone = microphone
            self.available = True
            self.unavailable_reason = ""
            return True
        except Exception as exc:
            log.error("No pude inicializar STT: %s", exc)
            self.available = False
            msg = str(exc).lower()
            if "pyaudio" in msg or "portaudio" in msg:
                self.unavailable_reason = (
                    "PyAudio no disponible en este entorno. "
                    "Instala con: pip install pipwin && pipwin install pyaudio"
                )
            else:
                self.unavailable_reason = f"Micrófono no disponible: {exc}"
            return False

    def set_language(self, language: str) -> None:
        if language and language.strip():
            self.language = language.strip()

    def listen_once(self, timeout: float = 5.0, phrase_time_limit: float = 10.0) -> str:
        """Escucha una frase y retorna texto; vacío si falla."""
        if not self.enabled or not self._ensure_backend():
            return ""
        if self._recognizer is None or self._microphone is None:
            return ""
        try:
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.35)
                audio = self._recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)

            # Offline-first: pocketsphinx si está disponible.
            try:
                text = self._recognizer.recognize_sphinx(audio, language=self.language)
                if text and text.strip():
                    return text.strip()
            except Exception:
                pass

            # Fallback de red mínima.
            try:
                text = self._recognizer.recognize_google(audio, language=self.language)
                return text.strip()
            except Exception:
                return ""
        except Exception:
            return ""

    def start_background(self, callback: Callable[[str], None]) -> bool:
        """Escucha continua en hilo sin bloquear la interfaz."""
        if self.listening:
            return True
        if not self._ensure_backend():
            return False
        self.listening = True

        def runner() -> None:
            while self.listening:
                text = self.listen_once(timeout=4.0, phrase_time_limit=9.0)
                if text:
                    try:
                        callback(text)
                    except Exception:
                        log.exception("Error en callback STT")
                time.sleep(0.05)

        self._listen_thread = threading.Thread(target=runner, daemon=True)
        self._listen_thread.start()
        return True

    def stop_background(self) -> None:
        self.listening = False

    def get_unavailable_hint(self) -> str:
        if self.available:
            return ""
        if self.unavailable_reason:
            return self.unavailable_reason
        return (
            "STT desactivado. Si estás en Windows, instala pipwin y pyaudio; "
            "si falla, usa Build Tools (C++) o conda-forge."
        )

    @staticmethod
    def _normalize_token(text: str) -> str:
        raw = (text or "").strip().lower()
        decomp = unicodedata.normalize("NFKD", raw)
        no_acc = "".join(ch for ch in decomp if not unicodedata.combining(ch))
        clean = re.sub(r"[^\w\s]", " ", no_acc)
        return re.sub(r"\s+", " ", clean).strip()

    def _detect_wakeword(self, text: str, wake_word: str) -> tuple[bool, float]:
        normalized = self._normalize_token(text)
        key = self._normalize_token(wake_word)
        if not normalized or not key:
            return False, 0.0
        tokens = normalized.split()
        if key in tokens:
            return True, 0.95
        if key in normalized:
            return True, 0.7
        return False, 0.0

    @property
    def continuous_active(self) -> bool:
        return bool(self._continuous_active)

    def stop_continuous_listener(self) -> None:
        self._continuous_stop.set()
        self._continuous_active = False

    def start_continuous_listener(
        self,
        *,
        on_command: Callable[[str], None],
        on_state: Callable[[str, float], None] | None = None,
        on_wakeword: Callable[[str], None] | None = None,
        wake_word: str = "eda",
        sensitivity: float = 0.6,
        post_activation_window: float = 5.0,
    ) -> bool:
        """
        Escucha continua ligera:
        - WAIT_WAKEWORD: escucha segmentos cortos y espera wakeword.
        - POST_ACTIVATION: capta orden durante una ventana corta.
        """
        if self._continuous_active:
            return True
        if not self._ensure_backend():
            return False
        self._continuous_stop.clear()
        self._continuous_active = True

        def _set_state(name: str, confidence: float = 0.0) -> None:
            if on_state is not None:
                try:
                    on_state(name, confidence)
                except Exception:
                    log.exception("Error notificando estado de escucha continua")

        def runner() -> None:
            _set_state("wait_wakeword", 0.0)
            while not self._continuous_stop.is_set():
                heard = self.listen_once(timeout=2.0, phrase_time_limit=2.5)
                if not heard:
                    time.sleep(0.05)
                    continue
                detected, confidence = self._detect_wakeword(heard, wake_word)
                if not detected or confidence < max(0.1, min(1.0, sensitivity)):
                    _set_state("wait_wakeword", confidence)
                    continue
                _set_state("post_activation", confidence)
                if on_wakeword is not None:
                    try:
                        on_wakeword(heard)
                    except Exception:
                        log.exception("Error en callback de wakeword")
                end_t = time.time() + max(1.0, float(post_activation_window))
                command_text = ""
                while time.time() < end_t and not self._continuous_stop.is_set():
                    chunk = self.listen_once(timeout=2.0, phrase_time_limit=4.0)
                    if not chunk:
                        continue
                    chunk_norm = self._normalize_token(chunk)
                    wake_norm = self._normalize_token(wake_word)
                    if chunk_norm == wake_norm:
                        continue
                    if chunk_norm.startswith(wake_norm + " "):
                        chunk = chunk[len(wake_word) :].strip(" ,.:;!?")
                    command_text = chunk.strip()
                    if command_text:
                        break
                if command_text:
                    _set_state("processing", confidence)
                    try:
                        on_command(command_text)
                    except Exception:
                        log.exception("Error en callback de comando continuo")
                _set_state("wait_wakeword", 0.0)
            _set_state("idle", 0.0)
            self._continuous_active = False

        self._continuous_thread = threading.Thread(target=runner, daemon=True, name="eda-continuous-listener")
        self._continuous_thread.start()
        return True
