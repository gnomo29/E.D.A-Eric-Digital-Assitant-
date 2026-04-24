"""Entrada/salida de voz para E.D.A."""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

from . import config
from .logger import get_logger

log = get_logger("voice")

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

try:
    import speech_recognition as sr
except Exception:
    sr = None


class VoiceEngine:
    """Motor de síntesis y reconocimiento de voz con fallback seguro."""

    def __init__(self) -> None:
        self.enabled = True
        self.listening = False
        self.stt_available = False
        self.tts_available = False

        self._engine = None
        self._recognizer = None
        self._microphone = None
        self._listen_thread: Optional[threading.Thread] = None
        self._speak_queue: "queue.Queue[str]" = queue.Queue()
        self._speak_lock = threading.Lock()
        self._speak_count = 0  # Contador para reiniciar el motor
        self._max_speaks_before_reset = 80  # pyttsx3 se estabiliza mejor con reinicios menos frecuentes

        self._init_tts()
        self._init_stt()
        self._start_speak_worker()

    def _init_tts(self) -> None:
        if pyttsx3 is None:
            log.warning("pyttsx3 no disponible. TTS desactivado.")
            return
        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", config.VOICE_RATE)
            self._engine.setProperty("volume", config.VOICE_VOLUME)
            for voice in self._engine.getProperty("voices"):
                name = str(getattr(voice, "name", "")).lower()
                if "spanish" in name or "es" in name:
                    self._engine.setProperty("voice", voice.id)
                    break
            self.tts_available = True
        except Exception as exc:
            log.error("No se pudo iniciar TTS: %s", exc)
            self._engine = None

    def _init_stt(self) -> None:
        if sr is None:
            log.warning("speech_recognition no disponible. STT desactivado.")
            return
        try:
            self._recognizer = sr.Recognizer()
            self._recognizer.pause_threshold = 0.8
            self._microphone = sr.Microphone()
            self.stt_available = True
        except Exception as exc:
            log.error("No se pudo iniciar micrófono: %s", exc)
            self._recognizer = None
            self._microphone = None

    def _start_speak_worker(self) -> None:
        def worker() -> None:
            while True:
                text = self._speak_queue.get()
                if text == "__STOP__":
                    break
                self._speak_now(text)
                self._speak_queue.task_done()

        threading.Thread(target=worker, daemon=True).start()

    def _reinit_tts_engine(self) -> None:
        """Reinicia el motor TTS para evitar bloqueos."""
        try:
            if self._engine:
                try:
                    self._engine.stop()
                except Exception:
                    pass
            
            self._engine = None
            time.sleep(0.1)  # Pequeña pausa
            
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", config.VOICE_RATE)
            self._engine.setProperty("volume", config.VOICE_VOLUME)
            
            # Configurar voz en español
            for voice in self._engine.getProperty("voices"):
                name = str(getattr(voice, "name", "")).lower()
                if "spanish" in name or "es" in name:
                    self._engine.setProperty("voice", voice.id)
                    break
            
            self.tts_available = True
            log.info("Motor TTS reiniciado correctamente")
        except Exception as exc:
            log.error("Error al reiniciar TTS: %s", exc)
            self._engine = None
            self.tts_available = False

    def _speak_now(self, text: str) -> None:
        if not self.enabled:
            return
        if not self.tts_available or self._engine is None:
            self._reinit_tts_engine()
        if not self.tts_available or self._engine is None:
            return

        try:
            # Reiniciar motor cada cierto número de mensajes para evitar bloqueos
            self._speak_count += 1
            if self._speak_count >= self._max_speaks_before_reset:
                log.info("Reiniciando motor TTS (uso periódico)")
                self._reinit_tts_engine()
                self._speak_count = 0
            
            if not self._engine:
                log.warning("Motor TTS no disponible")
                return
            
            with self._speak_lock:
                self._engine.say(text)
                self._engine.runAndWait()
                
        except RuntimeError as exc:
            # Error común de pyttsx3 - reintentar con motor reiniciado
            log.warning("RuntimeError en TTS, reiniciando motor: %s", exc)
            try:
                self._reinit_tts_engine()
                if self._engine:
                    self._engine.say(text)
                    self._engine.runAndWait()
            except Exception as retry_exc:
                log.error("Error en reintento de habla: %s", retry_exc)
                
        except Exception as exc:
            log.error("Error al hablar: %s", exc)
            # Intentar reiniciar motor para el próximo mensaje
            try:
                self._reinit_tts_engine()
            except Exception:
                pass

    def speak(self, text: str) -> None:
        """Encola texto para hablar sin bloquear GUI."""
        if not text or not self.enabled:
            return
        if not self.tts_available:
            self._reinit_tts_engine()
        self._speak_queue.put(text)

    def _contains_wake_word(self, text: str) -> bool:
        lower_text = text.lower().strip()
        return any(w in lower_text for w in config.WAKE_WORDS)

    def _strip_wake_word(self, text: str) -> str:
        clean = text.strip()
        lower = clean.lower()
        for wake in config.WAKE_WORDS:
            if wake in lower:
                idx = lower.find(wake)
                clean = clean[idx + len(wake) :].strip(" ,.:;-_")
                break
        return clean or text

    def start_listening(self, callback: Callable[[str], None], capture_without_wake: bool = False) -> bool:
        """Escucha en hilo y entrega texto detectado al callback."""
        if self.listening:
            return True
        if not self.stt_available or not self._recognizer or not self._microphone:
            return False

        self.listening = True

        def runner() -> None:
            log.info("Escucha de voz iniciada")
            while self.listening:
                try:
                    with self._microphone as source:
                        self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
                        audio = self._recognizer.listen(
                            source,
                            timeout=config.VOICE_RECOGNITION_TIMEOUT,
                            phrase_time_limit=config.VOICE_PHRASE_TIME_LIMIT,
                        )
                    text = self._recognizer.recognize_google(audio, language="es-ES")
                    if capture_without_wake:
                        callback(text)
                        continue
                    if self._contains_wake_word(text):
                        callback(self._strip_wake_word(text))
                except Exception:
                    time.sleep(0.2)
                    continue
            log.info("Escucha de voz finalizada")

        self._listen_thread = threading.Thread(target=runner, daemon=True)
        self._listen_thread.start()
        return True

    def stop_listening(self) -> None:
        """Detiene escucha de voz."""
        self.listening = False
