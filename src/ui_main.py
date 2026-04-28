"""UI principal ligera para E.D.A. (Deep Obsidian, low-RAM).

Soporta CustomTkinter cuando está disponible y cae a Tkinter estándar si no.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import psutil

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda.action_agent import ActionAgent
from eda.actions import ActionController
from eda.core import EDACore
from eda.memory import MemoryManager
from eda.mouse_keyboard import MouseKeyboardController
from eda.orchestrator import CommandOrchestrator
from eda.stt import STTManager
from eda.system_info import SystemInfo
from eda.system_observer import SystemObserver
from eda.task_membership import TaskMembershipStore
from eda.web_solver import WebSolver

try:
    import customtkinter as ctk  # type: ignore
except Exception:
    ctk = None  # type: ignore

import tkinter as tk
from tkinter import messagebox, ttk

BG = "#050505"
PANEL = "#0d0d0d"
BORDER = "#1a1a1a"
ACCENT = "#00f2ff"
HEALTH = "#39ff14"
TEXT = "#d9d9d9"
MUTED = "#8a8a8a"
ASSIST_BUBBLE = "#06222a"
USER_BUBBLE = "#1a1a1a"

DEFAULT_METRICS_INTERVAL_MS = int(os.getenv("EDA_UI_METRICS_MS", "2000"))

AUDIT_PATH = ROOT / "logs" / "operate_secure_audit.jsonl"
TRUST_PATH = ROOT / "config" / "ui_action_trust.json"


def _headless_default() -> bool:
    return bool(os.getenv("EDA_UI_HEADLESS")) or os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"


def _obfuscate_secret(value: str) -> str:
    clean = (value or "").strip()
    if len(clean) <= 4:
        return "***"
    return f"{clean[:2]}****{clean[-2:]}"


def append_ui_audit(payload: dict[str, Any]) -> None:
    """Auditoría compartida con operate_secure (mismo archivo JSONL)."""
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = dict(payload)
    row.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    row.setdefault("step", "ui_action_approval")
    if "telegram_token" in row:
        row["telegram_token"] = _obfuscate_secret(str(row["telegram_token"]))
    if "telegram_chat" in row:
        row["telegram_chat"] = _obfuscate_secret(str(row["telegram_chat"]))
    with AUDIT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_trusted_hashes() -> set[str]:
    data = {}
    try:
        if TRUST_PATH.exists():
            data = json.loads(TRUST_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    hashes = data.get("trusted_hashes")
    return set(hashes) if isinstance(hashes, list) else set()


def save_trusted_hash(text_hash: str) -> None:
    TRUST_PATH.parent.mkdir(parents=True, exist_ok=True)
    trusted = load_trusted_hashes()
    trusted.add(text_hash)
    TRUST_PATH.write_text(json.dumps({"trusted_hashes": sorted(trusted)}, indent=2), encoding="utf-8")


def hash_command(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def classify_action_risk(text: str) -> tuple[str, str]:
    """Retorna (nivel, resumen corto)."""
    low = (text or "").strip().lower()
    if re.search(r"^\s*(?:ejecuta|corre)\s+comando\s*:", low):
        cmd = low.split(":", 1)[1].strip() if ":" in low else ""
        return "high", f"Ejecución de terminal: {cmd[:120]}"
    if "mueve archivo" in low:
        return "high", "Movimiento de archivos entre rutas."
    if any(k in low for k in ("borra", "elimina", "rm ", "del ")):
        return "high", "Operación potencialmente destructiva."
    if low.startswith("aprende tarea"):
        return "medium", "Aprendizaje/guardado de nueva habilidad."
    if re.match(r"^\s*(?:abre|inicia|lanza)\s+", low):
        target = re.sub(r"^\s*(?:abre|inicia|lanza)\s+", "", low, flags=re.IGNORECASE).strip()
        return "low", f"Apertura dinámica: {target[:120]}"
    return "low", "Acción estándar de asistente."


def needs_user_approval(text: str, *, trusted: set[str]) -> bool:
    """Por defecto no ejecutar automáticamente acciones de riesgo medio/alto."""
    h = hash_command(text)
    if h in trusted:
        return False
    risk, _summary = classify_action_risk(text)
    return risk in {"medium", "high"}


class EDABaseUI:
    """API mínima compartida entre backends."""

    def __init__(
        self,
        *,
        action_agent: ActionAgent | None = None,
        stt: STTManager | None = None,
        metrics_interval_ms: int = DEFAULT_METRICS_INTERVAL_MS,
    ) -> None:
        self.metrics_interval_ms = max(250, int(metrics_interval_ms))

        self.action_agent = action_agent or ActionAgent(
            actions=ActionController(),
            mouse_keyboard=MouseKeyboardController(),
            task_store=TaskMembershipStore(),
            observer=SystemObserver(),
        )
        self.memory = MemoryManager()
        self.core = EDACore(memory_manager=self.memory)
        self.system_info = SystemInfo()
        self.web_solver = WebSolver(self.core, self.memory)
        self.orchestrator = CommandOrchestrator(
            memory=self.memory,
            core=self.core,
            action_agent=self.action_agent,
            actions=self.action_agent.actions,
            system_info=self.system_info,
            web_solver=self.web_solver,
            can_execute=lambda _text: True,
        )
        self.stt = stt or STTManager(language="es-ES")

        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="eda-worker")
        self._stop_event = threading.Event()
        self._recent_logs: deque[str] = deque(maxlen=48)
        self._trusted_hashes = load_trusted_hashes()

        self._approval_events: dict[str, threading.Event] = {}
        self._approval_results: dict[str, dict[str, Any]] = {}

        self.rotate_btn_ref: Any = None

    # --- Hooks implementados por subclases ---
    def schedule(self, delay_ms: int, fn: Callable[[], None]) -> None:
        raise NotImplementedError

    def show_message(self, title: str, message: str) -> None:
        raise NotImplementedError

    def open_approval_modal(self, req_id: str, summary: str, risk: str, command_preview: str) -> None:
        raise NotImplementedError

    def set_send_enabled(self, enabled: bool) -> None:
        raise NotImplementedError

    def append_user_bubble(self, text: str) -> None:
        raise NotImplementedError

    def append_assistant_bubble(self, text: str) -> None:
        raise NotImplementedError

    def append_log_line(self, category: str, message: str) -> None:
        raise NotImplementedError

    # --- Core flow ---
    def run_async(self, fn: Callable[[], None]) -> None:
        self._ui_queue.put(fn)

    def pump_ui(self, max_items: int = 200) -> None:
        """Procesa callbacks UI en el hilo actual (útil en tests)."""
        for _ in range(max_items):
            try:
                cb = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            cb()

    def drain_queue_loop(self) -> None:
        if self._stop_event.is_set():
            return
        for _ in range(24):
            try:
                cb = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            cb()
        self.schedule(100, self.drain_queue_loop)

    def submit_command(self, text: str, *, display_user: str) -> None:
        if display_user:
            self.append_user_bubble(display_user)
        self.append_log_line("UI", f"INPUT: {display_user or text}")
        self.set_send_enabled(False)

        def worker() -> None:
            user = os.getenv("USERNAME") or os.getenv("USER") or "unknown"
            profile_before = self.memory.get_user_profile()
            profile_before_ts = str(profile_before.get("updated_at", ""))
            need = needs_user_approval(text, trusted=self._trusted_hashes)
            if need:
                req_id = hash_command(text + str(time.time_ns()))
                risk, summary = classify_action_risk(text)
                evt = threading.Event()
                self._approval_events[req_id] = evt

                def ask_ui() -> None:
                    self.open_approval_modal(req_id, summary, risk, text[:400])

                self.run_async(ask_ui)
                evt.wait(timeout=600)
                result = self._approval_results.pop(req_id, {"choice": "deny", "trust": False})
                choice = str(result.get("choice", "deny"))
                trust = bool(result.get("trust"))
                append_ui_audit(
                    {
                        "step": "ui_action_approval",
                        "outcome": choice,
                        "risk": risk,
                        "command_preview": command_preview_safe(text),
                        "user": user,
                        "trust_saved": trust,
                        "detail": summary[:240],
                    }
                )
                if choice == "deny":
                    def deny_ui() -> None:
                        self.append_assistant_bubble("Acción cancelada por el usuario.")
                        self.append_log_line("ACTION", "DENY: usuario rechazó ejecución.")
                        self.set_send_enabled(True)

                    self.run_async(deny_ui)
                    return
                if choice == "approve_once":
                    pass
                if choice == "approve" and trust:
                    save_trusted_hash(hash_command(text))
                    self._trusted_hashes.add(hash_command(text))

            handled = False
            answer = ""
            try:
                action_handled, action_answer = self.action_agent.try_handle(text)
                handled = bool(action_handled)
                answer = str(action_answer or "").strip()
            except Exception:
                handled = False
                answer = ""

            if not handled:
                result = self.orchestrator.orchestrate(text)
                handled = bool(result.handled)
                answer = (result.answer or "").strip()
            else:
                result = type("UIResult", (), {"handled": handled, "answer": answer, "source": "action_agent"})()
            if not answer:
                answer = "No reconozco ese comando, intenta decir 'abre [app]' o 'reproduce [música]'."
            try:
                self.orchestrator.persist(text, answer)
            except Exception:
                pass
            profile_after = self.memory.get_user_profile()
            profile_after_ts = str(profile_after.get("updated_at", ""))
            memory_updated = bool(profile_after_ts and profile_after_ts != profile_before_ts)

            def ui_done() -> None:
                self.append_assistant_bubble(answer)
                tag = "OK" if handled else "WARN"
                self.append_log_line("ACTION", f"{tag}: {(answer or '')[:220]}")
                source = str(getattr(result, "source", ""))
                if source.startswith("play_music") or source.startswith("spotify"):
                    self.append_log_line("SPOTIFY", f"Spotify Skill: {source}")
                elif source.startswith("play_youtube") or source.startswith("youtube"):
                    self.append_log_line("YOUTUBE", f"YouTube Skill: {source}")
                elif source.startswith("list_windows") or source.startswith("focus_window") or source.startswith("activate_app_window"):
                    self.append_log_line("WINDOWS", f"Window Skill: {source}")
                if str(getattr(result, "source", "")).startswith("trigger"):
                    self.append_log_line("TRIGGER", f"Trigger ejecutado: {getattr(result, 'source', '')}")
                if memory_updated:
                    self.append_log_line("MEMORY", "Memoria actualizada: perfil persistente")
                self.set_send_enabled(True)

            self.run_async(ui_done)

        self._executor.submit(worker)

    def listen_mic(self) -> None:
        def worker() -> None:
            heard = self.stt.listen_once(timeout=5.0, phrase_time_limit=8.0)

            def ui_done() -> None:
                if heard:
                    self.submit_command(heard, display_user=heard)
                else:
                    self.append_assistant_bubble("No detecté voz válida.")

            self.run_async(ui_done)

        self._executor.submit(worker)

    def update_metrics_loop(self) -> None:
        if self._stop_event.is_set():
            return
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        used = (mem.total - mem.available) / (1024**3)
        total = mem.total / (1024**3)
        ratio = min(max(mem.percent / 100.0, 0.0), 1.0)
        self.apply_metrics(cpu, used, total, ratio)
        self.schedule(self.metrics_interval_ms, self.update_metrics_loop)

    def apply_metrics(self, cpu: float, used_gb: float, total_gb: float, mem_ratio: float) -> None:
        raise NotImplementedError

    def on_close(self) -> None:
        self._stop_event.set()
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def resolve_approval(self, req_id: str, choice: str, *, trust: bool) -> None:
        self._approval_results[req_id] = {"choice": choice, "trust": trust}
        evt = self._approval_events.pop(req_id, None)
        if evt:
            evt.set()


def command_preview_safe(text: str) -> str:
    return _obfuscate_secret(re.sub(r"(token|password|pwd|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", text, flags=re.I))


def _make_eda_ctk_ui_class():
    if ctk is None:
        return None

    class EDAObsidianUICTk(EDABaseUI, ctk.CTk):  # type: ignore[misc]
        def __init__(self, *, metrics_interval_ms: int = DEFAULT_METRICS_INTERVAL_MS) -> None:
            assert ctk is not None
            ctk.CTk.__init__(self)
            EDABaseUI.__init__(self, metrics_interval_ms=metrics_interval_ms)
    
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
    
            self.title("EDA | CORE")
            self.geometry("1280x760")
            self.minsize(1100, 680)
            self.configure(fg_color=BG)
    
            self._build_layout()
            self.append_assistant_bubble("Protocolo de seguridad ejecutado. ¿Deseas iniciar rotación de llaves?")
    
            self.schedule(120, self.drain_queue_loop)
            self.schedule(500, self.update_metrics_loop)
            self.protocol("WM_DELETE_WINDOW", self._close)
    
        def schedule(self, delay_ms: int, fn: Callable[[], None]) -> None:
            self.after(delay_ms, fn)
    
        def show_message(self, title: str, message: str) -> None:
            messagebox.showinfo(title, message)
    
        def set_send_enabled(self, enabled: bool) -> None:
            state = "normal" if enabled else "disabled"
            self.send_btn.configure(state=state)
    
        def append_user_bubble(self, text: str) -> None:
            self._add_bubble(text, by_user=True, system_header=False)
    
        def append_assistant_bubble(self, text: str) -> None:
            self._add_bubble(text, by_user=False, system_header=True)
    
        def append_log_line(self, category: str, message: str) -> None:
            stamp = time.strftime("%H:%M")
            line = f"• [{stamp}] {category}: {message}"
            self._recent_logs.append(line)
            try:
                self.log_box.configure(state="normal")
                self.log_box.delete("0.0", "end")
                self.log_box.insert("0.0", "\n".join(self._recent_logs))
                self.log_box.configure(state="disabled")
            except Exception:
                pass
    
        def apply_metrics(self, cpu: float, used_gb: float, total_gb: float, mem_ratio: float) -> None:
            self.cpu_label.configure(text=f"CPU {cpu:.0f}%")
            self.cpu_bar.set(min(max(cpu / 100.0, 0.0), 1.0))
            self.ram_label.configure(text=f"RAM {used_gb:.1f} / {total_gb:.1f} GB")
            self.ram_bar.set(mem_ratio)
    
        def _build_layout(self) -> None:
            main = ctk.CTkFrame(self, fg_color=BG)
            main.pack(fill="both", expand=True, padx=12, pady=12)
    
            left = ctk.CTkFrame(main, fg_color=BG)
            left.pack(side="left", fill="both", expand=True)
    
            right = ctk.CTkFrame(main, fg_color=PANEL, border_width=1, border_color=BORDER, width=330)
            right.pack(side="right", fill="y", padx=(10, 0))
            right.pack_propagate(False)
    
            header = ctk.CTkFrame(left, fg_color=BG)
            header.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(
                header,
                text="EDA | CORE",
                text_color=ACCENT,
                font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            ).pack(side="left")
            sub = ctk.CTkFrame(header, fg_color=BG)
            sub.pack(side="left", padx=(12, 0))
            ctk.CTkLabel(
                sub,
                text="SRE SECURE OPS • 8GB OPTIMIZED",
                text_color=MUTED,
                font=ctk.CTkFont(family="Segoe UI", size=11),
            ).pack(anchor="w")
            ctk.CTkLabel(
                header,
                text="STT: READY",
                text_color=HEALTH,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            ).pack(side="right")
    
            self.chat_view = ctk.CTkScrollableFrame(
                left,
                fg_color=PANEL,
                border_width=1,
                border_color=BORDER,
                corner_radius=8,
            )
            self.chat_view.pack(fill="both", expand=True)
            self.chat_view.grid_columnconfigure(0, weight=1)
    
            input_row = ctk.CTkFrame(left, fg_color=BG)
            input_row.pack(fill="x", pady=(10, 0))
    
            self.entry = ctk.CTkEntry(
                input_row,
                fg_color="#0a0a0a",
                border_color=BORDER,
                text_color=TEXT,
                height=34,
                corner_radius=4,
                font=ctk.CTkFont(family="Segoe UI", size=13),
                placeholder_text="Escribe tu comando...",
            )
            self.entry.pack(side="left", fill="x", expand=True)
            self.entry.bind("<Return>", lambda _e: self._on_send())
    
            self.mic_btn = ctk.CTkButton(
                input_row,
                text="🎤",
                width=36,
                height=36,
                corner_radius=18,
                fg_color="#121212",
                hover_color="#1a1a1a",
                border_width=1,
                border_color=BORDER,
                command=self._on_mic,
            )
            self.mic_btn.pack(side="left", padx=8)
    
            self.send_btn = ctk.CTkButton(
                input_row,
                text="SEND",
                width=84,
                height=36,
                corner_radius=4,
                fg_color=ACCENT,
                text_color="#001318",
                hover_color="#06d9e3",
                command=self._on_send,
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            )
            self.send_btn.pack(side="left")
    
            ctk.CTkLabel(
                right,
                text="RECURSOS",
                text_color=MUTED,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            ).pack(anchor="w", padx=14, pady=(14, 8))
    
            self.cpu_label = ctk.CTkLabel(right, text="CPU 0%", text_color=ACCENT, font=ctk.CTkFont(family="Consolas", size=12))
            self.cpu_label.pack(anchor="w", padx=14)
            self.cpu_bar = ctk.CTkProgressBar(right, height=4, progress_color=ACCENT, fg_color="#111111")
            self.cpu_bar.pack(fill="x", padx=14, pady=(2, 8))
            self.cpu_bar.set(0.0)
    
            self.ram_label = ctk.CTkLabel(right, text="RAM 0.0 / 0.0 GB", text_color=HEALTH, font=ctk.CTkFont(family="Consolas", size=12))
            self.ram_label.pack(anchor="w", padx=14)
            self.ram_bar = ctk.CTkProgressBar(right, height=4, progress_color=HEALTH, fg_color="#111111")
            self.ram_bar.pack(fill="x", padx=14, pady=(2, 14))
            self.ram_bar.set(0.0)
    
            ctk.CTkLabel(
                right,
                text="ACCIONES RÁPIDAS",
                text_color=MUTED,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            ).pack(anchor="w", padx=14, pady=(8, 8))
    
            quick_grid = ctk.CTkFrame(right, fg_color=PANEL)
            quick_grid.pack(fill="x", padx=14)
            quick_grid.grid_columnconfigure((0, 1), weight=1, uniform="q")
    
            self._quick_btn(quick_grid, 0, 0, "Limpiar Disco", "ejecuta comando: dir")
            self._quick_btn(quick_grid, 0, 1, "Render GPU", "observar sistema: procesos")
            self._quick_btn(quick_grid, 1, 0, "Generar CV", "abre notepad")
            self.rotate_btn_ref = self._quick_btn(
                quick_grid,
                1,
                1,
                "Rotar Llaves",
                f"ejecuta comando: python \"{ROOT / 'tools' / 'rotate_keys.py'}\" --dry-run",
                highlight=True,
            )
            self._quick_btn(quick_grid, 2, 0, "Listar Triggers", "listar mis disparadores")
            self._quick_btn(quick_grid, 2, 1, "Crear Trigger", "crear disparador: ironman reproduce acdc")
    
            ctk.CTkLabel(
                right,
                text="ÚLTIMOS LOGS",
                text_color=MUTED,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            ).pack(anchor="w", padx=14, pady=(14, 6))
    
            self.log_box = ctk.CTkTextbox(
                right,
                fg_color="#080808",
                border_width=1,
                border_color=BORDER,
                text_color=MUTED,
                font=ctk.CTkFont(family="Consolas", size=11),
                height=170,
                wrap="word",
                activate_scrollbars=False,
            )
            self.log_box.pack(fill="both", expand=False, padx=14, pady=(0, 14))
    
        def _quick_btn(self, parent: Any, row: int, col: int, text: str, command_text: str, *, highlight: bool = False) -> Any:
            btn = ctk.CTkButton(
                parent,
                text=text,
                height=36,
                corner_radius=4,
                fg_color=ACCENT if highlight else "#0f0f0f",
                text_color="#001318" if highlight else TEXT,
                border_width=2 if highlight else 1,
                border_color=ACCENT if highlight else BORDER,
                hover_color="#06d9e3" if highlight else "#181818",
                command=lambda: self.submit_command(command_text, display_user=text),
            )
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="ew")
            return btn
    
        def _add_bubble(self, text: str, *, by_user: bool, system_header: bool) -> None:
            row = len(self.chat_view.winfo_children())
            wrap = ctk.CTkFrame(self.chat_view, fg_color=PANEL)
            wrap.grid(row=row, column=0, sticky="ew", pady=(9, 6), padx=(12, 24 if by_user else 10))
            wrap.grid_columnconfigure(0, weight=1)
    
            bubble = ctk.CTkFrame(
                wrap,
                fg_color=USER_BUBBLE if by_user else ASSIST_BUBBLE,
                border_width=1,
                border_color=BORDER,
                corner_radius=6,
            )
            bubble.grid(sticky="e" if by_user else "w", padx=(0, 16 if by_user else 0))
            if not by_user and system_header:
                ctk.CTkLabel(
                    bubble,
                    text="SYSTEM",
                    text_color=ACCENT,
                    font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
                ).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(
                bubble,
                text=text,
                text_color=TEXT,
                wraplength=680,
                justify="left",
                font=ctk.CTkFont(family="Segoe UI", size=13),
            ).pack(padx=10, pady=(4 if (not by_user and system_header) else 8, 8))
    
        def _on_send(self) -> None:
            text = self.entry.get().strip()
            if not text:
                return
            self.entry.delete(0, "end")
            self.submit_command(text, display_user=text)
    
        def _on_mic(self) -> None:
            self.mic_btn.configure(state="disabled")
            self.append_assistant_bubble("Escuchando micrófono...")
    
            def worker() -> None:
                heard = self.stt.listen_once(timeout=5.0, phrase_time_limit=8.0)
    
                def ui_done() -> None:
                    self.mic_btn.configure(state="normal")
                    if heard:
                        self.entry.delete(0, "end")
                        self.entry.insert(0, heard)
                        self.submit_command(heard, display_user=heard)
                    else:
                        self.append_assistant_bubble("No detecté voz válida.")
    
                self.run_async(ui_done)
    
            self._executor.submit(worker)
    
        def open_approval_modal(self, req_id: str, summary: str, risk: str, command_preview: str) -> None:
            win = ctk.CTkToplevel(self)
            win.title("Confirmación de acción")
            win.geometry("520x320")
            win.configure(fg_color=PANEL)
            win.grab_set()
    
            ctk.CTkLabel(win, text="Acción pendiente de aprobación", text_color=ACCENT, font=ctk.CTkFont(size=15, weight="bold")).pack(
                anchor="w", padx=14, pady=(14, 6)
            )
            ctk.CTkLabel(win, text=f"Riesgo: {risk}", text_color=TEXT).pack(anchor="w", padx=14)
            ctk.CTkLabel(win, text=summary, text_color=TEXT, wraplength=480, justify="left").pack(anchor="w", padx=14, pady=(6, 6))
            ctk.CTkLabel(win, text=f"Comando: {command_preview}", text_color=MUTED, wraplength=480, justify="left").pack(
                anchor="w", padx=14, pady=(0, 10)
            )
    
            trust_var = tk.BooleanVar(value=False)
    
            def finish(choice: str) -> None:
                self.resolve_approval(req_id, choice, trust=bool(trust_var.get()))
                win.destroy()
    
            row = ctk.CTkFrame(win, fg_color=PANEL)
            row.pack(fill="x", padx=14, pady=10)
            ctk.CTkButton(row, text="Deny", fg_color="#2a0000", hover_color="#3a0000", command=lambda: finish("deny")).pack(
                side="left", expand=True, fill="x", padx=4
            )
            ctk.CTkButton(row, text="Approve Once", command=lambda: finish("approve_once")).pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkButton(row, text="Approve", fg_color=ACCENT, text_color="#001318", command=lambda: finish("approve")).pack(
                side="left", expand=True, fill="x", padx=4
            )
    
            ctk.CTkCheckBox(win, text="Record trust (guardar confianza para este comando)", variable=trust_var).pack(
                anchor="w", padx=14, pady=(0, 14)
            )
    
        def _close(self) -> None:
            self.on_close()
            self.destroy()

    return EDAObsidianUICTk


EDAObsidianUICTk = _make_eda_ctk_ui_class()


class EDAObsidianUITk(EDABaseUI, tk.Tk):
    """Fallback ligero con Tkinter estándar."""

    def __init__(self, *, metrics_interval_ms: int = DEFAULT_METRICS_INTERVAL_MS) -> None:
        tk.Tk.__init__(self)
        EDABaseUI.__init__(self, metrics_interval_ms=metrics_interval_ms)

        self.title("EDA | CORE")
        self.geometry("1280x760")
        self.configure(bg=BG)

        self._build_layout()
        self.append_assistant_bubble("Protocolo de seguridad ejecutado (modo Tk fallback).")

        self.schedule(120, self.drain_queue_loop)
        self.schedule(500, self.update_metrics_loop)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def schedule(self, delay_ms: int, fn: Callable[[], None]) -> None:
        self.after(delay_ms, fn)

    def show_message(self, title: str, message: str) -> None:
        messagebox.showinfo(title, message)

    def set_send_enabled(self, enabled: bool) -> None:
        self.send_btn.configure(state="normal" if enabled else "disabled")

    def append_user_bubble(self, text: str) -> None:
        self._add_bubble(text, by_user=True, system_header=False)

    def append_assistant_bubble(self, text: str) -> None:
        self._add_bubble(text, by_user=False, system_header=True)

    def append_log_line(self, category: str, message: str) -> None:
        stamp = time.strftime("%H:%M")
        line = f"• [{stamp}] {category}: {message}"
        self._recent_logs.append(line)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", "\n".join(self._recent_logs))
        self.log_box.configure(state="disabled")

    def apply_metrics(self, cpu: float, used_gb: float, total_gb: float, mem_ratio: float) -> None:
        self.cpu_label.configure(text=f"CPU {cpu:.0f}%")
        self.cpu_bar["value"] = min(max(cpu, 0.0), 100.0)
        self.ram_label.configure(text=f"RAM {used_gb:.1f} / {total_gb:.1f} GB")
        self.ram_bar["value"] = mem_ratio * 100.0

    def _build_layout(self) -> None:
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        left = tk.Frame(main, bg=BG)
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, width=330)
        right.pack(side="right", fill="y", padx=(10, 0))

        header = tk.Frame(left, bg=BG)
        header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text="EDA | CORE", fg=ACCENT, bg=BG, font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(header, text="STT: READY", fg=HEALTH, bg=BG, font=("Consolas", 12, "bold")).pack(side="right")

        self.chat_canvas = tk.Canvas(left, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, height=520)
        self.chat_canvas.pack(fill="both", expand=True)

        input_row = tk.Frame(left, bg=BG)
        input_row.pack(fill="x", pady=(10, 0))

        self.entry = tk.Entry(input_row, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT, relief="solid", bd=1)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self._on_send())

        self.mic_btn = tk.Button(input_row, text="🎤", command=self._on_mic, bg="#121212", fg=TEXT)
        self.mic_btn.pack(side="left", padx=8)

        self.send_btn = tk.Button(
            input_row,
            text="SEND",
            command=self._on_send,
            bg=ACCENT,
            fg="#001318",
            font=("Segoe UI", 11, "bold"),
            padx=12,
        )
        self.send_btn.pack(side="left")

        tk.Label(right, text="RECURSOS", fg=MUTED, bg=PANEL, font=("Consolas", 11, "bold")).pack(anchor="w", padx=10, pady=(12, 6))
        self.cpu_label = tk.Label(right, text="CPU 0%", fg=ACCENT, bg=PANEL, font=("Consolas", 11))
        self.cpu_label.pack(anchor="w", padx=10)
        self.cpu_bar = ttk.Progressbar(right, maximum=100, length=260)
        self.cpu_bar.pack(fill="x", padx=10, pady=(0, 8))

        self.ram_label = tk.Label(right, text="RAM", fg=HEALTH, bg=PANEL, font=("Consolas", 11))
        self.ram_label.pack(anchor="w", padx=10)
        self.ram_bar = ttk.Progressbar(right, maximum=100, length=260)
        self.ram_bar.pack(fill="x", padx=10, pady=(0, 12))

        qf = tk.Frame(right, bg=PANEL)
        qf.pack(fill="x", padx=10)
        self._tk_quick(qf, 0, 0, "Limpiar Disco", "ejecuta comando: dir")
        self._tk_quick(qf, 0, 1, "Render GPU", "observar sistema: procesos")
        self._tk_quick(qf, 1, 0, "Generar CV", "abre notepad")
        self.rotate_btn_ref = self._tk_quick(
            qf,
            1,
            1,
            "Rotar Llaves",
            f"ejecuta comando: python \"{ROOT / 'tools' / 'rotate_keys.py'}\" --dry-run",
            highlight=True,
        )
        self._tk_quick(qf, 2, 0, "Listar Triggers", "listar mis disparadores")
        self._tk_quick(qf, 2, 1, "Crear Trigger", "crear disparador: ironman reproduce acdc")

        tk.Label(right, text="ÚLTIMOS LOGS", fg=MUTED, bg=PANEL, font=("Consolas", 11, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        self.log_box = tk.Text(right, height=10, bg="#080808", fg=MUTED, font=("Consolas", 10), state="disabled")
        self.log_box.pack(fill="both", expand=False, padx=10, pady=(0, 12))

    def _tk_quick(self, parent: tk.Frame, r: int, c: int, label: str, cmd: str, *, highlight: bool = False) -> tk.Button:
        btn = tk.Button(
            parent,
            text=label,
            command=lambda: self.submit_command(cmd, display_user=label),
            bg=ACCENT if highlight else "#0f0f0f",
            fg="#001318" if highlight else TEXT,
            activebackground="#06d9e3" if highlight else "#181818",
            activeforeground="#001318" if highlight else TEXT,
            highlightbackground=ACCENT if highlight else BORDER,
            highlightthickness=2 if highlight else 1,
        )
        btn.grid(row=r, column=c, padx=4, pady=4, sticky="ew")
        parent.grid_columnconfigure((0, 1), weight=1)
        return btn

    def _add_bubble(self, text: str, *, by_user: bool, system_header: bool) -> None:
        color = USER_BUBBLE if by_user else ASSIST_BUBBLE
        y = 10 + len(self.chat_canvas.find_all()) * 6
        self.chat_canvas.create_rectangle(10, y, 900, y + 92, fill=color, outline=BORDER)
        yy = y + 10
        if not by_user and system_header:
            self.chat_canvas.create_text(
                20, yy, anchor="nw", fill=ACCENT, font=("Consolas", 11, "bold"), text="SYSTEM"
            )
            yy += 22
        self.chat_canvas.create_text(20, yy, anchor="nw", fill=TEXT, font=("Segoe UI", 11), text=text, width=860)

    def _on_send(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self.submit_command(text, display_user=text)

    def _on_mic(self) -> None:
        self.listen_mic()

    def open_approval_modal(self, req_id: str, summary: str, risk: str, command_preview: str) -> None:
        win = tk.Toplevel(self)
        win.title("Confirmación")
        win.configure(bg=PANEL)
        win.grab_set()
        tk.Label(win, text="Acción pendiente", fg=ACCENT, bg=PANEL, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=10)
        tk.Label(win, text=f"Riesgo: {risk}", fg=TEXT, bg=PANEL).pack(anchor="w", padx=12)
        tk.Label(win, text=summary, fg=TEXT, bg=PANEL, wraplength=460, justify="left").pack(anchor="w", padx=12)
        tk.Label(win, text=f"Comando: {command_preview}", fg=MUTED, bg=PANEL, wraplength=460, justify="left").pack(
            anchor="w", padx=12, pady=6
        )
        trust_var = tk.BooleanVar(value=False)
        tk.Checkbutton(win, text="Record trust", variable=trust_var, bg=PANEL, fg=TEXT, selectcolor="#222").pack(
            anchor="w", padx=12
        )

        def finish(choice: str) -> None:
            self.resolve_approval(req_id, choice, trust=bool(trust_var.get()))
            win.destroy()

        bf = tk.Frame(win, bg=PANEL)
        bf.pack(fill="x", padx=12, pady=12)
        tk.Button(bf, text="Deny", command=lambda: finish("deny")).pack(side="left", expand=True, fill="x", padx=4)
        tk.Button(bf, text="Approve Once", command=lambda: finish("approve_once")).pack(side="left", expand=True, fill="x", padx=4)
        tk.Button(bf, text="Approve", command=lambda: finish("approve")).pack(side="left", expand=True, fill="x", padx=4)

    def _close(self) -> None:
        self.on_close()
        self.destroy()


def build_app(*, metrics_interval_ms: int | None = None, prefer: str = "auto") -> EDABaseUI:
    interval = metrics_interval_ms if metrics_interval_ms is not None else DEFAULT_METRICS_INTERVAL_MS
    if prefer == "tk":
        return EDAObsidianUITk(metrics_interval_ms=interval)
    if prefer == "ctk":
        if EDAObsidianUICTk is None:
            return EDAObsidianUITk(metrics_interval_ms=interval)
        return EDAObsidianUICTk(metrics_interval_ms=interval)
    if EDAObsidianUICTk is not None:
        try:
            return EDAObsidianUICTk(metrics_interval_ms=interval)
        except Exception:
            return EDAObsidianUITk(metrics_interval_ms=interval)
    return EDAObsidianUITk(metrics_interval_ms=interval)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Interfaz EDA Obsidian")
    p.add_argument("--no-gui", action="store_true", help="No abrir ventana (útil en CI/import checks).")
    p.add_argument("--metrics-ms", type=int, default=DEFAULT_METRICS_INTERVAL_MS, help="Intervalo métricas UI (ms).")
    p.add_argument("--backend", choices=["auto", "ctk", "tk"], default="auto", help="Forzar backend gráfico.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.no_gui or _headless_default():
        return 0
    app = build_app(metrics_interval_ms=args.metrics_ms, prefer=args.backend)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
