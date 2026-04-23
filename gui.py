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

import config
from actions import ActionController
from bluetooth_manager import BluetoothManager
from core import EDACore
from evolution import EvolutionEngine
from logger import get_logger
from memory import MemoryManager
from mouse_keyboard import MouseKeyboardController
from nlp_utils import detect_confirmation, detect_secondary_action, parse_command, split_compound_command
from obs_controller import OBSController
from optimizer import Optimizer
from scheduler import ReminderScheduler, parse_reminder_request
from system_info import SystemInfo
from voice import VoiceEngine
from web_solver import WebSolver

log = get_logger("gui")


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
        self.evolution = EvolutionEngine(Path(__file__).resolve().parent)
        self.web_solver = WebSolver(self.core, self.memory)
        self.obs = OBSController()
        self.actions = ActionController(confirm_callback=self.confirm_critical)
        self.mouse_keyboard = MouseKeyboardController()
        self.reminders = ReminderScheduler(on_due=self._on_reminder_due)
        self.reminders.start()
        self.pending_auto_learn: dict = {}

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
        self._start_background_loops()
        self._restore_persisted_reminders()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.append_chat_animated("E.D.A.", "Protocolos de inicialización completados. Todos los servicios están en espera.")
        self.append_chat_animated("E.D.A.", "¿Cuáles son sus órdenes, señor?")
        self._set_status("En espera")

    def _on_close(self) -> None:
        self.reminders.stop()
        self.root.destroy()

    def _persist_reminders(self) -> None:
        self.memory.save_reminders(self.reminders.list_pending())

    def _restore_persisted_reminders(self) -> None:
        restored_count = 0
        for item in self.memory.get_reminders():
            if isinstance(item, dict) and self.reminders.add_existing(item):
                restored_count += 1
        if restored_count:
            self.append_chat("E.D.A.", f"Recordatorios restaurados: {restored_count}")
            self._persist_reminders()

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
        self.root.bind("<Control-l>", lambda _e: self.action_clear_chat())
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

        self._side_button(right, "Configuración", self.action_config)
        self._side_button(right, "Voz siempre ON", self.action_toggle_voice)
        self._side_button(right, "Limpiar chat", self.action_clear_chat)
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
            return "Abrí la aplicación, pero no detecté una acción secundaria ejecutable."

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
                # Flujo más confiable para Spotify desktop: foco de búsqueda y reproducir primer resultado.
                self.actions.activate_app_window("spotify")
                time.sleep(0.5)
                self.mouse_keyboard.hotkey("ctrl", "l")
                time.sleep(0.3)
                typed = self.mouse_keyboard.type_text(payload)
                if typed.get("status") == "ok":
                    self.mouse_keyboard.hotkey("enter")
                    time.sleep(1.0)
                    self.mouse_keyboard.hotkey("enter")
                    return f"Abriendo Spotify y reproduciendo: {payload}."
                return f"Abrí Spotify, pero no pude escribir la búsqueda: {typed.get('message', 'error desconocido')}"
            typed = self.mouse_keyboard.type_text(payload)
            if typed.get("status") == "ok":
                self.mouse_keyboard.hotkey("enter")
                return f"Abriendo {opened_app} y buscando: {payload}."
            return f"Abrí {opened_app}, pero no pude escribir la búsqueda: {typed.get('message', 'error desconocido')}"

        return "Abrí la aplicación, pero no supe completar la acción secundaria."

    @staticmethod
    def _normalize_trigger_text(text: str) -> str:
        cleaned = re.sub(r"[¿?¡!.,;:\"'()\[\]]", " ", (text or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _try_learn_automation_rule(self, user_text: str) -> str | None:
        """
        Aprende reglas tipo:
        - "quiero que <acción> cada vez que te diga <gatillo>"
        - "cuando te diga <gatillo> haz <acción>"
        """
        text = (user_text or "").strip()
        normalized = self._normalize_trigger_text(text)

        m1 = re.search(r"quiero que\s+(.+?)\s+cada vez que te diga\s+(.+)$", normalized)
        if m1:
            action = m1.group(1).strip()
            trigger = m1.group(2).strip()
            if action and trigger:
                self.memory.learn_command(trigger, action)
                return f"He aprendido la automatización. Cuando diga '{trigger}', ejecutaré: {action}."

        m2 = re.search(r"cuando te diga\s+(.+?)\s+(?:haz|hace|quiero que)\s+(.+)$", normalized)
        if m2:
            trigger = m2.group(1).strip()
            action = m2.group(2).strip()
            if action and trigger:
                self.memory.learn_command(trigger, action)
                return f"Automatización guardada. Trigger: '{trigger}' -> Acción: {action}."

        return None

    def _execute_automation_action(self, action_text: str) -> str:
        """
        Ejecuta acciones aprendidas por trigger.
        Incluye caso especial: OBS + escena nombrada.
        """
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

        # Fallback: intentar como comando compuesto ya existente.
        compound = self._try_handle_compound_open_command(action, action)
        if compound:
            return compound

        return "Automatización aprendida, pero esta acción aún no tiene ejecutor específico."

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
        if self._should_prefer_desktop_app(first_target):
            open_result = self.actions.open_app(first_target)
            if open_result.get("status") != "ok":
                open_result = self._open_web_target(first_target) or open_result
        else:
            open_result = self._open_web_target(first_target)
            if open_result is None:
                open_result = self.actions.open_app(first_target)
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

        module_path = Path(__file__).resolve().parent / module_name
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

            skill_name = payload.get("skill_name", payload.get("function", "habilidad"))
            self.memory.save_learned_skill(
                skill_name=str(skill_name),
                trigger=str(payload.get("trigger", "")).strip(),
                module=str(payload.get("module", "")).strip(),
                function_name=str(payload.get("function", "")).strip(),
            )

            log.info("[EVOLUTION] Skill aplicada: %s", skill_name)
            execute_now = self.web_solver.execute_generated_function(
                Path(__file__).resolve().parent / str(payload.get("module", "")),
                str(payload.get("function", "")),
                str(payload.get("original_user_text", "")),
            )
            execution_msg = execute_now.get("message", "") if isinstance(execute_now, dict) else ""
            if execute_now.get("status") == "ok":
                return (
                    f"✓ He mejorado mi código. Ahora puedo {payload.get('task', 'hacer esta acción')}. "
                    f"Ejecutando ahora: {execution_msg}"
                )
            return (
                f"✓ He mejorado mi código. Ahora puedo {payload.get('task', 'hacer esta acción')}, "
                f"pero la ejecución inmediata falló: {execution_msg}"
            )

        return "Tengo una mejora pendiente. Responde: SÍ, NO o VER CÓDIGO."

    def _start_auto_learn(self, user_text: str, intent: str = "") -> str:
        task = (user_text or "").strip()
        self.append_chat("E.D.A.", self.core.auto_learn_intro(task))
        self._set_status("AUTO_LEARN investigando...")
        log.info("[AUTO_LEARN] Activado para: %s", task)

        generated = self.web_solver.generate_autolearn_payload(task, intent=intent)
        if generated.get("status") != "ok":
            self._set_status("En espera")
            return f"Intenté auto-aprender, pero no logré generar código seguro: {generated.get('message', 'error desconocido')}"

        self.pending_auto_learn = {
            "task": generated.get("task", task),
            "module": generated.get("module", "skills_auto.py"),
            "function": generated.get("function", ""),
            "code": generated.get("code", ""),
            "trigger": task,
            "skill_name": generated.get("function", ""),
            "original_user_text": user_text,
        }
        libs = generated.get("libraries", [])
        libs_txt = ", ".join(libs) if libs else "(sin librerías externas)"
        self._set_status("Esperando confirmación")
        return (
            f"He aprendido cómo {task}. He generado código Python para implementarlo en {generated.get('module')}. "
            f"Librerías detectadas: {libs_txt}.\n"
            "¿Puedo mejorar mi código para agregar esta funcionalidad? [SÍ] [NO] [VER CÓDIGO]"
        )

    def _respond_and_store(self, user_text: str, answer: str) -> None:
        """Respuesta estándar: persistencia, chat, voz y estado."""
        final_answer = self._ensure_jarvis_treatment(answer)
        self.memory.add_history(user_text, final_answer)
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

        learn_auto_answer = self._try_learn_automation_rule(text)
        if learn_auto_answer:
            self._respond_and_store(text, learn_auto_answer)
            return

        learned_action = self.memory.get_learned_action(self._normalize_trigger_text(text))
        if learned_action:
            auto_answer = self._execute_automation_action(learned_action)
            self._respond_and_store(text, auto_answer)
            return

        nav_command, nav_query = self.actions.parse_navigation_command(text)
        spotify_fallback_query = self.actions.extract_spotify_play_query(text)
        spotify_query = nav_query if nav_command == "spotify_search" else spotify_fallback_query
        if spotify_query:
            opened = self.actions.open_app("spotify")
            if opened.get("status") == "ok":
                self.actions.activate_app_window("spotify")
                time.sleep(0.6)
                self.mouse_keyboard.hotkey("ctrl", "l")
                time.sleep(0.3)
                typed = self.mouse_keyboard.type_text(spotify_query)
                if typed.get("status") == "ok":
                    self.mouse_keyboard.hotkey("enter")
                    time.sleep(1.0)
                    self.mouse_keyboard.hotkey("enter")
                    self._respond_and_store(text, f"Reproduciendo {spotify_query} en Spotify, señor.")
                    return
            # fallback web si desktop falla
            fallback_nav = self.actions.execute_navigation_command(text)
            if fallback_nav is not None:
                self._respond_and_store(text, fallback_nav.get("message", "Abriendo Spotify web, señor."))
                return
            # fallback extra para comandos sin "en spotify"
            self.actions.open_website(f"https://open.spotify.com/search/{quote_plus(spotify_query)}/tracks")
            self._respond_and_store(text, f"No pude usar Spotify desktop; abrí Spotify web con {spotify_query}, señor.")
            return

        if any(k in normalized_text for k in ["usb", "dispositivos usb", "que hay conectado por usb", "qué hay conectado por usb"]):
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

        reminder_req = parse_reminder_request(text)
        if reminder_req is not None:
            created = self.reminders.add(reminder_req)
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
        if not self._confirm_sensitive_intent(parsed.intent, text):
            self._respond_and_store(text, "Acción cancelada por seguridad, señor.")
            return
        answer = ""

        # PRIORIDAD: comando "investiga" forzado a búsqueda web en background (sin abrir navegador).
        investigation_topic = self.core.extract_investigation_query(text)
        if investigation_topic:
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
                if self._should_prefer_desktop_app(target):
                    result = self.actions.open_app(target)
                    if result.get("status") != "ok":
                        result = self._open_web_target(target) or result
                else:
                    web_result = self._open_web_target(target)
                    result = web_result if web_result is not None else self.actions.open_app(target)
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
            parts = (parsed.entity or "").split(" ", 1)
            if len(parts) == 2:
                key, value = parts
                ok = self.memory.remember(key, value)
                answer = "He guardado ese recuerdo, señor." if ok else "No pude guardar ese recuerdo."
            else:
                answer = "Formato sugerido: recuerda <clave> <valor>."

        elif parsed.intent == "forget":
            key = parsed.entity.strip()
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
                    self._set_status("Investigando en navegador...")
                    self.append_chat("E.D.A.", "Abriendo navegador e investigando fuentes...")
                    self.core.open_browser_for_research(text, max_pages=2)
                    answer = self.core.force_research_answer(text)
                    self._respond_and_store(text, answer)
                    return
                mem = self.memory.get_memory()
                history = mem.get("chat_history", []) or mem.get("history", [])
                candidate_answer = self.core.ask(text, history=history)
                if self.core.should_activate_auto_learn(text, candidate_answer):
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

    def action_config(self) -> None:
        mem = self.memory.get_memory()
        prefs = mem.get("preferences", {})
        summary = (
            f"Modelo: {prefs.get('model', config.OLLAMA_MODEL)} | Voz: siempre activa | "
            f"Confirmaciones críticas: {config.REQUIRE_CONFIRMATION_CRITICAL} | "
            f"Permisos GUI: {config.ASK_PERMISSION_FOR_SENSITIVE_ACTIONS}"
        )
        self.append_chat("E.D.A.", summary)

    def action_toggle_voice(self) -> None:
        # Requisito del usuario: hablar siempre en voz alta.
        mem = self.memory.get_memory()
        prefs = mem.get("preferences", {})
        prefs["voice_enabled"] = True
        mem["preferences"] = prefs
        self.memory.save_memory(mem)
        self.append_chat_animated("E.D.A.", "Modo voz permanente activo, señor.")

    def action_clear_chat(self) -> None:
        confirmed = messagebox.askyesno("Limpiar chat", "¿Desea limpiar el historial visual del chat?")
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
            exports_dir = Path(__file__).resolve().parent / "exports"
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

    def _start_background_loops(self) -> None:
        self._refresh_metrics()

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
