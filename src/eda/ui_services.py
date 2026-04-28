"""Servicios compartidos para interfaces de usuario de E.D.A."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable

from . import config


UI_THEME_PRESETS = {
    "dark": {
        "bg": "#101623",
        "panel": "#1a2438",
        "text": "#e8f2ff",
        "accent": "#57d0ff",
    },
    "light": {
        "bg": "#f2f5fb",
        "panel": "#ffffff",
        "text": "#1b2130",
        "accent": "#1f7ae0",
    },
    # Identidad visual clásica basada en config global.
    "jarvis": {
        "bg": config.THEME_BG,
        "panel": config.THEME_PANEL,
        "text": config.THEME_TEXT,
        "accent": config.THEME_ACCENT,
    },
}


@dataclass
class UICommandResult:
    answer: str
    used_action_agent: bool


class UISharedServices:
    """Lógica reusable de la interfaz gráfica legacy."""

    @staticmethod
    def resolve_text_command(
        *,
        text: str,
        action_agent: Any,
        memory: Any,
        core: Any,
        extra_context: dict[str, Any] | None = None,
    ) -> UICommandResult:
        """Pipeline base: ActionAgent -> fallback Core.ask."""
        handled, action_answer = action_agent.try_handle(text)
        if handled:
            return UICommandResult(answer=action_answer, used_action_agent=True)

        mem = memory.get_memory()
        history = mem.get("chat_history", []) or mem.get("history", [])
        answer = core.ask(text, history=history, extra_context=extra_context) if extra_context else core.ask(text, history=history)
        return UICommandResult(answer=answer, used_action_agent=False)

    @staticmethod
    def persist_interaction(
        *,
        memory: Any,
        user_text: str,
        answer: str,
        parse_command_fn: Callable[[str], Any] | None = None,
        record_behavior: bool = True,
    ) -> None:
        """Persistencia común de conversación y patrones de uso."""
        memory.add_history(user_text, answer)
        if record_behavior and parse_command_fn is not None:
            try:
                parsed = parse_command_fn(user_text)
                memory.record_behavior_event(parsed.intent, parsed.entity, user_text)
            except Exception:
                pass

    @staticmethod
    def dispatch_response(
        *,
        answer: str,
        append_chat_fn: Callable[[str, str], None],
        speak_fn: Callable[[str], None] | None = None,
        status_fn: Callable[[str], None] | None = None,
        status_text: str = "En espera",
        sender: str = "E.D.A.",
    ) -> None:
        """Entrega respuesta a UI y voz en un único punto."""
        append_chat_fn(sender, answer)
        if speak_fn is not None:
            speak_fn(answer)
        if status_fn is not None:
            status_fn(status_text)

    @staticmethod
    def notify_system_alert(
        *,
        title: str,
        message: str,
        chat_message: str | None = None,
        append_chat_fn: Callable[[str, str], None] | None = None,
        popup_fn: Callable[[str, str], None] | None = None,
        speak_fn: Callable[[str], None] | None = None,
        chat_sender: str = "E.D.A.",
        spoken_prefix: str = "Alerta",
    ) -> None:
        """Notificación unificada para alertas del sistema."""
        if append_chat_fn is not None:
            append_chat_fn(chat_sender, chat_message or message)
        if popup_fn is not None:
            popup_fn(title, message)
        if speak_fn is not None:
            speak_fn(f"{spoken_prefix}: {message}")


class VoiceSessionService:
    """Gestión común de sesión de voz para la interfaz gráfica."""

    def __init__(self, voice_input: Any, voice_output: Any | None = None) -> None:
        self.voice_input = voice_input
        self.voice_output = voice_output
        self._active_once_thread: threading.Thread | None = None

    def is_listening(self) -> bool:
        return bool(getattr(self.voice_input, "listening", False))

    def stop_listening(self) -> None:
        if hasattr(self.voice_input, "stop_background"):
            self.voice_input.stop_background()
            return
        if hasattr(self.voice_input, "stop_listening"):
            self.voice_input.stop_listening()

    def start_continuous(self, callback: Callable[[str], None]) -> bool:
        if hasattr(self.voice_input, "available") and not bool(getattr(self.voice_input, "available", True)):
            return False
        if hasattr(self.voice_input, "stt_available") and not bool(getattr(self.voice_input, "stt_available", True)):
            return False
        if hasattr(self.voice_input, "start_background"):
            return bool(self.voice_input.start_background(callback))
        if hasattr(self.voice_input, "start_listening"):
            return bool(self.voice_input.start_listening(callback))
        return False

    def listen_once_async(
        self,
        on_text: Callable[[str], None],
        on_empty: Callable[[], None] | None = None,
        timeout: float = 5.0,
        phrase_time_limit: float = 9.0,
    ) -> bool:
        if hasattr(self.voice_input, "available") and not bool(getattr(self.voice_input, "available", True)):
            return False
        if hasattr(self.voice_input, "stt_available") and not bool(getattr(self.voice_input, "stt_available", True)):
            return False
        if not hasattr(self.voice_input, "listen_once"):
            return False

        def _runner() -> None:
            text = self.voice_input.listen_once(timeout=timeout, phrase_time_limit=phrase_time_limit)
            if text:
                on_text(text)
            elif on_empty is not None:
                on_empty()

        self._active_once_thread = threading.Thread(target=_runner, daemon=True)
        self._active_once_thread.start()
        return True

    def speak(self, text: str) -> None:
        engine = self.voice_output
        if engine is None:
            return
        if hasattr(engine, "speak_async"):
            engine.speak_async(text)
            return
        if hasattr(engine, "speak"):
            engine.speak(text)

    def get_stt_hint(self) -> str:
        if hasattr(self.voice_input, "get_unavailable_hint"):
            return str(self.voice_input.get_unavailable_hint() or "")
        if hasattr(self.voice_input, "get_stt_unavailable_hint"):
            return str(self.voice_input.get_stt_unavailable_hint() or "")
        return ""

