"""Interfaz gráfica estilo JARVIS para E.D.A."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
import re
from collections import deque
from tkinter import messagebox, scrolledtext
from urllib.parse import quote_plus

from . import config
from .actions import ActionController
from .audit_log import audit_event
from . import remote_llm
from .bluetooth_manager import BluetoothManager
from .core import EDACore
from .evolution import EvolutionEngine
from .logger import get_logger
from .memory import MemoryManager
from .mouse_keyboard import MouseKeyboardController
from .nlp_utils import (
    detect_confirmation,
    detect_secondary_action,
    normalize_learned_trigger_key,
    parse_command,
    split_compound_command,
)
from .obs_controller import OBSController
from .improvement_planner import ImprovementPlanner
from .integration_hub import IntegrationHub
from .multimodal import MultimodalContextCollector
from .objective_planner import ObjectivePlan, ObjectivePlanner, PlanStep
from .optimizer import Optimizer
from .security_levels import SecurityDecision, SecurityManager
from .scheduler import ReminderScheduler, parse_reminder_request
from .spotify_web import is_spotipy_installed, is_web_api_configured, try_play_via_web_api
from .system_info import SystemInfo
from .voice import VoiceEngine
from .web_solver import WebSolver

log = get_logger("gui")


def _resolve_learned_module_path(module_name: str) -> Path:
    """Ruta al .py de una habilidad aprendida (acepta rutas con o sin prefijo eda/)."""
    name = (module_name or "").strip().replace("\\", "/")
    if not name:
        return config.BASE_DIR
    direct = config.BASE_DIR / name
    if direct.is_file():
        return direct
    tail = Path(name).name
    under_eda = config.BASE_DIR / "eda" / tail
    if under_eda.is_file():
        return under_eda
    return direct


class EDAGUI:
    """GUI principal de E.D.A con paneles y ejecución multihilo."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("E.D.A. - Asistente Autónomo")
        self.root.geometry("1366x768")
        self.root.minsize(1180, 700)
        self.root.configure(bg=config.THEME_BG)

        self.memory = MemoryManager()
        self.core = EDACore(memory_manager=self.memory)
        self.voice = VoiceEngine()
        self.voice.enabled = True
        self.system_info = SystemInfo()
        self.optimizer = Optimizer()
        self.bt = BluetoothManager()
        self.evolution = EvolutionEngine(config.BASE_DIR)
        self.web_solver = WebSolver(self.core, self.memory)
        self.improvement_planner = ImprovementPlanner(config.BASE_DIR)
        self.obs = OBSController()
        self.integrations = IntegrationHub()
        self.multimodal = MultimodalContextCollector()
        self.security = SecurityManager()
        self.objective_planner = ObjectivePlanner()
        self.actions = ActionController(confirm_callback=self.confirm_critical)
        self.mouse_keyboard = MouseKeyboardController()
        self.reminders = ReminderScheduler(on_due=self._on_reminder_due)
        self.reminders.start()
        self.pending_auto_learn: dict = {}
        self.current_objective: ObjectivePlan | None = None
        self._executing_objective = False

        self.status_text = tk.StringVar(value="Inicializando")
        self.cpu_text = tk.StringVar(value="CPU_LOAD: --")
        self.ram_text = tk.StringVar(value="MEM_USAGE: --")
        self.time_text = tk.StringVar(value="HORA: --")
        self.bt_text = tk.StringVar(value="BLUETOOTH: --")
        self.ollama_text = tk.StringVar(value="OLLAMA: --")
        self.security_text = tk.StringVar(value="SEGURIDAD: --")

        self._mic_pulse_active = False
        self._mic_pulse_step = 0
        self._chat_animation_queue: deque[tuple[str, str, int]] = deque()
        self._chat_animating = False

        self._build_layout()
        self._refresh_ui_font_from_memory()
        self._start_background_loops()
        self._restore_persisted_reminders()
        self._restore_objective_state()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.append_chat_animated("E.D.A.", "Protocolos de inicialización completados. Todos los servicios están en espera.")
        self.append_chat_animated("E.D.A.", "¿Cuáles son sus órdenes, señor?")
        self._set_status("En espera")

    def _on_close(self) -> None:
        self.reminders.stop()
        self.root.destroy()

    def _persist_reminders(self) -> None:
        self.memory.save_reminders(self.reminders.list_pending())

    def _persist_objective_state(self) -> None:
        if self.current_objective is None:
            self.memory.save_objectives([])
            return
        self.memory.save_objectives([self.current_objective.to_dict()])

    def _restore_persisted_reminders(self) -> None:
        restored_count = 0
        for item in self.memory.get_reminders():
            if isinstance(item, dict) and self.reminders.add_existing(item):
                restored_count += 1
        if restored_count:
            self.append_chat("E.D.A.", f"Recordatorios restaurados: {restored_count}")
            self._persist_reminders()

    def _restore_objective_state(self) -> None:
        objectives = self.memory.get_objectives()
        if not objectives:
            return
        latest = objectives[-1]
        steps = latest.get("steps", []) if isinstance(latest, dict) else []
        if not isinstance(steps, list):
            return
        plan = ObjectivePlan(goal=str(latest.get("goal", "")))
        plan.created_at = str(latest.get("created_at", plan.created_at))
        plan.steps = [PlanStep(text=str(s.get("text", "")), done=bool(s.get("done", False))) for s in steps if isinstance(s, dict)]
        self.current_objective = plan

    def _build_layout(self) -> None:
        container = tk.Frame(self.root, bg=config.THEME_BG)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        left = tk.Frame(container, bg=config.THEME_BG)
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(container, bg=config.THEME_PANEL, width=340)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        title = tk.Label(
            left,
            text="RouteLLM / E.D.A.",
            bg=config.THEME_BG,
            fg=config.THEME_TEXT,
            font=("Consolas", 19, "bold"),
        )
        title.pack(anchor="w", pady=(0, 8))

        status_panel = tk.Frame(left, bg=config.THEME_PANEL)
        status_panel.pack(fill="x", pady=(0, 8))

        status = tk.Label(
            status_panel,
            textvariable=self.status_text,
            bg=config.THEME_PANEL,
            fg=config.THEME_ACCENT,
            font=("Consolas", 12, "bold"),
            padx=12,
            pady=8,
        )
        status.pack(side="left", fill="x", expand=True)

        self.ollama_indicator = tk.Label(
            status_panel,
            text="●",
            bg=config.THEME_PANEL,
            fg=config.THEME_WARNING,
            font=("Consolas", 14, "bold"),
            padx=10,
        )
        self.ollama_indicator.pack(side="right")

        self.chat_box = scrolledtext.ScrolledText(
            left,
            bg="#070b19",
            fg="#e3f8ff",
            insertbackground=config.THEME_TEXT,
            font=("Consolas", 12),
            wrap="word",
            state="disabled",
            relief="flat",
        )
        self.chat_box.pack(fill="both", expand=True)
        self.chat_box.tag_configure("sender_user", foreground="#7bdfff", font=("Consolas", 12, "bold"))
        self.chat_box.tag_configure("sender_assistant", foreground="#00ffaa", font=("Consolas", 12, "bold"))
        self.chat_box.tag_configure("msg_body", foreground="#e3f8ff", font=("Consolas", 12))

        bottom = tk.Frame(left, bg=config.THEME_BG)
        bottom.pack(fill="x", pady=(10, 0))

        self.mic_button = tk.Button(
            bottom,
            text="🎤",
            width=4,
            command=self.toggle_microphone,
            bg="#2f2f2f",
            fg="white",
            relief="flat",
        )
        self.mic_button.pack(side="left", padx=(0, 8))

        self.entry = tk.Entry(
            bottom,
            bg="#0f1630",
            fg=config.THEME_TEXT,
            insertbackground=config.THEME_TEXT,
            font=("Consolas", 12),
            relief="flat",
        )
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self.on_send())
        # Ctrl+L lo usa Spotify (barra de búsqueda); no enlazarlo aquí o la automatización
        # de música vacía el chat si el foco vuelve a E.D.A. Limpiar chat: Ctrl+Mayús+L.
        self.root.bind("<Control-Shift-L>", lambda _e: self.action_clear_chat())
        self.root.bind("<Control-s>", lambda _e: self.action_export_chat())

        send_btn = tk.Button(
            bottom,
            text="ENVIAR",
            command=self.on_send,
            bg="#113355",
            fg="white",
            relief="flat",
            padx=14,
            pady=6,
        )
        send_btn.pack(side="left", padx=(8, 0))

        tk.Label(right, text="ESTADO", bg=config.THEME_PANEL, fg=config.THEME_TEXT, font=("Consolas", 13, "bold")).pack(
            anchor="w", padx=12, pady=(14, 8)
        )

        self._side_value(right, self.cpu_text)
        self._side_value(right, self.ram_text)
        self._side_value(right, self.time_text)
        self._side_value(right, self.bt_text)
        self._side_value(right, self.ollama_text)
        self._side_value(right, self.security_text)

        tk.Label(right, text="ACCIONES", bg=config.THEME_PANEL, fg=config.THEME_TEXT, font=("Consolas", 13, "bold")).pack(
            anchor="w", padx=12, pady=(20, 8)
        )

        self._side_button(right, "Guía y ejemplos", self.action_usage_guide)
        self._side_button(right, "Configuración", self.action_config)
        self._side_button(right, "Permisos", self.action_permissions_panel)
        self._side_button(right, "Olvidar patrones", self.action_clear_behavior_patterns)
        self._side_button(right, "Voz siempre ON", self.action_toggle_voice)
        self._side_button(right, "Limpiar chat (Ctrl+Mayús+L)", self.action_clear_chat)
        self._side_button(right, "Borrar memoria", self.action_clear_memory)
        self._side_button(right, "Exportar chat", self.action_export_chat)
        self._side_button(right, "Evolución", self.action_evolution)
        self._side_button(right, "Bluetooth", self.action_bluetooth)
        self._side_button(right, "Optimizar", self.action_optimize)

    def _side_value(self, parent: tk.Widget, var: tk.StringVar) -> None:
        tk.Label(parent, textvariable=var, bg=config.THEME_PANEL, fg="#b7f2ff", font=("Consolas", 11)).pack(
            anchor="w", padx=14, pady=3
        )

    def _side_button(self, parent: tk.Widget, text: str, cmd) -> None:
        btn = tk.Button(
            parent,
            text=text,
            command=cmd,
            bg="#1b274f",
            fg="white",
            relief="flat",
            activebackground="#254082",
            activeforeground="white",
            cursor="hand2",
            bd=0,
            padx=10,
            pady=7,
        )
        btn.pack(fill="x", padx=12, pady=5)

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_text.set(text))

    def _append_chat(self, sender: str, text: str) -> None:
        ts = datetime.now().strftime("%H:%M")
        sender_label = f"[{ts}] {sender}: "
        sender_tag = "sender_assistant" if sender.strip().lower().startswith("e.d.a") else "sender_user"
        self.chat_box.config(state="normal")
        self.chat_box.insert("end", "\n")
        self.chat_box.insert("end", sender_label, sender_tag)
        self.chat_box.insert("end", f"{text}\n", "msg_body")
        self.chat_box.config(state="disabled")
        self.chat_box.see("end")

    def append_chat(self, sender: str, text: str) -> None:
        self.root.after(0, lambda: self._append_chat(sender, text))

    def append_chat_animated(self, sender: str, text: str, step_ms: int = 18) -> None:
        """Animación de texto tipo escritura sin bloquear GUI y sin solapar mensajes."""
        self._chat_animation_queue.append((sender, text, step_ms))
        self.root.after(0, self._start_next_animation)

    def _start_next_animation(self) -> None:
        if self._chat_animating or not self._chat_animation_queue:
            return

        sender, text, step_ms = self._chat_animation_queue.popleft()
        self._chat_animating = True
        ts = datetime.now().strftime("%H:%M")
        sender_label = f"[{ts}] {sender}: "
        sender_tag = "sender_assistant" if sender.strip().lower().startswith("e.d.a") else "sender_user"

        self.chat_box.config(state="normal")
        self.chat_box.insert("end", "\n")
        self.chat_box.insert("end", sender_label, sender_tag)
        self.chat_box.config(state="disabled")
        self._typewrite(text, 0, step_ms)

    def _typewrite(self, text: str, idx: int, step_ms: int) -> None:
        if idx >= len(text):
            self.chat_box.config(state="normal")
            self.chat_box.insert("end", "\n")
            self.chat_box.config(state="disabled")
            self.chat_box.see("end")
            self._chat_animating = False
            self.root.after(0, self._start_next_animation)
            return

        self.chat_box.config(state="normal")
        self.chat_box.insert("end", text[idx], "msg_body")
        self.chat_box.config(state="disabled")
        self.chat_box.see("end")
        self.root.after(step_ms, lambda: self._typewrite(text, idx + 1, step_ms))

    def on_send(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self.append_chat("Eric", text)
        threading.Thread(target=self._process_user_message_safe, args=(text,), daemon=True).start()

    def _process_user_message_safe(self, text: str) -> None:
        try:
            self._process_user_message(text)
        except Exception as exc:
            log.exception("Error procesando mensaje")
            self.append_chat("E.D.A.", f"Señor, ocurrió un error controlado: {exc}")
            self._set_status("Modo degradado")

    def _execute_secondary_action(self, secondary_text: str, opened_app: str) -> str:
        """Ejecuta una acción secundaria tras abrir una app."""
        action_name, payload = detect_secondary_action(secondary_text)
        log.info(
            "[CMD_PARSE] secondary raw='%s' action='%s' payload='%s' opened_app='%s'",
            secondary_text,
            action_name,
            payload,
            opened_app,
        )

        if not action_name:
            # Misma política solicitada: subacciones desconocidas disparan autoaprendizaje.
            learn_task = f"en {opened_app}, {secondary_text.strip()}"
            intro = (
                "No tengo esa subacción implementada todavía, señor. "
                "Activaré autoaprendizaje para investigarla en internet y repositorios."
            )
            self.append_chat("E.D.A.", intro)
            return self._start_auto_learn(learn_task, intent="secondary_action")

        # Intentar traer al frente la ventana de la app recién abierta.
        activation = self.actions.activate_app_window(opened_app)
        if activation.get("status") != "ok":
            log.warning("[CMD_PARSE] No pude activar ventana de '%s': %s", opened_app, activation.get("message"))

        if action_name == "write_text":
            if not payload:
                return "Abrí la aplicación, pero faltó el texto a escribir."

            # Caso común para Word: crear documento nuevo si el usuario lo pide.
            if "hoja en blanco" in secondary_text.lower() or "documento en blanco" in secondary_text.lower():
                self.mouse_keyboard.hotkey("ctrl", "n")
                time.sleep(0.8)

            typed = self.mouse_keyboard.type_text(payload)
            if typed.get("status") == "ok":
                return f"Abriendo {opened_app} y escribiendo el texto."
            return f"Abrí {opened_app}, pero no pude escribir automáticamente: {typed.get('message', 'error desconocido')}"

        if action_name == "search_web":
            if not payload:
                return f"Abrí {opened_app}, pero faltó el texto de búsqueda."
            if self._normalize_web_target(opened_app) == "spotify":
                ok, msg = self._play_spotify_query(payload)
                if ok:
                    return f"Abriendo Spotify y reproduciendo: {payload}."
                return msg
            typed = self.mouse_keyboard.type_text(payload)
            if typed.get("status") == "ok":
                self.mouse_keyboard.hotkey("enter")
                return f"Abriendo {opened_app} y buscando: {payload}."
            return f"Abrí {opened_app}, pero no pude escribir la búsqueda: {typed.get('message', 'error desconocido')}"

        return "Abrí la aplicación, pero no supe completar la acción secundaria."

    @staticmethod
    def _normalize_trigger_text(text: str) -> str:
        return normalize_learned_trigger_key(text)

    def _try_learn_automation_rule(self, user_text: str) -> str | None:
        """
        Aprende reglas tipo:
        - "quiero que <acción> cada vez que te diga <gatillo>"
        - "cuando te diga <gatillo> haz <acción>"
        """
        text = (user_text or "").strip()
        normalized = self._normalize_trigger_text(text)
        if not normalized:
            return None

        # Formato A: "quiero que <acción> cada vez que diga/pida <gatillo>"
        m1 = re.search(
            r"quiero que\s+(.+?)\s+cada vez que(?:\s+te)?\s+(?:diga|pida|digo)\s+(.+)$",
            normalized,
        )
        if m1:
            action = m1.group(1).strip(" ,.;:")
            trigger = m1.group(2).strip(" ,.;:")
            if action and trigger:
                self.memory.learn_command(trigger, action)
                return f"He aprendido la automatización. Cuando diga '{trigger}', ejecutaré: {action}."

        # Formato B: "cada vez que diga/pida <gatillo> haz/hagas <acción>"
        m2 = re.search(
            r"cada vez que(?:\s+te)?\s+(?:diga|pida|digo)\s+(.+?)\s+(?:haz|hace|hagas|quiero que)\s+(.+)$",
            normalized,
        )
        if m2:
            trigger = m2.group(1).strip(" ,.;:")
            action = m2.group(2).strip(" ,.;:")
            if action and trigger:
                self.memory.learn_command(trigger, action)
                return f"Automatización guardada. Trigger: '{trigger}' -> Acción: {action}."

        # Formato C: "cuando diga/pida <gatillo> haz/hagas <acción>"
        m3 = re.search(
            r"cuando(?:\s+te)?\s+(?:diga|pida|digo)\s+(.+?)\s+(?:haz|hace|hagas|quiero que)\s+(.+)$",
            normalized,
        )
        if m3:
            trigger = m3.group(1).strip(" ,.;:")
            action = m3.group(2).strip(" ,.;:")
            if action and trigger:
                self.memory.learn_command(trigger, action)
                return f"Automatización guardada. Trigger: '{trigger}' -> Acción: {action}."

        # Formato D: "agrega acción <Y> al comando <X>"
        m4 = re.search(
            r"agrega(?:r)?\s+(?:accion|acción)\s+(.+?)\s+al\s+comando\s+(.+)$",
            normalized,
        )
        if m4:
            action = m4.group(1).strip(" ,.;:")
            trigger = m4.group(2).strip(" ,.;:")
            if action and trigger:
                self.memory.learn_command(trigger, action, append=True)
                total = len(self.memory.get_learned_actions(trigger))
                return f"Acción agregada al trigger '{trigger}'. Total de acciones encadenadas: {total}."

        return None

    def _execute_automation_action(self, action_text: str) -> str:
        """
        Ejecuta acciones aprendidas por trigger.
        Incluye caso especial: OBS + escena nombrada.
        """
        action = (action_text or "").strip()
        chain_parts = split_compound_command(action)
        if len(chain_parts) > 1:
            messages = []
            for sub_action in chain_parts:
                result = self._execute_single_automation_action(sub_action)
                messages.append(result)
                time.sleep(0.35)
            return " ".join(messages)

        return self._execute_single_automation_action(action)

    def _execute_single_automation_action(self, action_text: str) -> str:
        """Ejecuta una sola acción de automatización."""
        action = (action_text or "").strip()
        normalized = self._normalize_trigger_text(action)
        if not normalized:
            return "La automatización no tiene una acción válida."

        # Caso especial solicitado: abrir OBS y cambiar a escena por nombre.
        scene_match = re.search(r"(?:abre|abrir|me abras)\s+obs.*escena llamada\s+(.+)$", normalized)
        if scene_match:
            scene_name = scene_match.group(1).strip()
            opened = self.actions.open_app("obs")
            if opened.get("status") != "ok":
                return "No pude abrir OBS para ejecutar la automatización."
            time.sleep(2.0)
            ws_result = self.obs.set_scene(scene_name)
            if ws_result.get("status") == "ok":
                return f"Abrí OBS y cambié a la escena '{scene_name}' por websocket."
            self.actions.activate_app_window("obs")
            # Fallback best-effort por UI.
            self.mouse_keyboard.hotkey("ctrl", "f")
            time.sleep(0.4)
            self.mouse_keyboard.type_text(scene_name)
            time.sleep(0.2)
            self.mouse_keyboard.hotkey("enter")
            return f"Abrí OBS e intenté cambiar a la escena '{scene_name}' (fallback UI)."

        # Reproducir música (Spotify) desde reglas aprendidas, p. ej. "reproducir queen".
        spot_play = re.match(r"^(?:reproduce|reproducir|pon|ponme)\s+(.+)$", normalized)
        if spot_play:
            if not self._is_action_family_allowed("automation"):
                return "La reproducción en automatización está bloqueada por permisos."
            q = spot_play.group(1).strip()
            if not q:
                return "La automatización de reproducción no tiene título de canción."
            ok, msg = self._play_spotify_query(q)
            if ok:
                return f"Reproduciendo {q} en Spotify (automatización)."
            return f"No pude reproducir en Spotify: {msg}"

        # Volumen / brillo / cerrar app: mismos intents que el chat principal.
        parsed_auto = parse_command(action)
        if parsed_auto.intent == "volume":
            if not self._is_action_family_allowed("system"):
                return "Volumen bloqueado por permisos."
            return self._handle_volume_command(action)
        if parsed_auto.intent == "brightness":
            if not self._is_action_family_allowed("system"):
                return "Brillo bloqueado por permisos."
            return self._handle_brightness_command(action)
        if parsed_auto.intent == "close_app":
            if not self._is_action_family_allowed("system"):
                return "Cerrar aplicaciones bloqueado por permisos."
            target = (parsed_auto.entity or action).strip()
            result = self.actions.close_app(target)
            if result.get("status") == "ok":
                return result.get("message", "Aplicación cerrada.")
            return result.get("message", "No pude cerrar la aplicación.")

        # Reutiliza acciones existentes para frases simples.
        if normalized.startswith(("abre ", "abrir ", "me abras ")):
            target = normalized.split(" ", 1)[1].strip() if " " in normalized else normalized
            result = self.actions.open_app(target)
            if result.get("status") == "ok":
                return result.get("message", "Automatización ejecutada.")
            web_result = self._open_web_target(target)
            if web_result is not None:
                return web_result.get("message", "Automatización web ejecutada.")
            return "No pude ejecutar la automatización de apertura."

        # Fallback: intentar como comando compuesto de apertura ya existente.
        compound = self._try_handle_compound_open_command(action, action)
        if compound:
            return compound

        return "Automatización aprendida, pero esta acción aún no tiene ejecutor específico."

    def _build_capabilities_report(self) -> str:
        """
        Resumen dinámico de capacidades basado en módulos/código cargado.
        Esto permite responder "qué puedes hacer" mirando su propia implementación.
        """
        capabilities = [
            "Conversación y respuestas con IA local (Ollama) + búsqueda web de respaldo",
            "Comandos de sistema: abrir/cerrar apps, volumen, brillo, mute",
            "Recordatorios con voz, popup, persistencia y cancelación por ID",
            "Automatizaciones aprendidas por gatillo (frase -> acción)",
            "Navegación web inteligente (Google, YouTube, Spotify, Steam)",
            "Detección de dispositivos USB conectados",
            "Bluetooth: escaneo y resumen de dispositivos",
            "Autoaprendizaje: investiga web/repos, genera código y pide confirmación",
        ]
        extra = []
        if getattr(self.obs, "available", False):
            extra.append("Integración OBS por websocket para cambiar escenas")
        if getattr(self.mouse_keyboard, "available", False):
            extra.append("Automatización de teclado/mouse para tareas en apps")
        if getattr(self.voice, "tts_available", False):
            extra.append("Respuesta hablada siempre activa (modo JARVIS)")
        if is_spotipy_installed() and is_web_api_configured():
            extra.append("Spotify vía Web API (spotipy + variables de entorno); sin eso, automatización de escritorio")

        lines = [f"- {item}" for item in capabilities + extra]
        return "Estas son mis capacidades actuales, señor:\n" + "\n".join(lines)

    def _play_spotify_query(self, query: str) -> tuple[bool, str]:
        """
        Ejecuta búsqueda y reproducción en Spotify desktop.
        Retorna (ok, mensaje_error_o_info).
        """
        q = (query or "").strip()
        if not q:
            return False, "No recibí texto de canción para Spotify."
        # Camino preferido: Web API (token en .cache/, ver .env.example).
        try:
            status, detail = try_play_via_web_api(q)
            if status == "ok":
                return True, f"web_api:{detail}"
            if status == "fail":
                log.info("[SPOTIFY] Web API no pudo reproducir (%s); fallback desktop.", detail)
        except Exception as exc:
            log.warning("[SPOTIFY] Web API excepción: %s", exc)
        # Fallback: escritorio (URI + atajos de teclado).
        # Intento 1: abrir búsqueda directa en Spotify app por URI.
        uri_open = self.actions.open_website(f"spotify:search:{quote_plus(q)}")
        if uri_open.get("status") != "ok":
            # Intento 2: abrir app manualmente.
            opened = self.actions.open_app("spotify")
            if opened.get("status") != "ok":
                return False, "No pude abrir Spotify de escritorio."
        self.actions.activate_app_window("spotify")
        time.sleep(1.2)
        # Reafirmar foco en Spotify antes de enviar atajos (si quedan en E.D.A., Ctrl+L/K afectan la GUI).
        self.actions.activate_app_window("spotify")
        time.sleep(0.45)
        # Flujo recomendado en desktop: Ctrl+K abre búsqueda rápida; Enter reproduce el resultado.
        # (Ctrl+L también enfoca búsqueda en muchas versiones; probamos ambos.)
        self.mouse_keyboard.hotkey("ctrl", "k")
        time.sleep(0.35)
        self.mouse_keyboard.hotkey("ctrl", "a")
        time.sleep(0.05)
        self.mouse_keyboard.hotkey("backspace")
        time.sleep(0.05)
        typed = self.mouse_keyboard.type_text(q)
        if typed.get("status") != "ok":
            log.warning("[SPOTIFY] type_text falló: %s", typed.get("message"))
        time.sleep(0.2)
        self.mouse_keyboard.press("enter")
        time.sleep(1.1)
        # A veces el primer Enter solo confirma búsqueda; el segundo inicia reproducción.
        self.mouse_keyboard.press("enter")
        time.sleep(0.45)
        # Navegación por teclado al primer resultado (best-effort).
        self.mouse_keyboard.press("down")
        time.sleep(0.12)
        self.mouse_keyboard.press("enter")
        time.sleep(0.35)
        # Último recurso: tecla multimedia play/pause (si hay cola o foco en reproductor).
        self.mouse_keyboard.press("playpause")
        time.sleep(0.2)
        # Fallback adicional: barra de búsqueda principal (Ctrl+L en Spotify) y repetir.
        self.actions.activate_app_window("spotify")
        time.sleep(0.5)
        self.mouse_keyboard.hotkey("ctrl", "l")
        time.sleep(0.25)
        self.mouse_keyboard.hotkey("ctrl", "a")
        time.sleep(0.05)
        self.mouse_keyboard.hotkey("backspace")
        time.sleep(0.05)
        typed2 = self.mouse_keyboard.type_text(q)
        if typed2.get("status") == "ok":
            self.mouse_keyboard.press("enter")
            time.sleep(1.0)
            self.mouse_keyboard.press("enter")
            time.sleep(0.35)
            self.mouse_keyboard.press("playpause")
        return True, "OK"

    def _extract_capability_learning_request(self, text: str) -> str:
        """
        Detecta pedidos tipo:
        - "consigue la habilidad de acceder a la cámara"
        - "aprende a controlar la cámara"
        """
        normalized = self._normalize_trigger_text(text)
        patterns = [
            r"(?:consigue|adquiere|obtén|obtiene)\s+la\s+habilidad\s+de\s+(.+)$",
            r"(?:aprende|aprender)\s+a\s+(.+)$",
            r"(?:quiero\s+que\s+aprendas\s+a)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                task = match.group(1).strip()
                if task:
                    return task
        return ""

    def _should_force_auto_learn(self, user_text: str, parsed_intent: str) -> bool:
        """
        Decide si debe activar autoaprendizaje cuando no entiende un pedido.
        Enfocado en frases de acción/tarea, evitando charla casual.
        """
        if parsed_intent not in {"chat", "question"}:
            return False

        normalized = self._normalize_trigger_text(user_text)
        if len(normalized) < 6:
            return False

        casual = {
            "hola",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "gracias",
            "como estas",
            "qué tal",
            "que tal",
            "quien eres",
            "como te llamas",
        }
        if normalized in casual:
            return False

        action_markers = (
            "abre",
            "abrir",
            "entra",
            "entrar",
            "configura",
            "configurar",
            "instala",
            "instalar",
            "conecta",
            "conectar",
            "controla",
            "controlar",
            "automatiza",
            "automatizar",
            "descarga",
            "descargar",
            "reproduce",
            "reproducir",
            "haz",
            "hace",
            "quiero que",
            "necesito que",
        )
        return any(marker in normalized for marker in action_markers)

    @staticmethod
    def _normalize_web_target(name: str) -> str:
        cleaned = re.sub(r"[^\w\s.-]", " ", (name or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _open_web_target(self, target_name: str) -> dict | None:
        """
        Abre destinos web conocidos o inferidos y persiste la URL para reutilizarla.
        Retorna None si no corresponde a objetivo web.
        """
        normalized = self._normalize_web_target(target_name)
        if not normalized:
            return None

        known = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "gmail": "https://mail.google.com",
            "spotify": "https://open.spotify.com",
            "steam": "https://store.steampowered.com",
            "github": "https://github.com",
        }
        if normalized in known:
            key = f"web_url::{normalized}"
            cached = self.memory.recall(key)
            url = cached or known[normalized]
            opened = self.actions.open_website(url)
            if opened.get("status") == "ok":
                self.memory.remember(key, url)
                return {"status": "ok", "message": f"Abriendo {normalized} en navegador, señor.", "opened_target": normalized}
            return {"status": "error", "message": f"No pude abrir {normalized} en navegador.", "opened_target": normalized}

        # Si no es app conocida, intentamos tratarlo como sitio web.
        token = re.sub(r"[^a-z0-9.-]", "", normalized.replace(" ", ""))
        if token and len(token) >= 3:
            candidate_url = f"https://www.{token}.com"
            opened = self.actions.open_website(candidate_url)
            if opened.get("status") == "ok":
                self.memory.remember(f"web_url::{normalized}", candidate_url)
                return {"status": "ok", "message": f"Abriendo {normalized} en navegador, señor.", "opened_target": normalized}

        return None

    def _should_prefer_desktop_app(self, target_name: str) -> bool:
        """Determina si conviene abrir app nativa antes que web."""
        normalized = self._normalize_web_target(target_name)
        desktop_first = {
            "spotify",
            "steam",
            "discord",
            "whatsapp",
            "cursor",
            "vscode",
            "code",
            "chrome",
            "firefox",
            "notepad",
            "calc",
            "explorer",
        }
        return normalized in desktop_first

    def _try_handle_compound_open_command(self, text: str, opened_app: str) -> str | None:
        """Maneja comandos compuestos tipo: 'abre X y escribe Y'."""
        parts = split_compound_command(text)
        if len(parts) < 2:
            return None

        # Si la primera parte no parece de apertura, no lo tomamos como comando compuesto de apertura.
        first = parse_command(parts[0])
        if first.intent != "open_app":
            return None

        # Acción 1: abrir app o destino web.
        first_target = first.entity or opened_app
        # Prioridad: abrir programa de escritorio; web solo como fallback.
        open_result = self.actions.open_app(first_target)
        if open_result.get("status") != "ok":
            open_result = self._open_web_target(first_target) or open_result
        if open_result.get("status") != "ok":
            return open_result.get("message", "No pude abrir la aplicación.")

        # Espera corta para que abra la ventana antes de la acción 2.
        time.sleep(2.5)

        # Acción 2..n: ejecutarlas secuencialmente.
        secondary_messages = []
        for secondary in parts[1:]:
            secondary_messages.append(self._execute_secondary_action(secondary, first_target))
            time.sleep(0.4)

        return " ".join(secondary_messages)

    def _execute_learned_skill(self, skill_payload: dict, user_text: str) -> str:
        module_name = str(skill_payload.get("module", "")).strip()
        function_name = str(skill_payload.get("function", "")).strip()
        if not module_name or not function_name:
            return "Tengo registrada esa habilidad, pero su definición está incompleta."

        module_path = _resolve_learned_module_path(module_name)
        result = self.web_solver.execute_generated_function(module_path, function_name, user_text)
        if result.get("status") == "ok":
            return str(result.get("message", "Habilidad aprendida ejecutada."))
        return f"Intenté ejecutar la habilidad aprendida, pero falló: {result.get('message', 'error desconocido')}"

    def _handle_pending_auto_learn_confirmation(self, user_text: str) -> str | None:
        if not self.pending_auto_learn:
            return None

        normalized = (user_text or "").strip().lower()
        if "ver codigo" in normalized or "ver código" in normalized:
            code = self.pending_auto_learn.get("code", "")
            if not code:
                return "No tengo código generado para mostrar en este momento."
            return f"Código aprendido:\n```python\n{code}\n```\nResponde SÍ para aplicar o NO para cancelar."

        confirmation = detect_confirmation(user_text)
        if confirmation is False:
            self.pending_auto_learn = {}
            return "Entendido, señor. Cancelé la mejora automática."

        if confirmation is True:
            payload = dict(self.pending_auto_learn)
            self.pending_auto_learn = {}

            evolve_result = self.evolution.evolve_module(payload.get("module", ""), payload.get("code", ""))
            if evolve_result.get("status") != "ok":
                return f"No pude aplicar la auto-mejora: {evolve_result.get('message', 'error desconocido')}"

            skill_name = str(payload.get("skill_name", payload.get("function", "habilidad")))
            execute_now = self.web_solver.execute_generated_function(
                _resolve_learned_module_path(str(payload.get("module", ""))),
                str(payload.get("function", "")),
                str(payload.get("original_user_text", "")),
            )
            execution_msg = execute_now.get("message", "") if isinstance(execute_now, dict) else ""
            if execute_now.get("status") == "ok":
                self.memory.save_learned_skill(
                    skill_name=skill_name,
                    trigger=str(payload.get("trigger", "")).strip(),
                    module=str(payload.get("module", "")).strip(),
                    function_name=str(payload.get("function", "")).strip(),
                )
                audit_event(
                    "autolearn_apply",
                    module=str(payload.get("module", ""))[:240],
                    function=str(payload.get("function", ""))[:120],
                    skill=skill_name[:120],
                )
                log.info("[EVOLUTION] Skill aplicada y validada: %s", skill_name)
                return (
                    f"✓ He mejorado mi código. Ahora puedo {payload.get('task', 'hacer esta acción')}. "
                    f"Ejecutando ahora: {execution_msg}"
                )

            # Política anti-simulación: si no ejecuta, no se considera aprendido.
            try:
                backups = evolve_result.get("backups", []) if isinstance(evolve_result, dict) else []
                if isinstance(backups, list) and backups:
                    backup_file = Path(str(backups[0]))
                    target = _resolve_learned_module_path(str(payload.get("module", "")))
                    if backup_file.exists() and target.exists():
                        target.write_text(backup_file.read_text(encoding="utf-8"), encoding="utf-8")
                        log.warning("[EVOLUTION] Revertido módulo por fallo de validación en ejecución: %s", target)
            except Exception as exc:
                log.error("[EVOLUTION] Error intentando revertir cambio no validado: %s", exc)

            self.memory.forget_learned_skill(skill_name)
            return (
                "No voy a fingir que aprendí algo que no funciona, señor. "
                f"La ejecución falló ({execution_msg}) y revertí el cambio para mantener estabilidad."
            )

        return "Tengo una mejora pendiente. Responde: SÍ, NO o VER CÓDIGO."

    def _start_auto_learn(self, user_text: str, intent: str = "") -> str:
        task = (user_text or "").strip()
        self.append_chat("E.D.A.", self.core.auto_learn_intro(task))
        self._set_status("AUTO_LEARN investigando...")
        log.info("[AUTO_LEARN] Activado para: %s", task)

        planner_notes = ""
        try:
            plan = self.improvement_planner.build_plan(
                task,
                include_web=self._is_action_family_allowed("web"),
                web_solver=self.web_solver,
            )
            planner_notes = self.improvement_planner.compact_context_for_llm(plan)
        except Exception as exc:
            log.warning("[AUTO_LEARN] planner context omitido: %s", exc)

        generated = self.web_solver.generate_autolearn_payload(task, intent=intent, planner_notes=planner_notes)
        if generated.get("status") != "ok":
            self._set_status("En espera")
            return f"Intenté auto-aprender, pero no logré generar código seguro: {generated.get('message', 'error desconocido')}"

        self.pending_auto_learn = {
            "task": generated.get("task", task),
            "module": generated.get("module", "eda/skills_auto.py"),
            "function": generated.get("function", ""),
            "code": generated.get("code", ""),
            "trigger": task,
            "skill_name": generated.get("function", ""),
            "original_user_text": user_text,
        }
        libs = generated.get("libraries", [])
        libs_txt = ", ".join(libs) if libs else "(sin librerías externas)"
        review = str(generated.get("review_notes", "") or "").strip()
        review_block = f"\n\nRevisión externa opcional (LLM remoto):\n{review}" if review else ""
        self._set_status("Esperando confirmación")
        return (
            f"He aprendido cómo {task}. He generado código Python para implementarlo en {generated.get('module')}. "
            f"Librerías detectadas: {libs_txt}.\n"
            "Solo confirmaré que aprendí si funciona al ejecutarlo; si falla, revertiré el cambio.\n"
            f"¿Puedo mejorar mi código para agregar esta funcionalidad? [SÍ] [NO] [VER CÓDIGO]{review_block}"
        )

    def _respond_and_store(self, user_text: str, answer: str) -> None:
        """Respuesta estándar: persistencia, chat, voz y estado."""
        final_answer = self._ensure_jarvis_treatment(answer)
        self.memory.add_history(user_text, final_answer)
        try:
            pq = parse_command(user_text)
            self.memory.record_behavior_event(pq.intent, pq.entity, user_text)
        except Exception as exc:
            log.debug("behavior_event: %s", exc)
        self.append_chat_animated("E.D.A.", final_answer)
        self.voice.speak(final_answer)
        self._set_status("En espera")

    @staticmethod
    def _ensure_jarvis_treatment(answer: str) -> str:
        """
        Asegura el tratamiento estilo JARVIS ("señor") en respuestas al usuario.
        No duplica si ya está presente.
        """
        text = (answer or "").strip()
        if not text:
            return "Señor."
        lowered = text.lower()
        if "señor" in lowered:
            return text
        if lowered.startswith(("si ", "sí ", "ok", "entendido", "perfecto", "listo", "claro")):
            return f"{text}, señor."
        return f"Señor, {text[0].lower() + text[1:] if len(text) > 1 else text.lower()}"

    def _confirm_sensitive_intent(self, intent: str, user_text: str) -> bool:
        """Pide permiso opcional para intents sensibles configurables."""
        if not config.ASK_PERMISSION_FOR_SENSITIVE_ACTIONS:
            return True
        sensitive_intents = {"close_app", "optimize", "evolve"}
        if intent not in sensitive_intents:
            return True
        return messagebox.askyesno(
            "Confirmar acción sensible",
            "Esta acción puede cambiar el estado del sistema.\n"
            f"Intento detectado: {intent}\n"
            f"Comando: {user_text}\n\n"
            "¿Desea continuar?",
        )

    def _process_user_message(self, text: str) -> None:
        self._set_status("Procesando comando...")

        normalized_text = (text or "").strip().lower()

        # Recordatorios: el texto puede mencionar "apagar" u otras palabras sensibles
        # en el *mensaje futuro*, no como orden inmediata. No aplicar bloqueo de alto riesgo.
        parsed_reminder = parse_reminder_request(text)
        if parsed_reminder is not None:
            security_decision = SecurityDecision(True, "low", "Recordatorio programado")
        else:
            security_decision = self.security.assess(text)

        # Seguridad por niveles (bloqueo preventivo de alto riesgo).
        if not security_decision.allowed:
            self._respond_and_store(
                text,
                f"Bloqueé este comando por seguridad ({security_decision.risk}), señor. "
                "Confírmelo de forma más explícita si desea continuar.",
            )
            return

        pattern_clear_triggers = (
            "borra patrones de uso",
            "borrar patrones de uso",
            "olvidá mis patrones",
            "olvida mis patrones",
            "olvida mis hábitos de uso",
            "borrar historial de patrones",
        )
        if any(t in normalized_text for t in pattern_clear_triggers):
            ok = self.memory.clear_behavior_events()
            self._respond_and_store(
                text,
                "He olvidado los patrones de uso guardados, señor."
                if ok
                else "No pude borrar los patrones en este momento, señor.",
            )
            return

        if normalized_text.startswith(("objetivo ", "planifica ", "planificar ")):
            goal = re.sub(r"^(objetivo|planifica|planificar)\s+", "", normalized_text).strip()
            if goal:
                self.current_objective = self.objective_planner.build_plan(goal)
                self._persist_objective_state()
                steps_txt = "\n".join(f"- {s.text}" for s in self.current_objective.steps)
                self._respond_and_store(text, f"Objetivo planificado, señor:\n{steps_txt}")
                return

        if any(k in normalized_text for k in ["siguiente paso del objetivo", "estado del objetivo"]):
            if not self.current_objective:
                self._respond_and_store(text, "No hay un objetivo activo, señor.")
                return
            step = self.current_objective.next_pending()
            if not step:
                self._respond_and_store(text, "El objetivo actual ya está completado, señor.")
                return
            self._respond_and_store(text, f"Siguiente paso del objetivo: {step.text}")
            return

        if any(k in normalized_text for k in ["ejecuta siguiente paso", "ejecutar siguiente paso"]):
            if not self.current_objective:
                self._respond_and_store(text, "No hay objetivo activo para ejecutar, señor.")
                return
            if self._executing_objective:
                self._respond_and_store(text, "Ya estoy ejecutando un paso de objetivo, señor.")
                return
            step = self.current_objective.next_pending()
            if not step:
                self._respond_and_store(text, "No quedan pasos pendientes en el objetivo, señor.")
                return
            self._executing_objective = True
            try:
                self._process_user_message(step.text)
                self.current_objective.mark_next_done()
                if self.current_objective.is_completed():
                    self.memory.archive_objective(self.current_objective.to_dict())
                    self.current_objective = None
                self._persist_objective_state()
            finally:
                self._executing_objective = False
            return

        if any(k in normalized_text for k in ["ejecuta objetivo completo", "ejecutar objetivo completo", "completa el objetivo"]):
            if not self.current_objective:
                self._respond_and_store(text, "No hay objetivo activo para ejecutar, señor.")
                return
            if self._executing_objective:
                self._respond_and_store(text, "Ya estoy ejecutando un objetivo, señor.")
                return
            if not self._is_action_family_allowed("automation"):
                self._respond_and_store(text, "La ejecución automática está bloqueada por permisos, señor.")
                return
            self._executing_objective = True
            executed = 0
            try:
                while self.current_objective and self.current_objective.next_pending():
                    step = self.current_objective.next_pending()
                    if step is None:
                        break
                    self._process_user_message(step.text)
                    self.current_objective.mark_next_done()
                    executed += 1
                    if executed >= 10:
                        break
                if self.current_objective and self.current_objective.is_completed():
                    self.memory.archive_objective(self.current_objective.to_dict())
                    self.current_objective = None
                self._persist_objective_state()
                self._respond_and_store(text, f"Objetivo ejecutado en modo autónomo. Pasos procesados: {executed}.")
            finally:
                self._executing_objective = False
            return

        if any(k in normalized_text for k in ["estado de integraciones", "integraciones", "health integraciones"]):
            status = self.integrations.get_status()
            report = "\n".join(f"- {k}: {v}" for k, v in status.items())
            self._respond_and_store(text, f"Estado de integraciones, señor:\n{report}")
            return

        if any(
            q in normalized_text
            for q in [
                "que puedes hacer",
                "qué puedes hacer",
                "cuales son tus habilidades",
                "cuáles son tus habilidades",
                "que habilidades tienes",
                "qué habilidades tienes",
            ]
        ):
            self._respond_and_store(text, self._build_capabilities_report())
            return

        capability_task = self._extract_capability_learning_request(text)
        if capability_task:
            if not self._is_action_family_allowed("learning"):
                self._respond_and_store(text, "El autoaprendizaje está bloqueado por permisos, señor.")
                return
            preface = (
                f"Entendido, señor. Investigaré cómo {capability_task} en internet y repositorios; "
                "antes de aplicar cualquier mejora haré backup automático del código."
            )
            self.append_chat("E.D.A.", preface)
            answer = self._start_auto_learn(f"aprender a {capability_task}", intent="capability_upgrade")
            self._respond_and_store(text, answer)
            return

        learn_auto_answer = self._try_learn_automation_rule(text)
        if learn_auto_answer:
            if not self._is_action_family_allowed("automation"):
                self._respond_and_store(text, "No puedo registrar automatizaciones: permisos de automation bloqueados, señor.")
                return
            self._respond_and_store(text, learn_auto_answer)
            return

        learned_actions = self.memory.get_learned_actions(self._normalize_trigger_text(text))
        if learned_actions:
            if not self._is_action_family_allowed("automation"):
                self._respond_and_store(text, "Las automatizaciones están bloqueadas por permisos, señor.")
                return
            messages = []
            for action in learned_actions:
                messages.append(self._execute_automation_action(action))
                time.sleep(0.25)
            auto_answer = " ".join(messages)
            self._respond_and_store(text, auto_answer)
            return

        nav_command, nav_query = self.actions.parse_navigation_command(text)
        spotify_fallback_query = self.actions.extract_spotify_play_query(text)
        spotify_query = nav_query if nav_command == "spotify_search" else spotify_fallback_query
        if spotify_query:
            if not self._is_action_family_allowed("automation"):
                self._respond_and_store(text, "La automatización multimedia está bloqueada por permisos, señor.")
                return
            ok, msg = self._play_spotify_query(spotify_query)
            if ok:
                self._respond_and_store(text, f"Reproduciendo {spotify_query} en Spotify, señor.")
                return
            # fallback web si desktop falla
            fallback_nav = self.actions.execute_navigation_command(text)
            if fallback_nav is not None:
                self._respond_and_store(text, fallback_nav.get("message", "Abriendo Spotify web, señor."))
                return
            # fallback extra para comandos sin "en spotify"
            self.actions.open_website(f"https://open.spotify.com/search/{quote_plus(spotify_query)}/tracks")
            self._respond_and_store(
                text,
                f"No pude usar Spotify desktop ({msg}); abrí Spotify web con {spotify_query}, señor.",
            )
            return

        if any(k in normalized_text for k in ["usb", "dispositivos usb", "que hay conectado por usb", "qué hay conectado por usb"]):
            if not self._is_action_family_allowed("system"):
                self._respond_and_store(text, "El acceso a información del sistema está bloqueado por permisos, señor.")
                return
            usb = self.actions.list_usb_devices()
            if usb.get("status") != "ok":
                self._respond_and_store(text, f"No pude listar los USB, señor: {usb.get('message', 'error desconocido')}")
                return
            devices = usb.get("devices", [])
            if not devices:
                self._respond_and_store(text, "No detecté dispositivos USB listables en este momento, señor.")
                return
            items = "\n".join(f"- {d}" for d in devices[:10])
            self._respond_and_store(text, f"Estos son los USB detectados, señor:\n{items}")
            return

        if parsed_reminder is not None:
            if not self._is_action_family_allowed("automation"):
                self._respond_and_store(text, "Los recordatorios están bloqueados por permisos, señor.")
                return
            created = self.reminders.add(parsed_reminder)
            self._persist_reminders()
            answer = (
                f"Recordatorio agendado para {created.get('scheduled_for')}: {created.get('message')}"
            )
            self._respond_and_store(text, answer)
            return

        if any(k in normalized_text for k in ["mis recordatorios", "mostrar recordatorios", "lista de recordatorios"]):
            pending = self.reminders.list_pending()
            if not pending:
                self._respond_and_store(text, "No tiene recordatorios pendientes, señor.")
                return
            lines = [f"#{item['id']} - {item['scheduled_for']} - {item['message']}" for item in pending[:8]]
            self._respond_and_store(text, "Recordatorios pendientes:\n" + "\n".join(lines))
            return

        cancel_match = re.search(r"(?:cancela|cancelar|elimina|borrar)\s+recordatorio\s+(\d+)", normalized_text)
        if cancel_match:
            reminder_id = cancel_match.group(1)
            ok_cancel = self.reminders.cancel(reminder_id)
            if ok_cancel:
                self._persist_reminders()
                self._respond_and_store(text, f"Recordatorio #{reminder_id} cancelado.")
            else:
                self._respond_and_store(text, f"No encontré el recordatorio #{reminder_id}.")
            return

        if any(k in normalized_text for k in ["borra recordatorios", "elimina recordatorios", "cancelar todos los recordatorios"]):
            self.reminders.clear_all()
            self._persist_reminders()
            self._respond_and_store(text, "Todos los recordatorios pendientes fueron eliminados.")
            return

        pending_answer = self._handle_pending_auto_learn_confirmation(text)
        if pending_answer is not None:
            self._respond_and_store(text, pending_answer)
            return

        if any(trigger in normalized_text for trigger in ["olvida todo", "borra tu memoria", "borra memoria"]):
            ok = self.memory.clear_knowledge()
            answer = (
                "He limpiado mi conocimiento aprendido, señor. Empezaré a aprender desde cero."
                if ok
                else "No pude limpiar mi conocimiento aprendido en este momento."
            )
            self._respond_and_store(text, answer)
            return

        learned_skill = self.memory.find_learned_skill(text)
        if learned_skill:
            log.info("[AUTO_LEARN] Reutilizando skill aprendida: %s", learned_skill.get("skill", ""))
            answer = self._execute_learned_skill(learned_skill, text)
            self._respond_and_store(text, answer)
            return

        navigation_result = self.actions.execute_navigation_command(text)
        if navigation_result is not None:
            answer = navigation_result.get("message", "Comando de navegación ejecutado.")
            self._respond_and_store(text, answer)
            return

        parsed = parse_command(text)

        if parsed.intent == "capability_plan":
            if not self._is_action_family_allowed("learning"):
                self._respond_and_store(text, "El planificador de mejoras está bloqueado por permisos, señor.")
                return
            task = (parsed.entity or text).strip()
            if len(task) < 3:
                self._respond_and_store(text, "Indique qué desea planificar, señor (una frase después del disparador).")
                return
            include_web = self._is_action_family_allowed("web")
            plan = self.improvement_planner.build_plan(task, include_web=include_web, web_solver=self.web_solver)
            answer = self.improvement_planner.format_plan_for_user(plan)
            self.memory.register_habit("capability_plan")
            self._respond_and_store(text, answer)
            return

        intent_family_map = {
            "open_app": "system",
            "close_app": "system",
            "volume": "system",
            "brightness": "system",
            "bluetooth": "system",
            "system_info": "system",
            "search_web": "web",
            "arduino_help": "web",
            "remember": "automation",
            "forget": "automation",
            "evolve": "learning",
        }
        family = intent_family_map.get(parsed.intent)
        if family and not self._is_action_family_allowed(family):
            self._respond_and_store(text, f"La familia de acciones '{family}' está bloqueada por permisos, señor.")
            return
        if not self._confirm_sensitive_intent(parsed.intent, text):
            self._respond_and_store(text, "Acción cancelada por seguridad, señor.")
            return
        answer = ""

        # PRIORIDAD: comando "investiga" forzado a búsqueda web en background (sin abrir navegador).
        investigation_topic = self.core.extract_investigation_query(text)
        if investigation_topic:
            if not self._is_action_family_allowed("web"):
                self._respond_and_store(text, "La investigación web está bloqueada por permisos, señor.")
                return
            self._set_status("Investigando en línea...")
            log.info("[RESEARCH] Investigando: %s", investigation_topic)
            self.append_chat("E.D.A.", f"Investigando {investigation_topic}...")
            self.core.open_browser_for_research(investigation_topic, max_pages=2)
            answer = self.core.force_research_answer(investigation_topic)
            self._respond_and_store(text, answer)
            return

        # CRÍTICO: priorizar comandos de abrir apps antes de regex de búsqueda web.
        if parsed.intent == "open_app":
            log.info("[CMD_PARSE] Comando detectado: abrir '%s'", parsed.entity or text)
            compound_answer = self._try_handle_compound_open_command(text, parsed.entity or text)
            if compound_answer:
                answer = compound_answer
            else:
                target = parsed.entity or text
                # Prioridad global: app de escritorio primero.
                result = self.actions.open_app(target)
                if result.get("status") != "ok":
                    result = self._open_web_target(target) or result
                if result.get("status") == "error":
                    # Último fallback: buscar en navegador lo pedido por el usuario.
                    fallback_url = f"https://www.google.com/search?q={quote_plus(target)}&hl=es"
                    fallback_result = self.actions.open_website(fallback_url)
                    if fallback_result.get("status") == "ok":
                        answer = "No identifiqué un programa instalable, así que abrí la búsqueda en navegador, señor."
                    else:
                        answer = self._start_auto_learn(text, intent=parsed.intent)
                else:
                    answer = result["message"]
            self.memory.register_habit("open_app")

        else:
            handled_search, search_answer = self.core.try_open_google_search(text)
            if handled_search:
                answer = search_answer
                self._respond_and_store(text, answer)
                return

        if parsed.intent == "close_app":
            result = self.actions.close_app(parsed.entity or text)
            if result.get("status") == "error":
                answer = self._start_auto_learn(text, intent=parsed.intent)
            else:
                answer = result["message"]

        elif parsed.intent == "optimize":
            answer = self.optimizer.optimize()["message"]
            self.memory.register_habit("optimize")

        elif parsed.intent == "bluetooth":
            devices = self.bt.scan_devices(timeout=5)
            answer = f"Dispositivos detectados: {len(devices)}"
            if devices:
                answer += " | " + ", ".join(d.get("name", "?") for d in devices[:4])

        elif parsed.intent == "remember":
            parts = ((parsed.entity or "").strip()).split(" ", 1)
            if len(parts) == 2:
                key, value = parts
                ok = self.memory.remember(key, value)
                answer = "He guardado ese recuerdo, señor." if ok else "No pude guardar ese recuerdo."
            else:
                answer = "Formato sugerido: recuerda <clave> <valor>."

        elif parsed.intent == "forget":
            key = (parsed.entity or "").strip()
            if key:
                ok = self.memory.forget(key)
                answer = "He olvidado ese dato, señor." if ok else "No pude olvidar ese dato."
            else:
                answer = "Indique qué dato desea olvidar."

        elif parsed.intent == "volume":
            answer = self._handle_volume_command(text)

        elif parsed.intent == "brightness":
            answer = self._handle_brightness_command(text)

        elif parsed.intent == "evolve":
            if config.AUTOEVOLUTION_REQUIRES_PERMISSION:
                confirmed = messagebox.askyesno(
                    "Confirmar autoevolución",
                    "La autoevolución puede modificar múltiples archivos del proyecto.\n"
                    "¿Desea continuar ahora?",
                )
                if not confirmed:
                    answer = "Autoevolución cancelada por seguridad, señor."
                    self._respond_and_store(text, answer)
                    return
            result = self.evolution.autonomous_evolve_project()
            answer = f"{result.get('message')} | Revisados: {result.get('checked')} | Cambiados: {result.get('changed')}"

        elif parsed.intent in ["search_web", "arduino_help"]:
            self.core.open_browser_for_research(text, max_pages=2)
            solved = self.web_solver.solve(text, auto_save_code=True)
            answer = solved.get("answer", "No tengo respuesta por ahora.")
            self.memory.register_habit("web_solver")

        elif parsed.intent == "system_info":
            m = self.system_info.get_metrics()
            answer = f"CPU {m['cpu']} | RAM {m['ram']} | Hora {m['time']} | Ollama {m.get('ollama', 'N/D')}"

        elif parsed.intent != "open_app":
            remember_key = text.replace("?", "").strip().lower()
            recalled = self.memory.recall(remember_key)
            if recalled:
                answer = f"Señor, recuerdo lo siguiente sobre '{remember_key}': {recalled}"
            else:
                if self.core.is_research_like_query(text):
                    if not self._is_action_family_allowed("web"):
                        self._respond_and_store(text, "La investigación web está bloqueada por permisos, señor.")
                        return
                    self._set_status("Investigando en navegador...")
                    self.append_chat("E.D.A.", "Abriendo navegador e investigando fuentes...")
                    self.core.open_browser_for_research(text, max_pages=2)
                    answer = self.core.force_research_answer(text)
                    self._respond_and_store(text, answer)
                    return
                if self._should_force_auto_learn(text, parsed.intent):
                    if not self._is_action_family_allowed("learning"):
                        self._respond_and_store(text, "El autoaprendizaje está bloqueado por permisos, señor.")
                        return
                    intro = (
                        "No tengo un ejecutor directo para esa tarea, señor. "
                        "Activaré autoaprendizaje y buscaré en internet y repositorios cómo hacerlo."
                    )
                    self.append_chat("E.D.A.", intro)
                    answer = self._start_auto_learn(text, intent=parsed.intent)
                    self._respond_and_store(text, answer)
                    return
                mem = self.memory.get_memory()
                history = mem.get("chat_history", []) or mem.get("history", [])
                mm_context = self.multimodal.collect_summary()
                candidate_answer = self.core.ask(text, history=history, extra_context=mm_context)
                if self.core.should_activate_auto_learn(text, candidate_answer):
                    if not self._is_action_family_allowed("learning"):
                        answer = "Detecté necesidad de autoaprendizaje, pero esa capacidad está bloqueada por permisos, señor."
                    else:
                        answer = self._start_auto_learn(text, intent=parsed.intent)
                else:
                    answer = candidate_answer

        self._respond_and_store(text, answer)

    def _animate_mic(self) -> None:
        if not self._mic_pulse_active:
            return
        self._mic_pulse_step += 1
        colors = ["#661111", "#882222", "#aa2222", "#cc2222", "#aa2222", "#882222"]
        self.mic_button.configure(bg=colors[self._mic_pulse_step % len(colors)])
        self.root.after(180, self._animate_mic)

    def toggle_microphone(self) -> None:
        if self.voice.listening:
            self.voice.stop_listening()
            self._mic_pulse_active = False
            self.mic_button.configure(bg="#2f2f2f")
            self._set_status("Micrófono desactivado")
            return

        ok = self.voice.start_listening(self._voice_callback)
        if ok:
            self._mic_pulse_active = True
            self._animate_mic()
            self._set_status("Escucha activa")
        else:
            self._set_status("Micrófono no disponible")
            messagebox.showwarning("Micrófono", "No se pudo activar el reconocimiento de voz.")

    def _voice_callback(self, text: str) -> None:
        self.append_chat("🎤 Voz", text)
        threading.Thread(target=self._process_user_message_safe, args=(text,), daemon=True).start()

    def confirm_critical(self, message: str) -> bool:
        return messagebox.askyesno("Confirmación requerida", message)

    def action_optimize(self) -> None:
        def run_optimization() -> None:
            self._set_status("Ejecutando optimización...")
            result = self.optimizer.optimize()
            self.append_chat_animated("E.D.A.", result.get("message", "Optimización completada."))
            self._set_status("En espera")

            panel = tk.Toplevel(self.root)
            panel.title("Panel de Optimización")
            panel.configure(bg=config.THEME_PANEL)
            panel.geometry("520x260")
            tk.Label(panel, text="Reporte de optimización", bg=config.THEME_PANEL, fg=config.THEME_TEXT, font=("Consolas", 12, "bold")).pack(
                pady=(12, 8)
            )
            tk.Label(panel, text=result.get("message", "Sin datos"), bg=config.THEME_PANEL, fg="white", justify="left", wraplength=480).pack(
                padx=16, pady=8
            )

        threading.Thread(target=run_optimization, daemon=True).start()

    def action_bluetooth(self) -> None:
        def run_scan() -> None:
            self._set_status("Escaneando Bluetooth...")
            devices = self.bt.scan_devices(timeout=5)
            summary = self.bt.get_status_summary()
            self.append_chat("E.D.A.", summary)
            if devices:
                lines = [f"{d.get('name', 'Desconocido')} ({d.get('address', '?')})" for d in devices[:10]]
                self.append_chat("E.D.A.", "Bluetooth detectado:\n" + "\n".join(lines))
            else:
                self.append_chat("E.D.A.", "No se detectaron dispositivos Bluetooth o el módulo no está disponible.")
            self._set_status("En espera")

            panel = tk.Toplevel(self.root)
            panel.title("Panel Bluetooth")
            panel.configure(bg=config.THEME_PANEL)
            panel.geometry("620x340")
            tk.Label(panel, text="Dispositivos detectados", bg=config.THEME_PANEL, fg=config.THEME_TEXT, font=("Consolas", 12, "bold")).pack(
                pady=(10, 6)
            )
            listbox = tk.Listbox(panel, bg="#0f1630", fg="#d9f7ff", font=("Consolas", 11), width=72, height=10)
            listbox.pack(padx=12, pady=6, fill="both", expand=True)
            for d in devices:
                listbox.insert("end", f"{d.get('name', 'Desconocido')} | {d.get('address', '?')} | RSSI {d.get('rssi', 'N/D')}")

        threading.Thread(target=run_scan, daemon=True).start()

    def action_evolution(self) -> None:
        if config.AUTOEVOLUTION_REQUIRES_PERMISSION:
            confirmed = messagebox.askyesno(
                "Confirmar autoevolución",
                "La autoevolución puede modificar múltiples archivos del proyecto.\n"
                "¿Desea continuar ahora?",
            )
            if not confirmed:
                self.append_chat_animated("E.D.A.", "Autoevolución cancelada por seguridad, señor.")
                self._set_status("En espera")
                return

        def run_evolution() -> None:
            self._set_status("Ejecutando autoevolución segura...")
            result = self.evolution.autonomous_evolve_project()
            msg = (
                f"{result.get('message')} | Revisados: {result.get('checked')} | "
                f"Modificados: {result.get('changed')}\n"
                "Se realizaron backups automáticos antes de cada cambio."
            )
            self.append_chat_animated("E.D.A.", msg)
            self._set_status("En espera")

        threading.Thread(target=run_evolution, daemon=True).start()

    def action_usage_guide(self) -> None:
        """Ventana con la guía de frases y ejemplos (docs/EJEMPLOS_CAPACIDADES_EDA.txt)."""
        path = config.BASE_DIR / "docs" / "EJEMPLOS_CAPACIDADES_EDA.txt"
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            body = (
                "(No se encontró docs/EJEMPLOS_CAPACIDADES_EDA.txt en el proyecto.)\n\n"
                "«aprende a …» investiga y puede proponer código (confirmación SÍ/NO).\n"
                "«Quiero que …» enseña reglas de automatización seguras.\n"
                "«¿Cómo implementarías …?» o «Planea cómo cumplir …» arma un plan sin modificar archivos.\n"
            )

        win = tk.Toplevel(self.root)
        win.title("E.D.A. — Guía de uso y ejemplos")
        win.configure(bg=config.THEME_PANEL)
        win.geometry("760x580")
        outer = tk.Frame(win, bg=config.THEME_PANEL)
        outer.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(
            outer,
            text="Frases de ejemplo y capacidades (también en docs/EJEMPLOS_CAPACIDADES_EDA.txt)",
            bg=config.THEME_PANEL,
            fg=config.THEME_TEXT,
            font=("Consolas", 11, "bold"),
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        box = scrolledtext.ScrolledText(
            outer,
            wrap="word",
            font=("Consolas", 10),
            bg="#070b19",
            fg="#e3f8ff",
            insertbackground=config.THEME_TEXT,
            relief="flat",
            height=28,
        )
        box.pack(fill="both", expand=True)
        box.insert("1.0", body)
        box.config(state="disabled")

        btn_row = tk.Frame(outer, bg=config.THEME_PANEL)
        btn_row.pack(fill="x", pady=(10, 0))
        tk.Button(
            btn_row,
            text="Cerrar",
            command=win.destroy,
            bg="#1b274f",
            fg="white",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
        ).pack(side="right")

    def action_config(self) -> None:
        mem = self.memory.get_memory()
        prefs = mem.get("preferences", {})
        perms = prefs.get("action_permissions", {})
        proactive = prefs.get("proactive_insights_enabled", True)
        fs = prefs.get("ui_chat_font_size", config.UI_CHAT_FONT_DEFAULT)
        rstat = remote_llm.health_status()
        rmode = remote_llm.remote_llm_mode()
        summary = (
            f"Modelo: {prefs.get('model', config.OLLAMA_MODEL)} | Voz: siempre activa | "
            f"Permisos: system={perms.get('system', True)} web={perms.get('web', True)} "
            f"automation={perms.get('automation', True)} learning={perms.get('learning', True)} | "
            f"Sugerencias proactivas: {proactive} | Fuente chat: {fs}px | "
            f"LLM remoto: {rstat} (modo {rmode}) | "
            f"Confirmaciones críticas: {config.REQUIRE_CONFIRMATION_CRITICAL} | "
            f"Permisos GUI: {config.ASK_PERMISSION_FOR_SENSITIVE_ACTIONS}"
        )
        self.append_chat("E.D.A.", summary)

    def _refresh_ui_font_from_memory(self) -> None:
        mem = self.memory.get_memory()
        prefs = mem.get("preferences", {})
        try:
            size = int(prefs.get("ui_chat_font_size", config.UI_CHAT_FONT_DEFAULT))
        except (TypeError, ValueError):
            size = int(config.UI_CHAT_FONT_DEFAULT)
        size = max(int(config.UI_CHAT_FONT_MIN), min(int(config.UI_CHAT_FONT_MAX), size))
        font = ("Consolas", size)
        self.chat_box.configure(font=font)
        self.entry.configure(font=font)
        self.chat_box.tag_configure("sender_user", foreground="#7bdfff", font=("Consolas", size, "bold"))
        self.chat_box.tag_configure("sender_assistant", foreground="#00ffaa", font=("Consolas", size, "bold"))
        self.chat_box.tag_configure("msg_body", foreground="#e3f8ff", font=font)

    def action_clear_behavior_patterns(self) -> None:
        confirmed = messagebox.askyesno(
            "Olvidar patrones",
            "Se borrarán los patrones de uso guardados y el temporizador de sugerencias proactivas.\n"
            "No afecta el chat, comandos aprendidos ni la memoria larga.\n\n¿Continuar?",
        )
        if not confirmed:
            return
        ok = self.memory.clear_behavior_events()
        self.append_chat(
            "E.D.A.",
            "Patrones de uso olvidados, señor." if ok else "No pude borrar los patrones en este momento, señor.",
        )

    def _get_action_permissions(self) -> dict:
        prefs = self.memory.get_memory().get("preferences", {})
        perms = prefs.get("action_permissions", {})
        if not isinstance(perms, dict):
            perms = {}
        perms.setdefault("system", True)
        perms.setdefault("web", True)
        perms.setdefault("automation", True)
        perms.setdefault("learning", True)
        return perms

    def _is_action_family_allowed(self, family: str) -> bool:
        perms = self._get_action_permissions()
        return bool(perms.get(family, True))

    def action_permissions_panel(self) -> None:
        perms = self._get_action_permissions()
        mem = self.memory.get_memory()
        prefs = mem.get("preferences", {})
        panel = tk.Toplevel(self.root)
        panel.title("Permisos y apariencia")
        panel.configure(bg=config.THEME_PANEL)
        panel.geometry("440x400")

        tk.Label(
            panel,
            text="Control de permisos",
            bg=config.THEME_PANEL,
            fg=config.THEME_TEXT,
            font=("Consolas", 12, "bold"),
        ).pack(pady=(12, 10))

        vars_map = {
            "system": tk.BooleanVar(value=bool(perms.get("system", True))),
            "web": tk.BooleanVar(value=bool(perms.get("web", True))),
            "automation": tk.BooleanVar(value=bool(perms.get("automation", True))),
            "learning": tk.BooleanVar(value=bool(perms.get("learning", True))),
        }

        for key, var in vars_map.items():
            tk.Checkbutton(
                panel,
                text=f"Permitir {key}",
                variable=var,
                bg=config.THEME_PANEL,
                fg="white",
                selectcolor="#1b274f",
                activebackground=config.THEME_PANEL,
            ).pack(anchor="w", padx=20, pady=6)

        proactive_var = tk.BooleanVar(value=bool(prefs.get("proactive_insights_enabled", True)))
        tk.Checkbutton(
            panel,
            text="Sugerencias proactivas (patrones de uso)",
            variable=proactive_var,
            bg=config.THEME_PANEL,
            fg="white",
            selectcolor="#1b274f",
            activebackground=config.THEME_PANEL,
        ).pack(anchor="w", padx=20, pady=(10, 4))

        font_row = tk.Frame(panel, bg=config.THEME_PANEL)
        font_row.pack(fill="x", padx=20, pady=8)
        tk.Label(font_row, text="Tamaño fuente chat:", bg=config.THEME_PANEL, fg="white").pack(side="left")
        try:
            fs_init = int(prefs.get("ui_chat_font_size", config.UI_CHAT_FONT_DEFAULT))
        except (TypeError, ValueError):
            fs_init = int(config.UI_CHAT_FONT_DEFAULT)
        fs_init = max(int(config.UI_CHAT_FONT_MIN), min(int(config.UI_CHAT_FONT_MAX), fs_init))
        font_spin = tk.Spinbox(
            font_row,
            from_=config.UI_CHAT_FONT_MIN,
            to=config.UI_CHAT_FONT_MAX,
            width=4,
            bg="#0f1630",
            fg=config.THEME_TEXT,
            insertbackground=config.THEME_TEXT,
        )
        font_spin.delete(0, "end")
        font_spin.insert(0, str(fs_init))
        font_spin.pack(side="left", padx=(8, 0))

        def save_permissions() -> None:
            mem2 = self.memory.get_memory()
            prefs2 = mem2.get("preferences", {})
            prefs2["action_permissions"] = {k: bool(v.get()) for k, v in vars_map.items()}
            prefs2["proactive_insights_enabled"] = bool(proactive_var.get())
            try:
                fs = int(font_spin.get())
            except (TypeError, ValueError):
                fs = int(config.UI_CHAT_FONT_DEFAULT)
            prefs2["ui_chat_font_size"] = max(
                int(config.UI_CHAT_FONT_MIN), min(int(config.UI_CHAT_FONT_MAX), fs)
            )
            mem2["preferences"] = prefs2
            self.memory.save_memory(mem2)
            self._refresh_ui_font_from_memory()
            panel.destroy()
            self.append_chat("E.D.A.", "Permisos y apariencia actualizados correctamente, señor.")

        tk.Button(
            panel,
            text="Guardar",
            command=save_permissions,
            bg="#1b274f",
            fg="white",
            relief="flat",
            padx=12,
            pady=6,
        ).pack(pady=12)

    def action_toggle_voice(self) -> None:
        # Requisito del usuario: hablar siempre en voz alta.
        mem = self.memory.get_memory()
        prefs = mem.get("preferences", {})
        prefs["voice_enabled"] = True
        mem["preferences"] = prefs
        self.memory.save_memory(mem)
        self.append_chat_animated("E.D.A.", "Modo voz permanente activo, señor.")

    def action_clear_chat(self) -> None:
        confirmed = messagebox.askyesno(
            "Limpiar chat",
            "¿Desea limpiar el historial visual del chat?\n\n"
            "(Atajo de teclado: Ctrl+Mayús+L — evita conflicto con Spotify, que usa Ctrl+L en búsqueda.)",
        )
        if not confirmed:
            return
        self.chat_box.config(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.config(state="disabled")
        self.append_chat("E.D.A.", "Chat visual limpiado. La memoria persistente se conserva.")

    def action_clear_memory(self) -> None:
        confirmed = messagebox.askyesno(
            "Borrar memoria",
            "Esto borrará historial, recuerdos, hábitos y aprendizaje de E.D.A.\n"
            "¿Desea continuar?",
        )
        if not confirmed:
            return

        ok = self.memory.clear_all_memory()
        if not ok:
            self.append_chat_animated("E.D.A.", "No pude borrar la memoria en este momento, señor.")
            return

        # Al limpiar memoria completa, también cancelamos cualquier auto-learn pendiente.
        self.pending_auto_learn = {}
        self.reminders.clear_all()
        self._persist_reminders()
        self.append_chat_animated(
            "E.D.A.",
            "Memoria borrada correctamente. Mantengo su perfil y configuración base.",
        )

    def action_export_chat(self) -> None:
        try:
            self.chat_box.config(state="normal")
            content = self.chat_box.get("1.0", "end").strip()
            self.chat_box.config(state="disabled")
            if not content:
                self.append_chat("E.D.A.", "No hay contenido de chat para exportar.")
                return
            exports_dir = config.BASE_DIR / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            filename = f"chat_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            out_path = exports_dir / filename
            out_path.write_text(content, encoding="utf-8")
            self.append_chat("E.D.A.", f"Chat exportado en: {out_path}")
        except Exception as exc:
            log.error("Error exportando chat: %s", exc)
            self.append_chat("E.D.A.", "No pude exportar el chat en este momento.")

    def _refresh_metrics(self) -> None:
        metrics = self.system_info.get_metrics()
        self.cpu_text.set(f"CPU_LOAD: {metrics.get('cpu', '--')}")
        self.ram_text.set(f"MEM_USAGE: {metrics.get('ram', '--')}")
        self.time_text.set(f"HORA: {metrics.get('time', '--')}")
        self.bt_text.set(f"BLUETOOTH: {metrics.get('bluetooth', '--')}")
        self.ollama_text.set(f"OLLAMA: {metrics.get('ollama', '--')}")
        permission_mode = "estricto" if config.ASK_PERMISSION_FOR_SENSITIVE_ACTIONS else "relajado"
        self.security_text.set(f"SEGURIDAD: {permission_mode}")

        if metrics.get("ollama") == "Activo":
            self.ollama_indicator.configure(fg="#19d36b")
        else:
            self.ollama_indicator.configure(fg=config.THEME_WARNING)

        self.root.after(1000, self._refresh_metrics)

    def _schedule_proactive_loop(self) -> None:
        delay = int(getattr(config, "PROACTIVE_GUI_TICK_MS", 180000))
        self.root.after(delay, self._proactive_tick)

    def _proactive_tick(self) -> None:
        try:
            if not getattr(config, "PROACTIVE_INSIGHTS_ENABLED", True):
                self._schedule_proactive_loop()
                return
            if not self.memory.should_emit_proactive_suggestion():
                self._schedule_proactive_loop()
                return
            msg = self.memory.build_proactive_suggestion_text()
            if msg:
                self.memory.mark_proactive_suggestion_sent(msg)
                self.append_chat("E.D.A.", f"💡 {msg}")
        except Exception as exc:
            log.warning("[PROACTIVE] %s", exc)
        self._schedule_proactive_loop()

    def _start_background_loops(self) -> None:
        self._refresh_metrics()
        self._schedule_proactive_loop()

    def run(self) -> None:
        self.root.mainloop()

    def _on_reminder_due(self, payload: dict) -> None:
        """Dispara notificación visual+voz para recordatorios agendados."""
        reminder_text = str(payload.get("message", "tienes un recordatorio pendiente.")).strip()
        scheduled_for = str(payload.get("scheduled_for", "")).strip()
        spoken = f"Recordatorio: {reminder_text}"
        chat_msg = f"⏰ Recordatorio ({scheduled_for}): {reminder_text}" if scheduled_for else f"⏰ Recordatorio: {reminder_text}"

        def notify() -> None:
            self.append_chat("E.D.A.", chat_msg)
            messagebox.showinfo("Recordatorio E.D.A.", reminder_text)
            self.voice.speak(spoken)
            self._persist_reminders()

        self.root.after(0, notify)

    def _handle_volume_command(self, text: str) -> str:
        """Soporta: volumen 40, sube/baja volumen, mutea/desmutea."""
        normalized = (text or "").strip().lower()

        if any(word in normalized for word in ["mutea", "mutear", "silencia", "silenciar"]):
            result = self.actions.set_mute(True)
            return result.get("message", "No pude silenciar el audio.") if result.get("status") == "ok" else self._start_auto_learn(text, intent="volume")

        if any(word in normalized for word in ["desmutea", "desmutear", "quita el mute", "activar sonido", "reactivar sonido"]):
            result = self.actions.set_mute(False)
            return result.get("message", "No pude reactivar el audio.") if result.get("status") == "ok" else self._start_auto_learn(text, intent="volume")

        number_match = re.search(r"(\d{1,3})", normalized)
        if number_match:
            target = int(number_match.group(1))
            result = self.actions.set_volume(target)
            return result.get("message", "Volumen ajustado") if result.get("status") == "ok" else self._start_auto_learn(text, intent="volume")

        if "sube" in normalized or "subir" in normalized:
            delta = 10
            delta_match = re.search(r"(\d{1,2})", normalized)
            if delta_match:
                delta = int(delta_match.group(1))
            result = self.actions.adjust_volume(delta)
            if result.get("status") == "ok":
                return f"Volumen aumentado {delta}%."
            return self._start_auto_learn(text, intent="volume")

        if "baja" in normalized or "bajar" in normalized:
            delta = 10
            delta_match = re.search(r"(\d{1,2})", normalized)
            if delta_match:
                delta = int(delta_match.group(1))
            result = self.actions.adjust_volume(-delta)
            if result.get("status") == "ok":
                return f"Volumen reducido {delta}%."
            return self._start_auto_learn(text, intent="volume")

        result = self.actions.set_volume(50)
        return result.get("message", "Volumen ajustado a 50%.") if result.get("status") == "ok" else self._start_auto_learn(text, intent="volume")

    def _handle_brightness_command(self, text: str) -> str:
        """Soporta: brillo 70, sube/baja brillo."""
        normalized = (text or "").strip().lower()
        number_match = re.search(r"(\d{1,3})", normalized)
        if number_match:
            target = int(number_match.group(1))
            result = self.actions.set_brightness(target)
            return result.get("message", "Brillo ajustado") if result.get("status") == "ok" else self._start_auto_learn(text, intent="brightness")

        if "sube" in normalized or "subir" in normalized:
            delta = 10
            delta_match = re.search(r"(\d{1,2})", normalized)
            if delta_match:
                delta = int(delta_match.group(1))
            result = self.actions.adjust_brightness(delta)
            if result.get("status") == "ok":
                return f"Brillo aumentado {delta}%."
            return self._start_auto_learn(text, intent="brightness")

        if "baja" in normalized or "bajar" in normalized:
            delta = 10
            delta_match = re.search(r"(\d{1,2})", normalized)
            if delta_match:
                delta = int(delta_match.group(1))
            result = self.actions.adjust_brightness(-delta)
            if result.get("status") == "ok":
                return f"Brillo reducido {delta}%."
            return self._start_auto_learn(text, intent="brightness")

        result = self.actions.set_brightness(70)
        return result.get("message", "Brillo ajustado a 70%.") if result.get("status") == "ok" else self._start_auto_learn(text, intent="brightness")
