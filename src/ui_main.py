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
import shutil
import sys
import threading
import time
import zipfile
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
from eda import config as eda_config
from eda.actions import ActionController
from eda.core import EDACore
from eda.memory import MemoryManager
from eda.mouse_keyboard import MouseKeyboardController
from eda.orchestrator import CommandOrchestrator
from eda.stt import STTManager
from eda.system_info import SystemInfo
from eda.system_observer import SystemObserver
from eda.task_membership import TaskMembershipStore
from eda.health_check import run_health_check
from eda.tts import TTSManager
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

AUDIT_PATH = ROOT / "data" / "logs" / "operate_secure_audit.jsonl"
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
        self.tts = TTSManager()

        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="eda-worker")
        self._stop_event = threading.Event()
        self._recent_logs: deque[str] = deque(maxlen=48)
        self._trusted_hashes = load_trusted_hashes()

        self._approval_events: dict[str, threading.Event] = {}
        self._approval_results: dict[str, dict[str, Any]] = {}
        self.continuous_wake_word = "eda"
        self.continuous_sensitivity = 0.6
        self.continuous_post_window = 5.0
        self.continuous_allow_non_destructive = False
        self.continuous_enabled = False
        self._continuous_state = "idle"
        self.push_to_talk_enabled = False
        self._last_trace = "Sin trazas"
        self._last_health_signature = ""
        self._last_health_check_ts = 0.0
        self._health_check_running = False

        self.rotate_btn_ref: Any = None

    def set_tts_enabled(self, enabled: bool) -> None:
        self.tts.enabled = bool(enabled)
        state = "activada" if self.tts.enabled else "desactivada"
        self.append_log_line("VOICE", f"Voz {state}.")

    def set_tts_rate(self, rate: int) -> None:
        safe = max(120, min(240, int(rate)))
        try:
            self.tts.set_rate(safe)
            self.append_log_line("VOICE", f"Velocidad de voz: {safe}.")
        except Exception:
            self.append_log_line("VOICE", "No pude ajustar la velocidad de voz.")

    def update_trace(self, text: str) -> None:
        _ = text

    def open_trigger_panel(self) -> None:
        raise NotImplementedError

    def open_trigger_wizard(self) -> None:
        raise NotImplementedError

    def open_profile_panel(self) -> None:
        raise NotImplementedError

    def open_backup_center(self) -> None:
        raise NotImplementedError

    def export_backup_snapshot(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = ROOT / "data" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        base_name = export_dir / f"eda_backup_{stamp}"
        include_paths = [
            ROOT / "config",
            ROOT / "data" / "memory",
            ROOT / "data" / "exports",
        ]
        temp_root = export_dir / f".tmp_backup_{stamp}"
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            for p in include_paths:
                if not p.exists():
                    continue
                target = temp_root / p.name
                if p.is_dir():
                    shutil.copytree(p, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(p, target)
            archive = shutil.make_archive(str(base_name), "zip", root_dir=str(temp_root))
            return archive
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def list_backup_snapshots(self) -> list[Path]:
        export_dir = ROOT / "data" / "exports"
        if not export_dir.exists():
            return []
        return sorted(export_dir.glob("eda_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)

    def restore_backup_snapshot(self, backup_zip: Path) -> tuple[bool, str]:
        src = Path(backup_zip)
        if not src.exists() or src.suffix.lower() != ".zip":
            return False, "Backup no válido."
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp = ROOT / "data" / "exports" / f".tmp_restore_{stamp}"
        temp.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(src, "r") as zf:
                zf.extractall(temp)
            # El backup guarda carpetas raíz: config, memory, exports
            mapping = [
                (temp / "config", ROOT / "config"),
                (temp / "memory", ROOT / "data" / "memory"),
                (temp / "exports", ROOT / "data" / "exports"),
            ]
            restored = 0
            for origin, target in mapping:
                if not origin.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(origin, target, dirs_exist_ok=True)
                restored += 1
            if restored == 0:
                return False, "No encontré contenido restaurable dentro del backup."
            return True, f"Restauración completada desde: {src.name}"
        except Exception as exc:
            return False, f"No pude restaurar backup: {exc}"
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def export_advanced_diagnostic(self) -> tuple[Path, Path]:
        out_dir = ROOT / "data" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        checks = run_health_check()
        report = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "checks": checks,
            "conversation_style": str(getattr(self.core, "conversation_style", "unknown")),
            "trigger_count": len(self.orchestrator.triggers.list_triggers(active_only=False)),
            "backups_available": len(self.list_backup_snapshots()),
        }
        json_path = out_dir / f"diagnostico_avanzado_{ts}.json"
        txt_path = out_dir / f"diagnostico_avanzado_{ts}.txt"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            f"EDA Diagnóstico Avanzado - {report['timestamp']}",
            f"Estilo conversación: {report['conversation_style']}",
            f"Triggers totales: {report['trigger_count']}",
            f"Backups disponibles: {report['backups_available']}",
            "",
            "Checks:",
        ]
        for k, v in checks.items():
            lines.append(f"- {k}: {v}")
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, txt_path

    def _handle_local_voice_command(self, text: str) -> str | None:
        low = (text or "").strip().lower()
        if not low:
            return None
        if low in {"silencio", "callate", "cállate", "mute voz", "mutear voz"}:
            self.set_tts_enabled(False)
            return "Entendido. He desactivado la voz."
        if low in {"habla", "activar voz", "activa voz"}:
            self.set_tts_enabled(True)
            return "Entendido. He activado la voz."
        if "habla mas lento" in low or "habla más lento" in low:
            self.set_tts_rate(max(120, int(getattr(self.tts, "rate", 175)) - 15))
            return "Entendido. Hablaré más despacio."
        if "habla mas rapido" in low or "habla más rápido" in low:
            self.set_tts_rate(min(240, int(getattr(self.tts, "rate", 175)) + 15))
            return "Entendido. Hablaré más rápido."
        return None

    def _push_to_talk_start(self) -> None:
        if not self.push_to_talk_enabled:
            return
        self.append_log_line("VOICE", "Push-to-talk activo: mantenga pulsado para hablar.")

        def _on_text(txt: str) -> None:
            cleaned = (txt or "").strip()
            if cleaned:
                self.run_async(lambda: self.submit_command(cleaned, display_user=cleaned))

        self.stt.start_background(_on_text)

    def _push_to_talk_stop(self) -> None:
        if not self.push_to_talk_enabled:
            return
        self.stt.stop_background()

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

    def render_youtube_candidates(self, candidates: list[dict[str, Any]]) -> None:
        # Hook opcional: algunas variantes UI/tests no renderizan tarjetas.
        _ = candidates

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
        local_voice = self._handle_local_voice_command(text)
        if local_voice:
            self.append_assistant_bubble(local_voice)
            self.tts.speak_async(local_voice)
            self.update_trace("local_voice_command")
            return
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
                self.update_trace(f"source={source or 'unknown'} | handled={handled}")
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
                payload = getattr(result, "payload", None) or {}
                candidates = payload.get("youtube_candidates", [])
                if isinstance(candidates, list) and candidates:
                    self.render_youtube_candidates(candidates[:5])
                    tts_text = str(payload.get("tts", "")).strip()
                    if tts_text:
                        self.tts.speak_async(tts_text)
                elif answer:
                    # Voz por defecto para respuestas generales y Q&A.
                    self.tts.speak_async(answer)
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
        now = time.time()
        if (now - self._last_health_check_ts) >= 60.0 and not self._health_check_running:
            self._last_health_check_ts = now
            self._health_check_running = True

            def health_worker() -> None:
                try:
                    checks = run_health_check()
                except Exception:
                    checks = {}

                def apply_health() -> None:
                    try:
                        bad = [(k, v) for k, v in checks.items() if str(v).lower().startswith(("error", "offline", "missing", "warn"))]
                        signature = "|".join(f"{k}:{v}" for k, v in bad[:4])
                        if signature and signature != self._last_health_signature:
                            self._last_health_signature = signature
                            self.append_log_line("HEALTH", f"Alertas detectadas: {len(bad)} (usa 'diagnóstico de salud').")
                    finally:
                        self._health_check_running = False

                self.run_async(apply_health)

            self._executor.submit(health_worker)
        self.schedule(self.metrics_interval_ms, self.update_metrics_loop)

    def apply_metrics(self, cpu: float, used_gb: float, total_gb: float, mem_ratio: float) -> None:
        raise NotImplementedError

    def on_close(self) -> None:
        self._stop_event.set()
        try:
            self.stt.stop_continuous_listener()
        except Exception:
            pass
        try:
            self.orchestrator.close()
        except Exception:
            pass
        try:
            self.tts.shutdown()
        except Exception:
            pass
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def _set_listen_state_visual(self, state: str, confidence: float) -> None:
        _ = (state, confidence)

    def _on_continuous_state(self, state: str, confidence: float) -> None:
        self._continuous_state = state
        self.run_async(lambda: self._set_listen_state_visual(state, confidence))

    def _on_continuous_wakeword(self, heard: str) -> None:
        msg = "He escuchado 'eda'. Puedes dar la orden ahora."
        self.run_async(lambda: self.append_assistant_bubble(msg))
        self.tts.speak_async(msg)
        self.append_log_line("VOICE", f"Wakeword detectada (confianza variable). Texto: {heard[:80]}")

    def _on_continuous_command(self, command: str) -> None:
        cleaned = (command or "").strip()
        if not cleaned:
            return
        self.run_async(lambda: self.submit_command(cleaned, display_user=cleaned))

    def toggle_continuous_listening(self, enabled: bool) -> bool:
        if not enabled:
            self.stt.stop_continuous_listener()
            self.continuous_enabled = False
            self._set_listen_state_visual("idle", 0.0)
            self.append_log_line("VOICE", "Escucha continua desactivada.")
            return True
        ok = self.stt.start_continuous_listener(
            on_command=self._on_continuous_command,
            on_state=self._on_continuous_state,
            on_wakeword=self._on_continuous_wakeword,
            wake_word=self.continuous_wake_word,
            sensitivity=self.continuous_sensitivity,
            post_activation_window=self.continuous_post_window,
        )
        self.continuous_enabled = bool(ok)
        if ok:
            self._set_listen_state_visual("wait_wakeword", 0.0)
            self.append_log_line("VOICE", "Escucha continua activa (esperando wakeword).")
        else:
            self.append_assistant_bubble("No pude activar escucha continua. Revisa el micrófono.")
        return ok

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

        def render_youtube_candidates(self, candidates: list[dict[str, Any]]) -> None:
            for w in self.yt_candidates_frame.winfo_children():
                w.destroy()
            for i, cand in enumerate(candidates[:5]):
                row = ctk.CTkFrame(self.yt_candidates_frame, fg_color="#0a0a0a", border_width=1, border_color=BORDER)
                row.pack(fill="x", padx=4, pady=3)
                title = str(cand.get("title", "video")).strip()
                channel = str(cand.get("channel", "canal")).strip()
                thumb = str(cand.get("thumbnail", "")).strip()
                url = str(cand.get("url", "")).strip()
                ctk.CTkLabel(
                    row,
                    text=f"{i+1}) {title}\nCanal: {channel}\nThumb: {thumb[:80]}",
                    text_color=TEXT,
                    justify="left",
                    wraplength=220,
                ).pack(side="left", padx=6, pady=5, fill="x", expand=True)
                ctk.CTkButton(
                    row,
                    text="Abrir",
                    width=56,
                    command=lambda idx=i + 1: self.submit_command(str(idx), display_user=f"Abrir YouTube #{idx}"),
                ).pack(side="right", padx=6)
    
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

            self.continuous_var = tk.BooleanVar(value=False)
            self.listen_state_label = ctk.CTkLabel(
                input_row,
                text="● OFF",
                text_color=MUTED,
                width=88,
                font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
            )
            self.listen_state_label.pack(side="left", padx=(8, 4))
            ctk.CTkSwitch(
                input_row,
                text="Escucha continua",
                variable=self.continuous_var,
                command=lambda: self.toggle_continuous_listening(bool(self.continuous_var.get())),
            ).pack(side="left", padx=(2, 0))
            self.push_to_talk_var = tk.BooleanVar(value=False)
            ctk.CTkSwitch(
                input_row,
                text="Push-to-talk",
                variable=self.push_to_talk_var,
                command=lambda: setattr(self, "push_to_talk_enabled", bool(self.push_to_talk_var.get())),
            ).pack(side="left", padx=(6, 0))
            self.mic_btn.bind("<ButtonPress-1>", lambda _e: self._push_to_talk_start())
            self.mic_btn.bind("<ButtonRelease-1>", lambda _e: self._push_to_talk_stop())
    
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
                text="SETTINGS > YOUTUBE",
                text_color=MUTED,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            ).pack(anchor="w", padx=14, pady=(6, 4))
            self.yt_auto_open_var = tk.BooleanVar(value=bool(getattr(self.orchestrator, "set_youtube_auto_open", None) and os.getenv("YOUTUBE_AUTO_OPEN", "false").lower() in {"1", "true", "yes", "on"}))

            def _toggle_yt_auto_open() -> None:
                self.orchestrator.set_youtube_auto_open(bool(self.yt_auto_open_var.get()))
                self.append_log_line("YOUTUBE", f"Auto-open {'ON' if self.yt_auto_open_var.get() else 'OFF'}")

            ctk.CTkCheckBox(
                right,
                text="Auto-open top result",
                variable=self.yt_auto_open_var,
                command=_toggle_yt_auto_open,
            ).pack(anchor="w", padx=14, pady=(0, 8))

            ctk.CTkLabel(
                right,
                text="SETTINGS > VOZ",
                text_color=MUTED,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            ).pack(anchor="w", padx=14, pady=(6, 4))
            self.tts_enabled_var = tk.BooleanVar(value=True)
            ctk.CTkSwitch(
                right,
                text="Voz en respuestas",
                variable=self.tts_enabled_var,
                command=lambda: self.set_tts_enabled(bool(self.tts_enabled_var.get())),
            ).pack(anchor="w", padx=14, pady=(0, 4))
            self.wake_word_var = tk.StringVar(value=self.continuous_wake_word)
            ctk.CTkEntry(right, textvariable=self.wake_word_var, width=120, placeholder_text="wake word").pack(
                anchor="w", padx=14, pady=(0, 4)
            )
            self.post_window_var = tk.DoubleVar(value=self.continuous_post_window)
            ctk.CTkEntry(right, textvariable=self.post_window_var, width=120, placeholder_text="post window s").pack(
                anchor="w", padx=14, pady=(0, 6)
            )
            self.tts_rate_var = tk.IntVar(value=175)
            ctk.CTkEntry(right, textvariable=self.tts_rate_var, width=120, placeholder_text="voz rate 120-240").pack(
                anchor="w", padx=14, pady=(0, 6)
            )
            self.conv_style_var = tk.StringVar(value=str(getattr(self.core, "conversation_style", "neutral")))
            ctk.CTkOptionMenu(
                right,
                variable=self.conv_style_var,
                values=["neutral", "formal", "cercano", "breve"],
                width=140,
            ).pack(anchor="w", padx=14, pady=(0, 6))
            self.spotify_official_var = tk.BooleanVar(value=bool(getattr(eda_config, "EDA_SPOTIFY_PREFER_OFFICIAL", True)))
            ctk.CTkCheckBox(
                right,
                text="Spotify: preferir versión oficial",
                variable=self.spotify_official_var,
            ).pack(anchor="w", padx=14, pady=(0, 6))

            def _apply_voice_settings() -> None:
                self.continuous_wake_word = (self.wake_word_var.get() or "eda").strip() or "eda"
                try:
                    self.continuous_post_window = max(2.0, min(12.0, float(self.post_window_var.get())))
                except Exception:
                    self.continuous_post_window = 5.0
                self.set_tts_rate(int(self.tts_rate_var.get()))
                style = str(self.conv_style_var.get() or "neutral")
                setter = getattr(self.core, "set_conversation_style", None)
                if callable(setter):
                    style = setter(style)
                eda_config.EDA_CONVERSATION_STYLE = style
                eda_config.EDA_SPOTIFY_PREFER_OFFICIAL = bool(self.spotify_official_var.get())
                self.append_log_line("AI", f"Estilo conversación: {style}")
                self.append_log_line(
                    "SPOTIFY",
                    f"Versión oficial {'ON' if bool(self.spotify_official_var.get()) else 'OFF'}",
                )

            ctk.CTkButton(right, text="Aplicar voz", width=120, command=_apply_voice_settings).pack(
                anchor="w", padx=14, pady=(0, 8)
            )
    
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
            self._quick_btn(quick_grid, 3, 0, "Borrar Trigger", "borrar disparador")
            self._quick_btn(quick_grid, 3, 1, "Desactivar Trigger", "desactivar disparador")
            self._quick_btn(quick_grid, 4, 0, "Diagnóstico", "diagnóstico de salud")
            ctk.CTkButton(quick_grid, text="Panel Triggers", command=self.open_trigger_panel).grid(row=4, column=1, padx=4, pady=4, sticky="ew")
            ctk.CTkButton(quick_grid, text="Backup", command=self._export_backup_click).grid(row=5, column=0, padx=4, pady=4, sticky="ew")
            ctk.CTkButton(quick_grid, text="Asistente Trigger", command=self.open_trigger_wizard).grid(
                row=5, column=1, padx=4, pady=4, sticky="ew"
            )
            ctk.CTkButton(quick_grid, text="Perfil Usuario", command=self.open_profile_panel).grid(
                row=6, column=0, padx=4, pady=4, sticky="ew"
            )
            ctk.CTkButton(quick_grid, text="Centro Backups", command=self.open_backup_center).grid(
                row=6, column=1, padx=4, pady=4, sticky="ew"
            )
            ctk.CTkButton(
                quick_grid,
                text="Diag Avanzado",
                command=lambda: (
                    lambda jp_tp: (
                        self.append_assistant_bubble(f"Diagnóstico exportado: {jp_tp[0]} | {jp_tp[1]}"),
                        self.append_log_line("HEALTH", f"Diagnóstico avanzado: {jp_tp[0].name}"),
                    )
                )(self.export_advanced_diagnostic()),
            ).grid(row=7, column=0, padx=4, pady=4, sticky="ew")
    
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
            self.trace_label = ctk.CTkLabel(
                right,
                text="TRACE: Sin trazas",
                text_color=MUTED,
                font=ctk.CTkFont(family="Consolas", size=10),
                wraplength=280,
                justify="left",
            )
            self.trace_label.pack(anchor="w", padx=14, pady=(0, 10))

            ctk.CTkLabel(
                right,
                text="YOUTUBE RESULTADOS",
                text_color=MUTED,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            ).pack(anchor="w", padx=14, pady=(8, 6))
            self.yt_candidates_frame = ctk.CTkScrollableFrame(
                right,
                fg_color="#080808",
                border_width=1,
                border_color=BORDER,
                height=180,
            )
            self.yt_candidates_frame.pack(fill="x", padx=14, pady=(0, 12))
    
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
            if self.push_to_talk_enabled:
                return
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

        def _export_backup_click(self) -> None:
            path = self.export_backup_snapshot()
            self.append_assistant_bubble(f"Backup creado: {path}")
            self.append_log_line("BACKUP", path)

        def update_trace(self, text: str) -> None:
            self.trace_label.configure(text=f"TRACE: {text[:140]}")

        def open_trigger_panel(self) -> None:
            win = ctk.CTkToplevel(self)
            win.title("Panel de Triggers")
            win.geometry("760x520")
            win.configure(fg_color=PANEL)

            list_wrap = ctk.CTkScrollableFrame(win, fg_color="#080808", border_color=BORDER, border_width=1)
            list_wrap.pack(fill="both", expand=True, padx=12, pady=(12, 8))

            def refresh() -> None:
                for w in list_wrap.winfo_children():
                    w.destroy()
                rows = self.orchestrator.triggers.list_triggers(active_only=False)
                run_map = self.orchestrator.triggers.get_last_run_map()
                if not rows:
                    ctk.CTkLabel(list_wrap, text="No hay triggers.", text_color=MUTED).pack(anchor="w", padx=8, pady=8)
                    return
                for r in rows[:120]:
                    row = ctk.CTkFrame(list_wrap, fg_color="#111111", border_color=BORDER, border_width=1)
                    row.pack(fill="x", padx=6, pady=4)
                    status = "ON" if r.get("active") else "OFF"
                    last = run_map.get(int(r.get("id", 0)))
                    last_line = ""
                    if last:
                        last_line = f"\nÚltimo: {last.get('status')} ({last.get('created_at')})"
                    ctk.CTkLabel(
                        row,
                        text=f"#{r['id']} [{status}] {r['phrase']} -> {r['action_type']}{last_line}",
                        text_color=TEXT,
                        justify="left",
                        wraplength=430,
                    ).pack(side="left", fill="x", expand=True, padx=8, pady=6)
                    ctk.CTkButton(
                        row,
                        text="Activar",
                        width=72,
                        command=lambda tid=r["id"]: self.submit_command(f"activar disparador {tid}", display_user=f"activar {tid}"),
                    ).pack(side="left", padx=3)
                    ctk.CTkButton(
                        row,
                        text="Desactivar",
                        width=86,
                        command=lambda tid=r["id"]: self.submit_command(f"desactivar disparador {tid}", display_user=f"desactivar {tid}"),
                    ).pack(side="left", padx=3)
                    ctk.CTkButton(
                        row,
                        text="Borrar",
                        width=64,
                        fg_color="#7a1f1f",
                        hover_color="#8c2525",
                        command=lambda tid=r["id"]: self.submit_command(f"borrar disparador {tid}", display_user=f"borrar {tid}"),
                    ).pack(side="left", padx=3)
                    ctk.CTkButton(
                        row,
                        text="Editar",
                        width=64,
                        command=lambda tr=r: open_edit_modal(tr),
                    ).pack(side="left", padx=3)
                    ctk.CTkButton(
                        row,
                        text="Historial",
                        width=72,
                        command=lambda tid=r["id"]: open_history_modal(int(tid)),
                    ).pack(side="left", padx=3)

            def open_edit_modal(trigger_row: dict[str, Any]) -> None:
                edit = ctk.CTkToplevel(win)
                edit.title(f"Editar Trigger #{trigger_row.get('id')}")
                edit.geometry("560x360")
                edit.configure(fg_color=PANEL)
                phrase_var = tk.StringVar(value=str(trigger_row.get("phrase", "")))
                action_var = tk.StringVar(value=str(trigger_row.get("action_type", "")))
                payload_var = tk.StringVar(value=json.dumps(trigger_row.get("action_payload", {}), ensure_ascii=False))
                req_var = tk.BooleanVar(value=bool(trigger_row.get("require_confirm", True)))
                ctk.CTkLabel(edit, text="Frase").pack(anchor="w", padx=12, pady=(12, 4))
                ctk.CTkEntry(edit, textvariable=phrase_var).pack(fill="x", padx=12)
                ctk.CTkLabel(edit, text="Acción (action_type)").pack(anchor="w", padx=12, pady=(10, 4))
                ctk.CTkEntry(edit, textvariable=action_var).pack(fill="x", padx=12)
                ctk.CTkLabel(edit, text="Payload JSON").pack(anchor="w", padx=12, pady=(10, 4))
                ctk.CTkEntry(edit, textvariable=payload_var).pack(fill="x", padx=12)
                ctk.CTkCheckBox(edit, text="Requiere confirmación", variable=req_var).pack(anchor="w", padx=12, pady=(10, 10))

                def _save_edit() -> None:
                    try:
                        payload = json.loads(str(payload_var.get() or "{}"))
                        if not isinstance(payload, dict):
                            payload = {}
                    except Exception:
                        self.append_assistant_bubble("Payload inválido: debe ser JSON objeto.")
                        return
                    ok = self.orchestrator.triggers.update_trigger(
                        int(trigger_row.get("id", 0)),
                        phrase=str(phrase_var.get() or ""),
                        action_type=str(action_var.get() or ""),
                        action_payload=payload,
                        require_confirm=bool(req_var.get()),
                        match_type=str(trigger_row.get("match_type", "fuzzy")),
                        fuzzy_threshold=float(trigger_row.get("fuzzy_threshold", 80.0)),
                    )
                    if ok:
                        self.append_assistant_bubble(f"Trigger #{trigger_row.get('id')} actualizado.")
                        refresh()
                        edit.destroy()
                    else:
                        self.append_assistant_bubble("No pude actualizar el trigger.")

                ctk.CTkButton(edit, text="Guardar", command=_save_edit).pack(anchor="e", padx=12, pady=(0, 12))

            def open_history_modal(trigger_id: int) -> None:
                hwin = ctk.CTkToplevel(win)
                hwin.title(f"Historial Trigger #{trigger_id}")
                hwin.geometry("700x360")
                hwin.configure(fg_color=PANEL)
                box = ctk.CTkTextbox(hwin, fg_color="#080808", border_color=BORDER, border_width=1, text_color=TEXT)
                box.pack(fill="both", expand=True, padx=12, pady=12)
                rows = self.orchestrator.triggers.list_trigger_runs(int(trigger_id), limit=60)
                if not rows:
                    box.insert("end", "No hay historial para este trigger.")
                    box.configure(state="disabled")
                    return
                for row in rows:
                    box.insert(
                        "end",
                        f"{row['created_at']} | {row['status']} | {row['source']} | {str(row['detail'])[:140]}\n",
                    )
                box.configure(state="disabled")

            row = ctk.CTkFrame(win, fg_color=PANEL)
            row.pack(fill="x", padx=12, pady=(0, 12))
            ctk.CTkButton(row, text="Refresh", command=refresh).pack(side="left", padx=4)
            ctk.CTkButton(
                row,
                text="Activar todos",
                command=lambda: self.submit_command("activar todos los disparadores", display_user="activar todos"),
            ).pack(side="left", padx=4)
            ctk.CTkButton(
                row,
                text="Desactivar todos",
                command=lambda: self.submit_command("desactivar todos los disparadores", display_user="desactivar todos"),
            ).pack(side="left", padx=4)
            refresh()

        def open_trigger_wizard(self) -> None:
            win = ctk.CTkToplevel(self)
            win.title("Asistente de Trigger")
            win.geometry("560x360")
            win.configure(fg_color=PANEL)
            phrase_var = tk.StringVar(value="")
            action_var = tk.StringVar(value="play_spotify")
            payload_var = tk.StringVar(value='{"query": ""}')
            confirm_var = tk.BooleanVar(value=True)
            ctk.CTkLabel(win, text="Frase disparadora").pack(anchor="w", padx=12, pady=(12, 4))
            ctk.CTkEntry(win, textvariable=phrase_var).pack(fill="x", padx=12)
            ctk.CTkLabel(win, text="Acción").pack(anchor="w", padx=12, pady=(10, 4))
            ctk.CTkOptionMenu(win, variable=action_var, values=["play_spotify", "open_app", "open_website", "speak"]).pack(
                fill="x", padx=12
            )
            ctk.CTkLabel(win, text="Payload (JSON)").pack(anchor="w", padx=12, pady=(10, 4))
            ctk.CTkEntry(win, textvariable=payload_var).pack(fill="x", padx=12)
            ctk.CTkCheckBox(win, text="Requiere confirmación", variable=confirm_var).pack(anchor="w", padx=12, pady=(10, 10))

            def _save_wizard() -> None:
                phrase = str(phrase_var.get() or "").strip()
                if not phrase:
                    self.append_assistant_bubble("Escribe una frase para el trigger.")
                    return
                try:
                    payload = json.loads(str(payload_var.get() or "{}"))
                    if not isinstance(payload, dict):
                        payload = {}
                except Exception:
                    self.append_assistant_bubble("Payload inválido: usa JSON objeto.")
                    return
                tid = self.orchestrator.triggers.create_trigger(
                    phrase=phrase,
                    match_type="fuzzy",
                    action_type=str(action_var.get() or "play_spotify"),
                    action_payload=payload,
                    require_confirm=bool(confirm_var.get()),
                )
                if tid <= 0:
                    self.append_assistant_bubble("No pude crear el trigger.")
                    return
                self.append_assistant_bubble(f"Trigger creado (id={tid}) para '{phrase}'.")
                win.destroy()

            ctk.CTkButton(win, text="Crear Trigger", command=_save_wizard).pack(anchor="e", padx=12, pady=(0, 12))

        def open_profile_panel(self) -> None:
            win = ctk.CTkToplevel(self)
            win.title("Perfil de Usuario")
            win.geometry("620x420")
            win.configure(fg_color=PANEL)
            profile = self.memory.get_user_profile()
            facts = profile.get("facts", {}) if isinstance(profile.get("facts"), dict) else {}
            name_var = tk.StringVar(value=str(profile.get("name", "Eric")))
            role_var = tk.StringVar(value=str(facts.get("role", "")))
            location_var = tk.StringVar(value=str(facts.get("location", "")))
            prefs_var = tk.StringVar(value=json.dumps(self.memory.get_user_preferences(), ensure_ascii=False))
            ctk.CTkLabel(win, text="Nombre").pack(anchor="w", padx=12, pady=(12, 4))
            ctk.CTkEntry(win, textvariable=name_var).pack(fill="x", padx=12)
            ctk.CTkLabel(win, text="Rol").pack(anchor="w", padx=12, pady=(10, 4))
            ctk.CTkEntry(win, textvariable=role_var).pack(fill="x", padx=12)
            ctk.CTkLabel(win, text="Ubicación").pack(anchor="w", padx=12, pady=(10, 4))
            ctk.CTkEntry(win, textvariable=location_var).pack(fill="x", padx=12)
            ctk.CTkLabel(win, text="Preferencias (JSON clave/valor)").pack(anchor="w", padx=12, pady=(10, 4))
            ctk.CTkEntry(win, textvariable=prefs_var).pack(fill="x", padx=12)

            def _save_profile() -> None:
                profile_now = self.memory.get_user_profile()
                fact_map = profile_now.get("facts", {}) if isinstance(profile_now.get("facts"), dict) else {}
                fact_map["role"] = str(role_var.get() or "").strip()
                fact_map["location"] = str(location_var.get() or "").strip()
                self.memory.save_user_profile(
                    {
                        "name": str(name_var.get() or "Eric").strip() or "Eric",
                        "traits": profile_now.get("traits", []),
                        "facts": fact_map,
                    }
                )
                try:
                    prefs = json.loads(str(prefs_var.get() or "{}"))
                    if isinstance(prefs, dict):
                        for k, v in prefs.items():
                            self.memory.set_user_preference(str(k), str(v))
                except Exception:
                    self.append_assistant_bubble("Preferencias no actualizadas: JSON inválido.")
                    return
                self.append_assistant_bubble("Perfil actualizado.")
                win.destroy()

            ctk.CTkButton(win, text="Guardar Perfil", command=_save_profile).pack(anchor="e", padx=12, pady=(12, 12))

        def open_backup_center(self) -> None:
            win = ctk.CTkToplevel(self)
            win.title("Centro de Backups")
            win.geometry("760x560")
            win.configure(fg_color=PANEL)
            list_box = ctk.CTkTextbox(win, fg_color="#080808", border_color=BORDER, border_width=1, text_color=TEXT)
            list_box.pack(fill="both", expand=True, padx=12, pady=(12, 6))
            mem_box = ctk.CTkTextbox(win, fg_color="#080808", border_color=BORDER, border_width=1, text_color=TEXT, height=160)
            mem_box.pack(fill="x", padx=12, pady=(0, 8))
            selected = {"path": None}

            def refresh() -> None:
                list_box.configure(state="normal")
                list_box.delete("1.0", "end")
                backups = self.list_backup_snapshots()
                if not backups:
                    list_box.insert("end", "No hay backups todavía.\n")
                for i, p in enumerate(backups[:100], start=1):
                    list_box.insert("end", f"{i}. {p.name}\n")
                list_box.insert("end", "\nSelecciona por número con el botón 'Usar #'.")
                list_box.configure(state="disabled")
                mem_box.configure(state="normal")
                mem_box.delete("1.0", "end")
                snaps = self.memory.list_memory_snapshots(limit=50)
                if not snaps:
                    mem_box.insert("end", "No hay snapshots de memoria.\n")
                for i, p in enumerate(snaps, start=1):
                    mem_box.insert("end", f"{i}. {p.name}\n")
                mem_box.insert("end", "\nCompara: A vs B. Restaura: índice + sección.")
                mem_box.configure(state="disabled")

            idx_var = tk.StringVar(value="1")

            def use_index() -> None:
                try:
                    idx = int(idx_var.get())
                    backups = self.list_backup_snapshots()
                    selected["path"] = backups[idx - 1]
                    self.append_assistant_bubble(f"Backup seleccionado: {backups[idx - 1].name}")
                except Exception:
                    self.append_assistant_bubble("Índice de backup inválido.")

            def restore_selected() -> None:
                chosen = selected.get("path")
                if not chosen:
                    self.append_assistant_bubble("Primero selecciona un backup.")
                    return
                ok, msg = self.restore_backup_snapshot(Path(str(chosen)))
                self.append_assistant_bubble(msg)
                self.append_log_line("BACKUP", msg)

            mem_idx_var = tk.StringVar(value="1")
            cmp_a_var = tk.StringVar(value="1")
            cmp_b_var = tk.StringVar(value="2")
            section_var = tk.StringVar(value="todo")

            def create_mem_snapshot() -> None:
                snap = self.memory.create_memory_snapshot("ui")
                self.append_assistant_bubble(f"Snapshot memoria: {snap}" if snap else "No pude crear snapshot de memoria.")
                refresh()

            def restore_mem_snapshot() -> None:
                snaps = self.memory.list_memory_snapshots(limit=50)
                try:
                    idx = int(mem_idx_var.get()) - 1
                    if idx < 0 or idx >= len(snaps):
                        raise ValueError
                except Exception:
                    self.append_assistant_bubble("Índice de snapshot inválido.")
                    return
                sec = str(section_var.get() or "todo").strip().lower()
                sections = {"memory", "profile", "db"}
                if sec == "perfil":
                    sections = {"profile"}
                elif sec == "memoria":
                    sections = {"memory"}
                elif sec == "db":
                    sections = {"db"}
                ok = self.memory.restore_memory_snapshot(snaps[idx], sections=sections)
                self.append_assistant_bubble(
                    f"Snapshot restaurado ({','.join(sorted(sections))})." if ok else "No pude restaurar snapshot."
                )

            def compare_mem_snapshots() -> None:
                snaps = self.memory.list_memory_snapshots(limit=50)
                try:
                    a = int(cmp_a_var.get()) - 1
                    b = int(cmp_b_var.get()) - 1
                    if a < 0 or b < 0 or a >= len(snaps) or b >= len(snaps) or a == b:
                        raise ValueError
                except Exception:
                    self.append_assistant_bubble("Índices inválidos para comparar snapshots.")
                    return
                cmp = self.memory.compare_memory_snapshots(snaps[a], snaps[b])
                if not cmp.get("ok"):
                    self.append_assistant_bubble("No pude comparar snapshots.")
                    return
                if cmp.get("same"):
                    self.append_assistant_bubble("Snapshots idénticos.")
                    return
                parts = []
                if cmp.get("added"):
                    parts.append("Agregados: " + ", ".join(cmp["added"]))
                if cmp.get("removed"):
                    parts.append("Eliminados: " + ", ".join(cmp["removed"]))
                if cmp.get("changed"):
                    parts.append("Cambiados: " + ", ".join(cmp["changed"]))
                self.append_assistant_bubble(" | ".join(parts) if parts else "Sin diferencias relevantes.")

            row = ctk.CTkFrame(win, fg_color=PANEL)
            row.pack(fill="x", padx=12, pady=(0, 12))
            ctk.CTkButton(row, text="Refrescar", command=refresh).pack(side="left", padx=4)
            ctk.CTkEntry(row, textvariable=idx_var, width=80).pack(side="left", padx=4)
            ctk.CTkButton(row, text="Usar #", command=use_index).pack(side="left", padx=4)
            ctk.CTkButton(row, text="Restaurar", command=restore_selected).pack(side="left", padx=4)
            ctk.CTkButton(
                row,
                text="Crear backup",
                command=lambda: self.append_assistant_bubble(f"Backup creado: {self.export_backup_snapshot()}"),
            ).pack(side="left", padx=4)
            ctk.CTkButton(row, text="Snapshot Memoria", command=create_mem_snapshot).pack(side="left", padx=4)
            ctk.CTkEntry(row, textvariable=mem_idx_var, width=56).pack(side="left", padx=4)
            ctk.CTkOptionMenu(row, variable=section_var, values=["todo", "perfil", "memoria", "db"], width=110).pack(
                side="left", padx=4
            )
            ctk.CTkButton(row, text="Restaurar Snap", command=restore_mem_snapshot).pack(side="left", padx=4)

            cmp_row = ctk.CTkFrame(win, fg_color=PANEL)
            cmp_row.pack(fill="x", padx=12, pady=(0, 12))
            ctk.CTkLabel(cmp_row, text="Comparar snapshots").pack(side="left", padx=4)
            ctk.CTkEntry(cmp_row, textvariable=cmp_a_var, width=56).pack(side="left", padx=4)
            ctk.CTkLabel(cmp_row, text="vs").pack(side="left", padx=2)
            ctk.CTkEntry(cmp_row, textvariable=cmp_b_var, width=56).pack(side="left", padx=4)
            ctk.CTkButton(cmp_row, text="Comparar", command=compare_mem_snapshots).pack(side="left", padx=6)
            refresh()

        def _set_listen_state_visual(self, state: str, confidence: float) -> None:
            palette = {
                "idle": ("● OFF", MUTED),
                "wait_wakeword": ("● WAKE", "#f6c343"),
                "post_activation": ("● ESCUCHANDO", HEALTH),
                "processing": ("● PROCESS", ACCENT),
            }
            label, color = palette.get(state, ("● OFF", MUTED))
            self.listen_state_label.configure(text=f"{label} {confidence:.2f}", text_color=color)
    
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

    def render_youtube_candidates(self, candidates: list[dict[str, Any]]) -> None:
        for w in self.yt_candidates_frame.winfo_children():
            w.destroy()
        for i, cand in enumerate(candidates[:5]):
            row = tk.Frame(self.yt_candidates_frame, bg="#0a0a0a", highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x", padx=4, pady=3)
            title = str(cand.get("title", "video")).strip()
            channel = str(cand.get("channel", "canal")).strip()
            thumb = str(cand.get("thumbnail", "")).strip()
            tk.Label(
                row,
                text=f"{i+1}) {title}\nCanal: {channel}\nThumb: {thumb[:70]}",
                bg="#0a0a0a",
                fg=TEXT,
                justify="left",
                wraplength=220,
            ).pack(side="left", padx=6, pady=4, fill="x", expand=True)
            tk.Button(row, text="Abrir", command=lambda idx=i + 1: self.submit_command(str(idx), display_user=f"Abrir YouTube #{idx}")).pack(side="right", padx=6)

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

        self.continuous_var = tk.BooleanVar(value=False)
        self.listen_state_label = tk.Label(input_row, text="● OFF", fg=MUTED, bg=BG, font=("Consolas", 10, "bold"))
        self.listen_state_label.pack(side="left", padx=(8, 4))
        tk.Checkbutton(
            input_row,
            text="Escucha continua",
            variable=self.continuous_var,
            command=lambda: self.toggle_continuous_listening(bool(self.continuous_var.get())),
            bg=BG,
            fg=TEXT,
            selectcolor="#222",
        ).pack(side="left")
        self.push_to_talk_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            input_row,
            text="Push-to-talk",
            variable=self.push_to_talk_var,
            command=lambda: setattr(self, "push_to_talk_enabled", bool(self.push_to_talk_var.get())),
            bg=BG,
            fg=TEXT,
            selectcolor="#222",
        ).pack(side="left")
        self.mic_btn.bind("<ButtonPress-1>", lambda _e: self._push_to_talk_start())
        self.mic_btn.bind("<ButtonRelease-1>", lambda _e: self._push_to_talk_stop())

        tk.Label(right, text="RECURSOS", fg=MUTED, bg=PANEL, font=("Consolas", 11, "bold")).pack(anchor="w", padx=10, pady=(12, 6))
        self.cpu_label = tk.Label(right, text="CPU 0%", fg=ACCENT, bg=PANEL, font=("Consolas", 11))
        self.cpu_label.pack(anchor="w", padx=10)
        self.cpu_bar = ttk.Progressbar(right, maximum=100, length=260)
        self.cpu_bar.pack(fill="x", padx=10, pady=(0, 8))

        self.ram_label = tk.Label(right, text="RAM", fg=HEALTH, bg=PANEL, font=("Consolas", 11))
        self.ram_label.pack(anchor="w", padx=10)
        self.ram_bar = ttk.Progressbar(right, maximum=100, length=260)
        self.ram_bar.pack(fill="x", padx=10, pady=(0, 12))

        tk.Label(right, text="SETTINGS > YOUTUBE", fg=MUTED, bg=PANEL, font=("Consolas", 11, "bold")).pack(anchor="w", padx=10, pady=(4, 4))
        self.yt_auto_open_var = tk.BooleanVar(value=os.getenv("YOUTUBE_AUTO_OPEN", "false").lower() in {"1", "true", "yes", "on"})

        def _toggle_yt_auto_open() -> None:
            self.orchestrator.set_youtube_auto_open(bool(self.yt_auto_open_var.get()))
            self.append_log_line("YOUTUBE", f"Auto-open {'ON' if self.yt_auto_open_var.get() else 'OFF'}")

        tk.Checkbutton(
            right,
            text="Auto-open top result",
            variable=self.yt_auto_open_var,
            command=_toggle_yt_auto_open,
            bg=PANEL,
            fg=TEXT,
            selectcolor="#222222",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        tk.Label(right, text="SETTINGS > VOZ", fg=MUTED, bg=PANEL, font=("Consolas", 11, "bold")).pack(anchor="w", padx=10, pady=(4, 4))
        self.tts_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            right,
            text="Voz en respuestas",
            variable=self.tts_enabled_var,
            command=lambda: self.set_tts_enabled(bool(self.tts_enabled_var.get())),
            bg=PANEL,
            fg=TEXT,
            selectcolor="#222",
        ).pack(anchor="w", padx=10, pady=(0, 4))
        self.wake_word_var = tk.StringVar(value=self.continuous_wake_word)
        tk.Entry(right, textvariable=self.wake_word_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(anchor="w", padx=10, pady=(0, 4))
        self.post_window_var = tk.StringVar(value=str(self.continuous_post_window))
        tk.Entry(right, textvariable=self.post_window_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(anchor="w", padx=10, pady=(0, 6))
        self.tts_rate_var = tk.StringVar(value="175")
        tk.Entry(right, textvariable=self.tts_rate_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(anchor="w", padx=10, pady=(0, 6))
        self.conv_style_var = tk.StringVar(value=str(getattr(self.core, "conversation_style", "neutral")))
        tk.OptionMenu(right, self.conv_style_var, "neutral", "formal", "cercano", "breve").pack(anchor="w", padx=10, pady=(0, 6))
        self.spotify_official_var = tk.BooleanVar(value=bool(getattr(eda_config, "EDA_SPOTIFY_PREFER_OFFICIAL", True)))
        tk.Checkbutton(
            right,
            text="Spotify: preferir versión oficial",
            variable=self.spotify_official_var,
            bg=PANEL,
            fg=TEXT,
            selectcolor="#222",
        ).pack(anchor="w", padx=10, pady=(0, 6))

        def _apply_voice_settings() -> None:
            self.continuous_wake_word = (self.wake_word_var.get() or "eda").strip() or "eda"
            try:
                self.continuous_post_window = max(2.0, min(12.0, float(self.post_window_var.get())))
            except Exception:
                self.continuous_post_window = 5.0
            try:
                self.set_tts_rate(int(float(self.tts_rate_var.get())))
            except Exception:
                self.set_tts_rate(175)
            style = str(self.conv_style_var.get() or "neutral")
            setter = getattr(self.core, "set_conversation_style", None)
            if callable(setter):
                style = setter(style)
            eda_config.EDA_CONVERSATION_STYLE = style
            eda_config.EDA_SPOTIFY_PREFER_OFFICIAL = bool(self.spotify_official_var.get())
            self.append_log_line("AI", f"Estilo conversación: {style}")
            self.append_log_line("SPOTIFY", f"Versión oficial {'ON' if bool(self.spotify_official_var.get()) else 'OFF'}")

        tk.Button(right, text="Aplicar voz", command=_apply_voice_settings, bg="#121212", fg=TEXT).pack(anchor="w", padx=10, pady=(0, 8))

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
        self._tk_quick(qf, 3, 0, "Borrar Trigger", "borrar disparador")
        self._tk_quick(qf, 3, 1, "Desactivar Trigger", "desactivar disparador")
        self._tk_quick(qf, 4, 0, "Diagnóstico", "diagnóstico de salud")
        self._tk_quick(qf, 4, 1, "Panel Triggers", "__open_trigger_panel__")
        self._tk_quick(qf, 5, 0, "Backup", "__backup_snapshot__")
        self._tk_quick(qf, 5, 1, "Asistente Trigger", "__open_trigger_wizard__")
        self._tk_quick(qf, 6, 0, "Perfil Usuario", "__open_profile_panel__")
        self._tk_quick(qf, 6, 1, "Centro Backups", "__open_backup_center__")
        self._tk_quick(qf, 7, 0, "Diag Avanzado", "__diag_export__")

        tk.Label(right, text="ÚLTIMOS LOGS", fg=MUTED, bg=PANEL, font=("Consolas", 11, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        self.log_box = tk.Text(right, height=10, bg="#080808", fg=MUTED, font=("Consolas", 10), state="disabled")
        self.log_box.pack(fill="both", expand=False, padx=10, pady=(0, 12))
        self.trace_label = tk.Label(right, text="TRACE: Sin trazas", fg=MUTED, bg=PANEL, font=("Consolas", 9), wraplength=260, justify="left")
        self.trace_label.pack(anchor="w", padx=10, pady=(0, 8))

        tk.Label(right, text="YOUTUBE RESULTADOS", fg=MUTED, bg=PANEL, font=("Consolas", 11, "bold")).pack(anchor="w", padx=10, pady=(2, 4))
        self.yt_candidates_frame = tk.Frame(right, bg="#080808", highlightbackground=BORDER, highlightthickness=1)
        self.yt_candidates_frame.pack(fill="x", padx=10, pady=(0, 12))

    def _tk_quick(self, parent: tk.Frame, r: int, c: int, label: str, cmd: str, *, highlight: bool = False) -> tk.Button:
        btn = tk.Button(
            parent,
            text=label,
            command=lambda: self._dispatch_quick_action(cmd, label),
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

    def _dispatch_quick_action(self, cmd: str, label: str) -> None:
        if cmd == "__open_trigger_panel__":
            self.open_trigger_panel()
            return
        if cmd == "__backup_snapshot__":
            path = self.export_backup_snapshot()
            self.append_assistant_bubble(f"Backup creado: {path}")
            self.append_log_line("BACKUP", path)
            return
        if cmd == "__open_trigger_wizard__":
            self.open_trigger_wizard()
            return
        if cmd == "__open_profile_panel__":
            self.open_profile_panel()
            return
        if cmd == "__open_backup_center__":
            self.open_backup_center()
            return
        if cmd == "__diag_export__":
            json_path, txt_path = self.export_advanced_diagnostic()
            self.append_assistant_bubble(f"Diagnóstico exportado: {json_path} | {txt_path}")
            self.append_log_line("HEALTH", f"Diagnóstico avanzado: {json_path.name}")
            return
        self.submit_command(cmd, display_user=label)

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
        if self.push_to_talk_enabled:
            return
        self.listen_mic()

    def update_trace(self, text: str) -> None:
        self.trace_label.configure(text=f"TRACE: {text[:120]}")

    def open_trigger_panel(self) -> None:
        win = tk.Toplevel(self)
        win.title("Panel de Triggers")
        win.configure(bg=PANEL)
        win.geometry("760x520")
        container = tk.Frame(win, bg="#080808", highlightbackground=BORDER, highlightthickness=1)
        container.pack(fill="both", expand=True, padx=10, pady=(10, 8))
        canvas = tk.Canvas(container, bg="#080808", highlightthickness=0)
        scroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        rows_frame = tk.Frame(canvas, bg="#080808")
        rows_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=rows_frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        def refresh() -> None:
            for w in rows_frame.winfo_children():
                w.destroy()
            rows = self.orchestrator.triggers.list_triggers(active_only=False)
            run_map = self.orchestrator.triggers.get_last_run_map()
            if not rows:
                tk.Label(rows_frame, text="No hay triggers.", bg="#080808", fg=MUTED).pack(anchor="w", padx=8, pady=8)
                return
            for r in rows[:120]:
                line = tk.Frame(rows_frame, bg="#111111", highlightbackground=BORDER, highlightthickness=1)
                line.pack(fill="x", padx=6, pady=4)
                status = "ON" if r.get("active") else "OFF"
                last = run_map.get(int(r.get("id", 0)))
                last_line = ""
                if last:
                    last_line = f"\nÚltimo: {last.get('status')} ({last.get('created_at')})"
                tk.Label(
                    line,
                    text=f"#{r['id']} [{status}] {r['phrase']} -> {r['action_type']}{last_line}",
                    bg="#111111",
                    fg=TEXT,
                    justify="left",
                    wraplength=430,
                ).pack(side="left", fill="x", expand=True, padx=8, pady=5)
                tk.Button(line, text="Activar", command=lambda tid=r["id"]: self.submit_command(f"activar disparador {tid}", display_user=f"activar {tid}")).pack(side="left", padx=3)
                tk.Button(line, text="Desactivar", command=lambda tid=r["id"]: self.submit_command(f"desactivar disparador {tid}", display_user=f"desactivar {tid}")).pack(side="left", padx=3)
                tk.Button(line, text="Borrar", command=lambda tid=r["id"]: self.submit_command(f"borrar disparador {tid}", display_user=f"borrar {tid}")).pack(side="left", padx=3)
                tk.Button(line, text="Editar", command=lambda tr=r: open_edit_modal(tr)).pack(side="left", padx=3)
                tk.Button(line, text="Historial", command=lambda tid=r["id"]: open_history_modal(int(tid))).pack(side="left", padx=3)

        def open_edit_modal(trigger_row: dict[str, Any]) -> None:
            edit = tk.Toplevel(win)
            edit.title(f"Editar Trigger #{trigger_row.get('id')}")
            edit.configure(bg=PANEL)
            phrase_var = tk.StringVar(value=str(trigger_row.get("phrase", "")))
            action_var = tk.StringVar(value=str(trigger_row.get("action_type", "")))
            payload_var = tk.StringVar(value=json.dumps(trigger_row.get("action_payload", {}), ensure_ascii=False))
            req_var = tk.BooleanVar(value=bool(trigger_row.get("require_confirm", True)))
            tk.Label(edit, text="Frase", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(10, 4))
            tk.Entry(edit, textvariable=phrase_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)
            tk.Label(edit, text="Acción (action_type)", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(8, 4))
            tk.Entry(edit, textvariable=action_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)
            tk.Label(edit, text="Payload JSON", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(8, 4))
            tk.Entry(edit, textvariable=payload_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)
            tk.Checkbutton(edit, text="Requiere confirmación", variable=req_var, bg=PANEL, fg=TEXT, selectcolor="#222").pack(anchor="w", padx=10, pady=(8, 10))

            def _save_edit() -> None:
                try:
                    payload = json.loads(str(payload_var.get() or "{}"))
                    if not isinstance(payload, dict):
                        payload = {}
                except Exception:
                    self.append_assistant_bubble("Payload inválido: use JSON objeto.")
                    return
                ok = self.orchestrator.triggers.update_trigger(
                    int(trigger_row.get("id", 0)),
                    phrase=str(phrase_var.get() or ""),
                    action_type=str(action_var.get() or ""),
                    action_payload=payload,
                    require_confirm=bool(req_var.get()),
                    match_type=str(trigger_row.get("match_type", "fuzzy")),
                    fuzzy_threshold=float(trigger_row.get("fuzzy_threshold", 80.0)),
                )
                if ok:
                    self.append_assistant_bubble(f"Trigger #{trigger_row.get('id')} actualizado.")
                    refresh()
                    edit.destroy()
                else:
                    self.append_assistant_bubble("No pude actualizar el trigger.")

            tk.Button(edit, text="Guardar", command=_save_edit).pack(anchor="e", padx=10, pady=(0, 10))

        def open_history_modal(trigger_id: int) -> None:
            hwin = tk.Toplevel(win)
            hwin.title(f"Historial Trigger #{trigger_id}")
            hwin.configure(bg=PANEL)
            box = tk.Text(hwin, bg="#080808", fg=TEXT, height=16)
            box.pack(fill="both", expand=True, padx=10, pady=10)
            rows = self.orchestrator.triggers.list_trigger_runs(int(trigger_id), limit=60)
            if not rows:
                box.insert("end", "No hay historial para este trigger.")
            else:
                for row in rows:
                    box.insert(
                        "end",
                        f"{row['created_at']} | {row['status']} | {row['source']} | {str(row['detail'])[:140]}\n",
                    )
            box.configure(state="disabled")

        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(row, text="Refresh", command=refresh).pack(side="left", padx=3)
        tk.Button(
            row,
            text="Activar todos",
            command=lambda: self.submit_command("activar todos los disparadores", display_user="activar todos"),
        ).pack(side="left", padx=3)
        tk.Button(
            row,
            text="Desactivar todos",
            command=lambda: self.submit_command("desactivar todos los disparadores", display_user="desactivar todos"),
        ).pack(side="left", padx=3)
        refresh()

    def open_trigger_wizard(self) -> None:
        win = tk.Toplevel(self)
        win.title("Asistente de Trigger")
        win.configure(bg=PANEL)
        phrase_var = tk.StringVar(value="")
        action_var = tk.StringVar(value="play_spotify")
        payload_var = tk.StringVar(value='{"query": ""}')
        req_var = tk.BooleanVar(value=True)
        tk.Label(win, text="Frase disparadora", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(10, 4))
        tk.Entry(win, textvariable=phrase_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)
        tk.Label(win, text="Acción", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(8, 4))
        tk.OptionMenu(win, action_var, "play_spotify", "open_app", "open_website", "speak").pack(fill="x", padx=10)
        tk.Label(win, text="Payload JSON", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(8, 4))
        tk.Entry(win, textvariable=payload_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)
        tk.Checkbutton(win, text="Requiere confirmación", variable=req_var, bg=PANEL, fg=TEXT, selectcolor="#222").pack(
            anchor="w", padx=10, pady=(8, 10)
        )

        def _create() -> None:
            phrase = str(phrase_var.get() or "").strip()
            if not phrase:
                self.append_assistant_bubble("Escribe una frase para el trigger.")
                return
            try:
                payload = json.loads(str(payload_var.get() or "{}"))
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:
                self.append_assistant_bubble("Payload inválido: use JSON objeto.")
                return
            tid = self.orchestrator.triggers.create_trigger(
                phrase=phrase,
                match_type="fuzzy",
                action_type=str(action_var.get() or "play_spotify"),
                action_payload=payload,
                require_confirm=bool(req_var.get()),
            )
            if tid <= 0:
                self.append_assistant_bubble("No pude crear el trigger.")
                return
            self.append_assistant_bubble(f"Trigger creado (id={tid}) para '{phrase}'.")
            win.destroy()

        tk.Button(win, text="Crear Trigger", command=_create).pack(anchor="e", padx=10, pady=(0, 10))

    def open_profile_panel(self) -> None:
        win = tk.Toplevel(self)
        win.title("Perfil de Usuario")
        win.configure(bg=PANEL)
        profile = self.memory.get_user_profile()
        facts = profile.get("facts", {}) if isinstance(profile.get("facts"), dict) else {}
        name_var = tk.StringVar(value=str(profile.get("name", "Eric")))
        role_var = tk.StringVar(value=str(facts.get("role", "")))
        location_var = tk.StringVar(value=str(facts.get("location", "")))
        prefs_var = tk.StringVar(value=json.dumps(self.memory.get_user_preferences(), ensure_ascii=False))
        tk.Label(win, text="Nombre", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(10, 4))
        tk.Entry(win, textvariable=name_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)
        tk.Label(win, text="Rol", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(8, 4))
        tk.Entry(win, textvariable=role_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)
        tk.Label(win, text="Ubicación", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(8, 4))
        tk.Entry(win, textvariable=location_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)
        tk.Label(win, text="Preferencias (JSON)", bg=PANEL, fg=TEXT).pack(anchor="w", padx=10, pady=(8, 4))
        tk.Entry(win, textvariable=prefs_var, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(fill="x", padx=10)

        def _save() -> None:
            profile_now = self.memory.get_user_profile()
            fact_map = profile_now.get("facts", {}) if isinstance(profile_now.get("facts"), dict) else {}
            fact_map["role"] = str(role_var.get() or "").strip()
            fact_map["location"] = str(location_var.get() or "").strip()
            self.memory.save_user_profile(
                {
                    "name": str(name_var.get() or "Eric").strip() or "Eric",
                    "traits": profile_now.get("traits", []),
                    "facts": fact_map,
                }
            )
            try:
                prefs = json.loads(str(prefs_var.get() or "{}"))
                if isinstance(prefs, dict):
                    for k, v in prefs.items():
                        self.memory.set_user_preference(str(k), str(v))
            except Exception:
                self.append_assistant_bubble("Preferencias no actualizadas: JSON inválido.")
                return
            self.append_assistant_bubble("Perfil actualizado.")
            win.destroy()

        tk.Button(win, text="Guardar Perfil", command=_save).pack(anchor="e", padx=10, pady=(10, 10))

    def open_backup_center(self) -> None:
        win = tk.Toplevel(self)
        win.title("Centro de Backups")
        win.configure(bg=PANEL)
        list_box = tk.Text(win, bg="#080808", fg=TEXT, height=10)
        list_box.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        mem_box = tk.Text(win, bg="#080808", fg=TEXT, height=8)
        mem_box.pack(fill="x", padx=10, pady=(0, 8))
        selected: dict[str, Path | None] = {"path": None}

        def refresh() -> None:
            list_box.configure(state="normal")
            list_box.delete("1.0", "end")
            backups = self.list_backup_snapshots()
            if not backups:
                list_box.insert("end", "No hay backups todavía.\n")
            for i, p in enumerate(backups[:100], start=1):
                list_box.insert("end", f"{i}. {p.name}\n")
            list_box.insert("end", "\nSelecciona por número y pulsa 'Usar #'.")
            list_box.configure(state="disabled")
            mem_box.configure(state="normal")
            mem_box.delete("1.0", "end")
            snaps = self.memory.list_memory_snapshots(limit=50)
            if not snaps:
                mem_box.insert("end", "No hay snapshots de memoria.\n")
            for i, p in enumerate(snaps, start=1):
                mem_box.insert("end", f"{i}. {p.name}\n")
            mem_box.insert("end", "\nCompara: A vs B. Restaura: índice + sección.")
            mem_box.configure(state="disabled")

        idx_var = tk.StringVar(value="1")

        def use_index() -> None:
            try:
                idx = int(idx_var.get())
                backups = self.list_backup_snapshots()
                selected["path"] = backups[idx - 1]
                self.append_assistant_bubble(f"Backup seleccionado: {backups[idx - 1].name}")
            except Exception:
                self.append_assistant_bubble("Índice de backup inválido.")

        def restore_selected() -> None:
            chosen = selected.get("path")
            if not chosen:
                self.append_assistant_bubble("Primero selecciona un backup.")
                return
            ok, msg = self.restore_backup_snapshot(Path(chosen))
            self.append_assistant_bubble(msg)
            self.append_log_line("BACKUP", msg)

        mem_idx_var = tk.StringVar(value="1")
        cmp_a_var = tk.StringVar(value="1")
        cmp_b_var = tk.StringVar(value="2")
        section_var = tk.StringVar(value="todo")

        def create_mem_snapshot() -> None:
            snap = self.memory.create_memory_snapshot("ui")
            self.append_assistant_bubble(f"Snapshot memoria: {snap}" if snap else "No pude crear snapshot de memoria.")
            refresh()

        def restore_mem_snapshot() -> None:
            snaps = self.memory.list_memory_snapshots(limit=50)
            try:
                idx = int(mem_idx_var.get()) - 1
                if idx < 0 or idx >= len(snaps):
                    raise ValueError
            except Exception:
                self.append_assistant_bubble("Índice de snapshot inválido.")
                return
            sec = str(section_var.get() or "todo").strip().lower()
            sections = {"memory", "profile", "db"}
            if sec == "perfil":
                sections = {"profile"}
            elif sec == "memoria":
                sections = {"memory"}
            elif sec == "db":
                sections = {"db"}
            ok = self.memory.restore_memory_snapshot(snaps[idx], sections=sections)
            self.append_assistant_bubble(
                f"Snapshot restaurado ({','.join(sorted(sections))})." if ok else "No pude restaurar snapshot."
            )

        def compare_mem_snapshots() -> None:
            snaps = self.memory.list_memory_snapshots(limit=50)
            try:
                a = int(cmp_a_var.get()) - 1
                b = int(cmp_b_var.get()) - 1
                if a < 0 or b < 0 or a >= len(snaps) or b >= len(snaps) or a == b:
                    raise ValueError
            except Exception:
                self.append_assistant_bubble("Índices inválidos para comparar snapshots.")
                return
            cmp = self.memory.compare_memory_snapshots(snaps[a], snaps[b])
            if not cmp.get("ok"):
                self.append_assistant_bubble("No pude comparar snapshots.")
                return
            if cmp.get("same"):
                self.append_assistant_bubble("Snapshots idénticos.")
                return
            parts = []
            if cmp.get("added"):
                parts.append("Agregados: " + ", ".join(cmp["added"]))
            if cmp.get("removed"):
                parts.append("Eliminados: " + ", ".join(cmp["removed"]))
            if cmp.get("changed"):
                parts.append("Cambiados: " + ", ".join(cmp["changed"]))
            self.append_assistant_bubble(" | ".join(parts) if parts else "Sin diferencias relevantes.")

        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(row, text="Refrescar", command=refresh).pack(side="left", padx=3)
        tk.Entry(row, textvariable=idx_var, width=6, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(side="left", padx=3)
        tk.Button(row, text="Usar #", command=use_index).pack(side="left", padx=3)
        tk.Button(row, text="Restaurar", command=restore_selected).pack(side="left", padx=3)
        tk.Button(
            row,
            text="Crear backup",
            command=lambda: self.append_assistant_bubble(f"Backup creado: {self.export_backup_snapshot()}"),
        ).pack(side="left", padx=3)
        tk.Button(row, text="Snapshot Memoria", command=create_mem_snapshot).pack(side="left", padx=3)
        tk.Entry(row, textvariable=mem_idx_var, width=5, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(side="left", padx=3)
        tk.OptionMenu(row, section_var, "todo", "perfil", "memoria", "db").pack(side="left", padx=3)
        tk.Button(row, text="Restaurar Snap", command=restore_mem_snapshot).pack(side="left", padx=3)

        cmp_row = tk.Frame(win, bg=PANEL)
        cmp_row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(cmp_row, text="Comparar snapshots", bg=PANEL, fg=TEXT).pack(side="left", padx=3)
        tk.Entry(cmp_row, textvariable=cmp_a_var, width=5, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(side="left", padx=3)
        tk.Label(cmp_row, text="vs", bg=PANEL, fg=TEXT).pack(side="left", padx=2)
        tk.Entry(cmp_row, textvariable=cmp_b_var, width=5, bg="#0a0a0a", fg=TEXT, insertbackground=TEXT).pack(side="left", padx=3)
        tk.Button(cmp_row, text="Comparar", command=compare_mem_snapshots).pack(side="left", padx=4)
        refresh()

    def _set_listen_state_visual(self, state: str, confidence: float) -> None:
        palette = {
            "idle": ("● OFF", MUTED),
            "wait_wakeword": ("● WAKE", "#f6c343"),
            "post_activation": ("● ESCUCHANDO", HEALTH),
            "processing": ("● PROCESS", ACCENT),
        }
        label, color = palette.get(state, ("● OFF", MUTED))
        self.listen_state_label.configure(text=f"{label} {confidence:.2f}", fg=color)

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
