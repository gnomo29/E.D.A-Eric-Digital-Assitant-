"""Orquestador unificado de comandos para las interfaces de E.D.A."""

from __future__ import annotations

import re
import json
import hashlib
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote_plus
from pathlib import Path
from datetime import datetime

from .logger import get_logger
from . import config
from . import remote_llm
from . import web_execution_gate
from .nlp_utils import detect_confirmation, detect_confirmation_mode, parse_command
from .connectors.spotify import route_spotify_natural, try_handle_spotify_pending
from .connectors.youtube import (
    classify_youtube_intent,
    channel_lookup_candidates,
    extract_youtube_candidates_from_text,
    is_suspicious_result_for_query,
    search_youtube_candidates,
    validate_youtube_url,
    fetch_youtube_oembed,
)
from .spotify_web import try_play_via_web_api
from .triggers import TriggerStore, normalize_phrase
from .vision import VisionService
from .background_tasks import BackgroundReminderWorker
from .connectors.mobile import TelegramConnector
from .security.remote_acl import RemoteACL
from .security.otp_manager import OTPManager
from .qa import QAService
from skills.document_specialist import create_presentation

log = get_logger("orchestrator")


@dataclass
class OrchestrationResult:
    """Resultado de una decisión del orquestador."""

    handled: bool
    answer: str
    source: str
    payload: dict[str, Any] | None = None


class CommandOrchestrator:
    """
    Cerebro compartido para decidir cómo resolver un comando.

    El orden de decisión es:
    1) ActionAgent (tareas aprendidas/dinámicas)
    2) Comandos de navegación
    3) Intents estructurados (open/close/volume/brightness/system/web)
    4) Fallback a Core.ask (Ollama/LLM local)
    """

    def __init__(
        self,
        *,
        memory: Any,
        core: Any,
        action_agent: Any,
        actions: Any,
        system_info: Any | None = None,
        web_solver: Any | None = None,
        can_execute: Callable[[str], bool] | None = None,
        vision: Any | None = None,
    ) -> None:
        self.memory = memory
        self.core = core
        self.action_agent = action_agent
        self.actions = actions
        self.system_info = system_info
        self.web_solver = web_solver
        self.can_execute = can_execute
        self.vision = vision or VisionService()
        self._pending_organization_plan: dict[str, Any] | None = None
        self._spotify_pending: dict[str, Any] | None = None
        self._pending_risky_action: dict[str, str] | None = None
        self._pending_pdf_overwrite: dict[str, str] | None = None
        self._pending_shutdown_confirm = False
        self._pending_restart_confirm = False
        self._pending_trigger_create: dict[str, Any] | None = None
        self._pending_trigger_execute: dict[str, Any] | None = None
        self._pending_youtube_options: list[dict[str, str]] = []
        self._pending_youtube_confirm: dict[str, str] | None = None
        self._pending_youtube_query = ""
        self._pending_mobile_opt_in = False
        self._pending_confirmation: dict[str, Any] | None = None
        self.mobile_connector = TelegramConnector()
        self._telegram_offset = 0
        self.reminder_worker = BackgroundReminderWorker()
        self.reminder_worker.start()
        self._webhook_thread = None
        self._webhook_queue_path = config.DATA_DIR / "queue" / "telegram_queue.jsonl"
        self._webhook_queue_offset = 0
        self.remote_acl = RemoteACL()
        self.triggers = TriggerStore()
        self.otp_manager = OTPManager(ttl_seconds=int(getattr(config, "REMOTE_OTP_TTL_SECONDS", 120)))
        self.qa = QAService()
        self._bootstrap_audit_log_path = config.LOGS_DIR / "bootstrap_actions.log"
        self._remote_audit_log_path = config.LOGS_DIR / "remote_commands.log"
        self._youtube_log_path = config.LOGS_DIR / "search_history.jsonl"
        self._bootstrap_remote_mode()

    @staticmethod
    def _split_app_query(entity: str) -> tuple[str, str]:
        if not entity:
            return "", ""
        if "|||" not in entity:
            return "", entity
        app, query = entity.split("|||", 1)
        return app.strip(), query.strip()

    @staticmethod
    def _is_likely_music_request(text: str) -> bool:
        low = (text or "").strip().lower()
        if not low:
            return False
        starts = ("reproduce ", "pon ", "ponme ", "escucha ", "play ")
        if any(low.startswith(s) for s in starts):
            return True
        music_markers = (
            "spotify",
            "playlist",
            "álbum",
            "album",
            "canción",
            "track",
            "artista",
            "mis me gusta",
            "liked songs",
        )
        return any(m in low for m in music_markers)

    @staticmethod
    def _is_likely_system_command(text: str) -> bool:
        low = (text or "").strip().lower()
        command_roots = (
            "abre ",
            "abrir ",
            "inicia ",
            "cierra ",
            "cerrar ",
            "ejecuta ",
            "corre ",
            "borra ",
            "elimina ",
            "mueve ",
            "sube ",
            "baja ",
            "silencia",
            "mutea",
            "desmutea",
        )
        return any(low.startswith(root) for root in command_roots)

    @staticmethod
    def _is_likely_conversational_query(text: str) -> bool:
        clean = (text or "").strip()
        if not clean:
            return False
        low = clean.lower()
        if clean.endswith("?"):
            return True
        markers = (
            "qué es",
            "que es",
            "cómo",
            "como ",
            "por qué",
            "por que",
            "explícame",
            "explicame",
            "dime",
            "cuál",
            "cual",
            "quién",
            "quien",
        )
        return any(m in low for m in markers)

    @staticmethod
    def _command_conf_threshold() -> float:
        try:
            return float(getattr(config, "EDA_COMMAND_CONFIDENCE_THRESHOLD", 0.78))
        except Exception:
            return 0.78

    @staticmethod
    def _extract_video_search_query(text: str) -> str:
        low = (text or "").strip().lower()
        m = re.search(r"(?:abre|busca|search)\s+(?:videos?|video)\s+(?:de|sobre)?\s*(.+)$", low)
        if not m:
            return ""
        return m.group(1).strip(" .,:;!?")

    @staticmethod
    def _extract_news_query(text: str) -> tuple[str, str]:
        low = (text or "").strip().lower()
        m = re.search(r"busca\s+noticias(?:\s+en\s+([a-záéíóúñ]+))?(?:\s+sobre\s+(.+))?$", low)
        if not m:
            return "", ""
        lang = (m.group(1) or "").strip()
        topic = (m.group(2) or "últimas noticias").strip()
        return lang, topic

    @staticmethod
    def _extract_pdf_request(text: str) -> tuple[str, str]:
        low = (text or "").strip().lower()
        if "pdf" not in low:
            return "", ""
        title = "informe"
        mt = re.search(r"(?:pdf\s+del?|informe\s+de)\s+(.+?)(?:\s+en\s+|$)", low)
        if mt and mt.group(1).strip():
            title = mt.group(1).strip()
        target = "escritorio" if ("escritorio" in low or "desktop" in low) else "data/exports"
        return title, target

    @staticmethod
    def _safe_filename(name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "informe").strip())
        return cleaned[:64] or "informe"

    def _route_create_pdf(self, title: str, target_hint: str) -> str:
        home = Path.home()
        if target_hint == "escritorio":
            desktop = home / "Desktop"
            alt = home / "Escritorio"
            base = desktop if desktop.exists() else alt
            if not base.exists():
                base = config.DATA_DIR / "exports"
        else:
            base = config.DATA_DIR / "exports"
        base.mkdir(parents=True, exist_ok=True)
        out = base / f"{self._safe_filename(title)}.pdf"
        if out.exists() and self._pending_pdf_overwrite is None:
            self._pending_pdf_overwrite = {"path": str(out), "title": title}
            return f"El archivo {out} ya existe. ¿Deseas sobrescribirlo? (Sí/No)"
        content = (
            "%PDF-1.1\n"
            "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            "2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n"
            "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
            f"4 0 obj << /Length {len(title) + 48} >> stream\nBT /F1 18 Tf 72 720 Td ({title}) Tj ET\nendstream endobj\n"
            "xref\n0 5\n0000000000 65535 f \n"
            "0000000010 00000 n \n0000000060 00000 n \n0000000117 00000 n \n0000000207 00000 n \n"
            "trailer << /Root 1 0 R /Size 5 >>\nstartxref\n300\n%%EOF\n"
        )
        out.write_text(content, encoding="latin-1", errors="ignore")
        self._pending_pdf_overwrite = None
        return f"PDF creado en: {out}"

    def orchestrate(self, text: str) -> OrchestrationResult:
        clean = (text or "").strip()
        if not clean:
            return OrchestrationResult(True, "", "empty")
        low = clean.lower()

        force_close_match = re.match(r"^\s*(?:forzar|force|kill)\s+(?:cerrar|cierra|close)\s+(.+)$", low)
        if force_close_match:
            target = force_close_match.group(1).strip()
            result = self.actions.close_app_robust(target, force=True)
            return OrchestrationResult(True, result.get("message", f"Forcé cierre de {target}."), "close_app_forced")

        # Confirmación genérica para entradas cortas (UI/STT) con timeout.
        if self._pending_confirmation is not None:
            created = float(self._pending_confirmation.get("created_at", 0.0))
            if (datetime.now().timestamp() - created) > float(self._pending_confirmation.get("timeout_sec", 30)):
                self._pending_confirmation = None
            else:
                mode = detect_confirmation_mode(clean)
                if mode in {"yes", "no", "force"}:
                    pending = dict(self._pending_confirmation)
                    self._pending_confirmation = None
                    if pending.get("kind") == "close_app":
                        target = str(pending.get("target", "")).strip()
                        if mode == "no":
                            return OrchestrationResult(True, "Listo, no cerraré la aplicación.", "close_app_cancelled")
                        result = self.actions.close_app_robust(target, force=(mode == "force"))
                        src = "close_app_forced" if mode == "force" else "close_app_confirmed"
                        return OrchestrationResult(True, result.get("message", f"Intenté cerrar {target}."), src)

        if self._pending_youtube_options:
            choice = low.strip()
            if choice in {"1", "2", "3"}:
                idx = int(choice) - 1
                if 0 <= idx < len(self._pending_youtube_options):
                    chosen = self._pending_youtube_options[idx]
                    self._pending_youtube_options = []
                    self._release_ollama_for_low_ram()
                    webbrowser.open(chosen["url"])
                    self._log_youtube_search(
                        user_query=self._pending_youtube_query or clean,
                        top_candidates=[],
                        chosen_video=chosen,
                        action="opened",
                        source=str(chosen.get("source", "unknown")),
                    )
                    return OrchestrationResult(True, f"Abriendo YouTube: {chosen['url']}", "youtube_choice")
            if detect_confirmation(clean) is False:
                self._log_youtube_search(
                    user_query=self._pending_youtube_query or clean,
                    top_candidates=self._pending_youtube_options,
                    chosen_video=None,
                    action="ignored",
                    source="selection",
                )
                self._pending_youtube_options = []
                return OrchestrationResult(True, "Cancelado, no abrí YouTube.", "youtube_choice_cancel")
            return OrchestrationResult(True, "Elige 1, 2 o 3 para abrir un resultado de YouTube.", "youtube_choice_wait")
        if self._pending_youtube_confirm is not None:
            decision = detect_confirmation(clean)
            if decision is True:
                chosen = dict(self._pending_youtube_confirm)
                self._pending_youtube_confirm = None
                url = str(chosen.get("url", "")).strip()
                if not validate_youtube_url(url):
                    return OrchestrationResult(True, "Ese enlace ya no parece válido/safe de YouTube.", "youtube_confirm_invalid")
                self._release_ollama_for_low_ram()
                webbrowser.open(url)
                self._log_youtube_search(
                    user_query=self._pending_youtube_query or clean,
                    top_candidates=[chosen],
                    chosen_video=chosen,
                    action="opened",
                    source=str(chosen.get("source", "unknown")),
                )
                return OrchestrationResult(True, f"Abriendo YouTube: {url}", "youtube_confirm_open")
            if decision is False:
                self._log_youtube_search(
                    user_query=self._pending_youtube_query or clean,
                    top_candidates=[self._pending_youtube_confirm],
                    chosen_video=None,
                    action="ignored",
                    source="confirm",
                )
                self._pending_youtube_confirm = None
                return OrchestrationResult(True, "Cancelado, no abrí el video.", "youtube_confirm_cancel")
            cand = dict(self._pending_youtube_confirm)
            return OrchestrationResult(
                True,
                f"Encontré este video: {cand.get('title','video')} ({cand.get('channel','canal')}). ¿Quieres que lo reproduzca? (Sí/No)",
                "youtube_confirm_wait",
                payload={"youtube_confirm": cand},
            )

        if self._pending_trigger_create is not None:
            decision = detect_confirmation(clean)
            if decision is True:
                p = dict(self._pending_trigger_create)
                self._pending_trigger_create = None
                trigger_id = self.triggers.create_trigger(
                    phrase=p["phrase"],
                    match_type=p.get("match_type", "fuzzy"),
                    action_type=p["action_type"],
                    action_payload=p.get("action_payload", {}),
                    require_confirm=bool(p.get("require_confirm", True)),
                )
                return OrchestrationResult(True, f"Trigger creado (id={trigger_id}) para '{p['phrase']}'.", "trigger_created")
            if decision is False:
                self._pending_trigger_create = None
                return OrchestrationResult(True, "Cancelado, no creé el trigger.", "trigger_create_cancelled")
            return OrchestrationResult(True, "Responde Sí o No para confirmar creación del trigger.", "trigger_create_wait")

        if self._pending_trigger_execute is not None:
            decision = detect_confirmation(clean)
            if decision is True:
                trig = dict(self._pending_trigger_execute)
                self._pending_trigger_execute = None
                result = self._execute_trigger_action(trig)
                self._audit_operate_secure(
                    "trigger_executed",
                    f"trigger_id={trig.get('id')}",
                    {
                        "trigger_id": trig.get("id"),
                        "phrase_matched": trig.get("phrase", ""),
                        "action": trig.get("action_type"),
                        "result": result[:180],
                        "user_confirmed": True,
                    },
                )
                return OrchestrationResult(True, f"Trigger ejecutado — {result}", "trigger_executed_confirmed")
            if decision is False:
                self._pending_trigger_execute = None
                return OrchestrationResult(True, "Trigger cancelado.", "trigger_cancelled")
            return OrchestrationResult(True, "Responde Sí o No para ejecutar el trigger.", "trigger_wait")

        if low.startswith("listar mis disparadores"):
            rows = self.triggers.list_triggers(active_only=False)
            if not rows:
                return OrchestrationResult(True, "No tienes disparadores creados.", "trigger_list")
            txt = "\n".join([f"#{r['id']} [{'ON' if r['active'] else 'OFF'}] '{r['phrase']}' -> {r['action_type']}" for r in rows[:20]])
            return OrchestrationResult(True, f"Disparadores:\n{txt}", "trigger_list")

        quick_trigger = self._parse_trigger_chat_request(clean)
        if quick_trigger is not None:
            self._pending_trigger_create = quick_trigger
            return OrchestrationResult(
                True,
                (
                    f"¿Confirmas que cada vez que digas '{quick_trigger['phrase']}' "
                    f"ejecute {quick_trigger['action_type']}?"
                ),
                "trigger_create_confirm",
            )

        yt_intent = classify_youtube_intent(clean)
        if yt_intent and not re.match(r"^\s*(abre|abrir|open)\s+", low):
            yt_answer, yt_source, yt_payload = self._route_play_youtube(clean, yt_intent)
            if yt_answer:
                return OrchestrationResult(True, yt_answer, yt_source, yt_payload)
        identity_facts = self.memory.update_user_profile_from_text(clean)
        if identity_facts:
            self.memory.save_long_term_memory(
                clean,
                f"Perfil actualizado: {', '.join(f'{k}={v}' for k, v in identity_facts.items())}",
                tags=["identity", "profile"],
                importance=5,
            )

        if low.startswith("recuerda que"):
            remembered = clean.split("que", 1)[1].strip(" .,:;") if "que" in low else clean
            self.memory.save_long_term_memory(
                clean,
                f"Recordatorio persistente registrado: {remembered}",
                tags=["remember", "user_fact"],
                importance=5,
            )
            profile = self.memory.get_user_profile()
            name = str(profile.get("name", "Eric")).strip() or "Eric"
            return OrchestrationResult(
                True,
                f"Entendido, {name}. Guardado en mi memoria permanente.",
                "remember_persistent",
            )

        trig_match = self.triggers.match(clean)
        if trig_match and trig_match.get("trigger"):
            t = trig_match["trigger"]
            if bool(t.get("require_confirm")):
                self._pending_trigger_execute = t
                self._audit_operate_secure(
                    "trigger_match_confirm_required",
                    f"trigger_id={t.get('id')}",
                    {"trigger_id": t.get("id"), "phrase_matched": trig_match.get("phrase_matched"), "action": t.get("action_type")},
                )
                return OrchestrationResult(True, "Trigger detectado. ¿Confirmas ejecución? (Sí/No)", "trigger_confirm_required")
            result = self._execute_trigger_action(t)
            self._audit_operate_secure(
                "trigger_executed",
                f"trigger_id={t.get('id')}",
                {
                    "trigger_id": t.get("id"),
                    "phrase_matched": trig_match.get("phrase_matched"),
                    "action": t.get("action_type"),
                    "result": result[:180],
                    "user_confirmed": False,
                },
            )
            return OrchestrationResult(True, f"Trigger: '{t.get('phrase')}' ejecutado — {result}", "trigger_executed")

        if web_execution_gate.text_disarms_gate(clean):
            web_execution_gate.disarm()
            return OrchestrationResult(True, "Acciones locales desbloqueadas; podés usar comandos otra vez.", "web_gate_disarmed")

        if low in {"deshaz lo último", "deshaz lo ultimo", "deshazlo"}:
            result = self.actions.undo_last_action()
            return OrchestrationResult(True, result.get("message", ""), "undo_last_action")

        if low.startswith("listar recordatorios"):
            reminders = self.reminder_worker.list_reminders()
            if not reminders:
                return OrchestrationResult(True, "No hay recordatorios pendientes.", "list_reminders")
            lines = [f"#{r['id']} -> {r['message']}" for r in reminders[:20]]
            return OrchestrationResult(True, "Recordatorios:\n" + "\n".join(lines), "list_reminders")

        if low.startswith("cancelar recordatorio"):
            match = re.search(r"(\d+)", low)
            if not match:
                return OrchestrationResult(True, "Necesito el ID del recordatorio a cancelar.", "cancel_reminder")
            ok = self.reminder_worker.cancel_reminder(int(match.group(1)))
            return OrchestrationResult(True, "Recordatorio cancelado." if ok else "No encontré ese recordatorio.", "cancel_reminder")

        if low.startswith("enviar mensaje al móvil") or low.startswith("enviar mensaje al movil"):
            if not self.mobile_connector.config.enabled:
                self._pending_mobile_opt_in = True
                return OrchestrationResult(
                    True,
                    "Para enviarte mensajes al móvil, necesito que habilites el servicio con tu Token. ¿Deseas configurarlo?",
                    "mobile_opt_in_prompt",
                )
            payload = clean.split(":", 1)[1].strip() if ":" in clean else "Mensaje desde E.D.A."
            result = self.mobile_connector.enviar_mensaje(payload)
            return OrchestrationResult(True, result.get("message", ""), "mobile_send")

        if self._pending_mobile_opt_in:
            decision = detect_confirmation(clean)
            if decision is True:
                self._pending_mobile_opt_in = False
                return OrchestrationResult(
                    True,
                    "Configuración pendiente: usa 'configurar móvil: telegram|<TOKEN>|<CHAT_ID>' o pushbullet.",
                    "mobile_opt_in_accepted",
                )
            if decision is False:
                self._pending_mobile_opt_in = False
                return OrchestrationResult(True, "Perfecto, mantengo el conector móvil desactivado.", "mobile_opt_in_rejected")
            return OrchestrationResult(True, "Responde Sí o No para configurar el conector móvil.", "mobile_opt_in_wait")

        if low.startswith("configurar móvil:") or low.startswith("configurar movil:"):
            raw = clean.split(":", 1)[1].strip()
            parts = [p.strip() for p in raw.split("|")]
            if len(parts) < 2:
                return OrchestrationResult(True, "Formato: configurar móvil: telegram|TOKEN|CHAT_ID", "mobile_config_invalid")
            provider = parts[0].lower()
            token = parts[1]
            chat_id = parts[2] if len(parts) >= 3 else ""
            if provider != "telegram":
                return OrchestrationResult(True, "Por ahora solo está habilitado Telegram.", "mobile_config_invalid")
            self.mobile_connector.save_opt_in(token=token, telegram_chat_id=chat_id)
            return OrchestrationResult(True, "Telegram configurado en modo Opt-In.", "mobile_configured")

        if self.can_execute and not self.can_execute(clean):
            return OrchestrationResult(True, "Acción bloqueada por permisos/configuración.", "security")

        if self._pending_risky_action is not None:
            decision = detect_confirmation(clean)
            if decision is True:
                approved_text = self._pending_risky_action.get("user_text", "")
                self._pending_risky_action = None
                handled, answer = self.action_agent.try_handle(approved_text)
                if handled:
                    return OrchestrationResult(True, answer, "approved_risky_action")
                return OrchestrationResult(True, "No pude ejecutar la acción aprobada.", "approved_risky_action")
            if decision is False:
                self._pending_risky_action = None
                return OrchestrationResult(True, "Acción cancelada por seguridad.", "risky_action_cancelled")
            return OrchestrationResult(
                True,
                "Hay una acción crítica pendiente. Responde Sí para ejecutar o No para cancelar.",
                "risky_action_waiting_confirmation",
            )
        if self._pending_pdf_overwrite is not None:
            decision = detect_confirmation(clean)
            if decision is True:
                pending = dict(self._pending_pdf_overwrite)
                self._pending_pdf_overwrite = None
                title = pending.get("title", "informe")
                target = "escritorio" if ("Desktop" in pending.get("path", "") or "Escritorio" in pending.get("path", "")) else "data/exports"
                return OrchestrationResult(True, self._route_create_pdf(title, target), "create_pdf_overwrite")
            if decision is False:
                self._pending_pdf_overwrite = None
                return OrchestrationResult(True, "Cancelado, no sobrescribí el PDF.", "create_pdf_cancelled")
            return OrchestrationResult(True, "Responde Sí o No para sobrescribir el PDF.", "create_pdf_wait")
        if self._pending_shutdown_confirm:
            decision = detect_confirmation(clean)
            if decision is True:
                self._pending_shutdown_confirm = False
                result = self.actions.shutdown(preconfirmed=True)
                return OrchestrationResult(True, result.get("message", "Apagado programado."), "shutdown_system")
            if decision is False:
                self._pending_shutdown_confirm = False
                return OrchestrationResult(True, "Cancelado, no apagaré el equipo.", "shutdown_cancelled")
            return OrchestrationResult(True, "Responde Sí o No para confirmar apagado del sistema.", "shutdown_wait")
        if self._pending_restart_confirm:
            decision = detect_confirmation(clean)
            if decision is True:
                self._pending_restart_confirm = False
                result = self.actions.restart(preconfirmed=True)
                return OrchestrationResult(True, result.get("message", "Reinicio programado."), "restart_system")
            if decision is False:
                self._pending_restart_confirm = False
                return OrchestrationResult(True, "Cancelado, no reiniciaré el equipo.", "restart_cancelled")
            return OrchestrationResult(True, "Responde Sí o No para confirmar reinicio del sistema.", "restart_wait")

        risk_preview = self._build_risk_preview(clean)
        if risk_preview:
            self._pending_risky_action = {"user_text": clean, "preview": risk_preview}
            return OrchestrationResult(
                True,
                f"[Aprobación PRO requerida]\n{risk_preview}\n¿Confirmas ejecución? (Sí/No)",
                "risky_action_requires_confirmation",
            )

        if self._pending_organization_plan is not None:
            confirmation = detect_confirmation(clean)
            if confirmation is True:
                result = self.actions.apply_directory_organization_plan(self._pending_organization_plan)
                self._pending_organization_plan = None
                return OrchestrationResult(True, result.get("message", "Plan aplicado."), "organize_directory_apply")
            if confirmation is False:
                self._pending_organization_plan = None
                return OrchestrationResult(True, "Listo, cancelé la organización de archivos.", "organize_directory_cancel")
            return OrchestrationResult(
                True,
                "Tengo una organización pendiente. Responde 'sí' para ejecutar o 'no' para cancelar.",
                "organize_directory_waiting_confirmation",
            )

        spotify_pending_answer = try_handle_spotify_pending(self, clean)
        if spotify_pending_answer is not None:
            return OrchestrationResult(True, spotify_pending_answer, "spotify_pending")

        parsed = parse_command(clean)
        intent = parsed.intent
        conf_str = f"{float(parsed.confidence or 0.0):.2f}"
        log.info("[ORCHESTRATOR] Intent detected: %s | entity=%s | conf=%s", intent, parsed.entity, conf_str)

        # Prioridad dura de música: evita que "reproduce X" caiga al ActionAgent.
        if self._is_likely_music_request(clean) or intent in {"play_music", "open_and_play_music"}:
            app, query = self._split_app_query(parsed.entity)
            track_query = query if query else (parsed.entity or clean)
            route_score = f"{max(0.86, float(parsed.confidence or 0.0)):.2f}"
            log.info("[ORCHESTRATOR] route chosen: spotify (score=%s)", route_score)
            return OrchestrationResult(
                True,
                self._route_play_music(track_query, preferred_app=app, utterance=clean),
                "play_music",
            )
        video_q = self._extract_video_search_query(clean)
        if video_q:
            if self.web_solver is not None:
                solved = self.web_solver.solve(f"videos {video_q}", auto_save_code=False)
                out = solved.get("answer", f"Top-5 resultados de video para {video_q}.")
                log.info("[ORCHESTRATOR] route chosen: open_media_search (score=%s)", conf_str)
                return OrchestrationResult(True, out, "open_media_search")
            return OrchestrationResult(True, f"No tengo solver web activo, pero buscaría videos de {video_q}.", "open_media_search")

        pdf_title, pdf_target = self._extract_pdf_request(clean)
        if pdf_title:
            log.info("[ORCHESTRATOR] route chosen: create_pdf (score=%s)", conf_str)
            return OrchestrationResult(True, self._route_create_pdf(pdf_title, pdf_target), "create_pdf")

        news_lang, news_topic = self._extract_news_query(clean)
        if news_lang or "noticias" in clean.lower():
            prompt = f"noticias {news_topic}".strip()
            if news_lang:
                prompt = f"{prompt} en {news_lang}"
            if remote_llm.remote_search_mode_requested() and remote_llm.is_remote_fully_configured():
                ans = self.core.filtered_remote_research_answer(prompt)
                log.info("[ORCHESTRATOR] route chosen: web_search_news_remote (score=%s)", conf_str)
                return OrchestrationResult(True, ans, "web_search_news")
            if self.web_solver is not None:
                solved = self.web_solver.solve(prompt, auto_save_code=False)
                return OrchestrationResult(True, solved.get("answer", "No pude traer noticias ahora."), "web_search_news")
            return OrchestrationResult(True, "No tengo motor de noticias disponible en este momento.", "web_search_news")

        nav = self.actions.execute_navigation_command(clean)
        if nav is not None:
            return OrchestrationResult(True, nav.get("message", "Comando de navegación ejecutado."), "navigation")

        # Si parece conversación y no comando de sistema, responder con LLM en vez de "acción directa".
        if (
            self._is_likely_conversational_query(clean)
            and not self._is_likely_system_command(clean)
            and float(parsed.confidence or 0.0) < self._command_conf_threshold()
        ):
            mem = self.memory.get_memory()
            history = mem.get("chat_history", []) or mem.get("history", [])
            log.info("[ORCHESTRATOR] route chosen: llm_conversation (score=%s)", conf_str)
            answer = self.core.ask(clean, history=history, allow_web_fallback=self._should_use_web_for_question(clean, intent))
            return OrchestrationResult(True, f"Te explico: {answer}", "conversation_llm")

        handled, answer = self.action_agent.try_handle(clean)
        if handled:
            log.info("[ORCHESTRATOR] route chosen: action_agent (score=%s)", conf_str)
            return OrchestrationResult(True, answer, "action_agent")

        if intent in {
            "theoretical_question",
            "technical_question",
            "general_knowledge_question",
            "explanation_request",
            "debugging_request",
        }:
            qa_answer, qa_source = self.qa.answer(clean)
            if qa_answer:
                return OrchestrationResult(True, qa_answer, qa_source)
            response_instruction = self._response_instruction_for_intent(intent)
            use_web = self._should_use_web_for_question(clean, intent)
            mem = self.memory.get_memory()
            history = mem.get("chat_history", []) or mem.get("history", [])
            if use_web and intent == "search_request" and remote_llm.remote_search_mode_requested():
                if not remote_llm.is_remote_fully_configured():
                    return OrchestrationResult(True, remote_llm.RemoteUnavailableMsg, "remote_search_misconfigured")
                answer = self.core.filtered_remote_research_answer(clean)
                log.info("[ORCHESTRATOR] route chosen: remote_secured_research (score=%s)", conf_str)
                return OrchestrationResult(True, answer, "remote_secured_research")
            route = "core_direct_answer" if not use_web else "core_web_allowed"
            log.info("[ORCHESTRATOR] route chosen: %s (score=%s)", route, conf_str)
            answer = self.core.ask(
                clean,
                history=history,
                allow_web_fallback=use_web,
                response_instruction=response_instruction,
            )
            if not use_web:
                log.info("[ORCHESTRATOR] Fallback: web search not used")
            return OrchestrationResult(True, answer, "knowledge_answer")

        if intent in {"search_in_app", "open_and_search_in_app"}:
            app, query = self._split_app_query(parsed.entity)
            if not query:
                query = clean
            if not app:
                app = "steam" if "steam" in clean.lower() else "spotify"
            log.info("[ORCHESTRATOR] Route: search_in_app (%s)", app)
            return OrchestrationResult(True, self._route_search_in_app(app, query), "search_in_app")

        if intent == "screen_comprehension":
            log.info("[ORCHESTRATOR] Route: screen_comprehension")
            return OrchestrationResult(True, self._route_screen_comprehension(clean), "screen_comprehension")

        if intent == "organize_directory":
            log.info("[ORCHESTRATOR] Route: organize_directory")
            return OrchestrationResult(True, self._route_organize_directory(parsed.entity, clean), "organize_directory_plan")

        if intent == "create_presentation":
            log.info("[ORCHESTRATOR] Route: create_presentation")
            return OrchestrationResult(True, self._route_create_presentation(parsed.entity or clean), "create_presentation")

        if intent == "open_app":
            target = parsed.entity or clean
            try:
                result = self.actions.open_app(target)
            except FileNotFoundError:
                result = {"status": "error", "message": "File not found"}
            except Exception as exc:
                result = {"status": "error", "message": str(exc)}
            if result.get("status") == "ok":
                return OrchestrationResult(True, result.get("message", "Aplicación abierta."), "open_app")
            web_candidate = self.actions._resolve_web_target_url(target)
            if web_candidate:
                web_result = self.actions.open_website(web_candidate)
                if web_result.get("status") == "ok":
                    return OrchestrationResult(
                        True,
                        f"No encontré app local para {target}. Lo abrí en navegador.",
                        "open_app_web_fallback",
                    )
            if self.web_solver is not None:
                solved = self.web_solver.solve(f"buscar {target}", auto_save_code=False)
                return OrchestrationResult(
                    True,
                    solved.get("answer", f"No encontré app local para {target}; intenté búsqueda de apoyo."),
                    "open_app_search_fallback",
                )
            fallback_url = f"https://www.google.com/search?q={quote_plus(target)}&hl=es"
            self.actions.open_website(fallback_url)
            return OrchestrationResult(True, "No identifiqué la app; abrí búsqueda web como fallback.", "open_app_fallback")

        if intent == "list_windows":
            windows = self.actions.list_windows()
            if windows.get("status") != "ok":
                return OrchestrationResult(True, windows.get("message", "No pude listar ventanas."), "list_windows")
            items = windows.get("windows", [])
            if not isinstance(items, list) or not items:
                return OrchestrationResult(True, "No detecté ventanas abiertas visibles.", "list_windows")
            preview = "\n".join(f"- {str(w)}" for w in items[:20])
            return OrchestrationResult(True, f"Ventanas abiertas:\n{preview}", "list_windows")

        if intent == "focus_window":
            target = parsed.entity or clean
            focused = self.actions.focus_window(target)
            return OrchestrationResult(True, focused.get("message", "Intenté enfocar la ventana."), "focus_window")

        if intent == "activate_app_window":
            target = parsed.entity or clean
            focused = self.actions.activate_app_window(target)
            return OrchestrationResult(True, focused.get("message", "Intenté activar la ventana."), "activate_app_window")

        if intent == "shutdown_system":
            self._pending_shutdown_confirm = True
            return OrchestrationResult(
                True,
                "Vas a apagar el equipo. Esta acción cerrará aplicaciones y puede perderse trabajo no guardado. ¿Confirmas? (Sí/No)",
                "shutdown_confirm_required",
            )

        if intent == "restart_system":
            self._pending_restart_confirm = True
            return OrchestrationResult(
                True,
                "Vas a reiniciar el equipo. Esta acción cerrará aplicaciones y puede perderse trabajo no guardado. ¿Confirmas? (Sí/No)",
                "restart_confirm_required",
            )

        if intent == "close_app":
            target = parsed.entity or clean
            force_now = bool(re.search(r"\b(forzar|force|kill)\b", clean.lower()))
            target = re.sub(r"\b(forzar|force|kill)\b", "", target, flags=re.IGNORECASE).strip()
            if force_now:
                result = self.actions.close_app_robust(target, force=True)
                return OrchestrationResult(True, result.get("message", f"Forcé cierre de {target}."), "close_app_forced")
            if any(k in target.lower() for k in ("chrome", "edge", "firefox", "brave")):
                self._pending_confirmation = {
                    "kind": "close_app",
                    "target": target,
                    "created_at": datetime.now().timestamp(),
                    "timeout_sec": 30.0,
                    "caller": "close_app_intent",
                }
                return OrchestrationResult(
                    True,
                    f"Vas a cerrar {target}. Podrías perder pestañas o datos no guardados. ¿Confirmas? (Sí/No, o 'forzar')",
                    "close_app_confirm_required",
                )
            result = self.actions.close_app_robust(target, force=False)
            return OrchestrationResult(True, result.get("message", "Intenté cerrar la aplicación."), "close_app")

        if intent == "volume":
            return OrchestrationResult(True, self._handle_volume(clean), "volume")

        if intent == "brightness":
            return OrchestrationResult(True, self._handle_brightness(clean), "brightness")

        if intent in {"search_web", "search_request", "arduino_help"} and self.web_solver is not None:
            if remote_llm.remote_search_mode_requested() and not remote_llm.is_remote_fully_configured():
                return OrchestrationResult(True, remote_llm.RemoteUnavailableMsg, "remote_search_misconfigured")
            if remote_llm.remote_search_mode_requested() and remote_llm.is_remote_fully_configured():
                answer = self.core.filtered_remote_research_answer(clean)
                log.info("[ORCHESTRATOR] route chosen: remote_secured_research (score=%s)", conf_str)
                return OrchestrationResult(True, answer, "remote_secured_research")
            solved = self.web_solver.solve(clean, auto_save_code=True)
            log.info("[ORCHESTRATOR] route chosen: web_solver (score=%s)", conf_str)
            return OrchestrationResult(True, solved.get("answer", "No tengo respuesta por ahora."), "web_solver")

        if intent == "system_info" and self.system_info is not None:
            m = self.system_info.get_metrics()
            answer = f"CPU {m.get('cpu')} | RAM {m.get('ram')} | Hora {m.get('time')} | Ollama {m.get('ollama', 'N/D')}"
            return OrchestrationResult(True, answer, "system_info")

        mem = self.memory.get_memory()
        history = mem.get("chat_history", []) or mem.get("history", [])
        answer = self.core.ask(clean, history=history)
        return OrchestrationResult(True, answer, "core")

    def _bootstrap_remote_mode(self) -> None:
        mode = str(getattr(config, "TELEGRAM_CONTROL_MODE", "polling")).strip().lower()
        if mode != "webhook":
            return
        try:
            from .webhook.telegram_webhook import start_webhook_thread

            self._webhook_thread = start_webhook_thread(
                telegram_connector=self.mobile_connector,
                host=str(getattr(config, "TELEGRAM_WEBHOOK_HOST", "127.0.0.1")),
                port=int(getattr(config, "TELEGRAM_WEBHOOK_PORT", 8088)),
            )
            if getattr(config, "TELEGRAM_WEBHOOK_USE_NGROK", False):
                log.info("[ORCHESTRATOR] Webhook mode activo. Use ngrok para exponer localhost de forma controlada.")
            else:
                log.info("[ORCHESTRATOR] Webhook mode activo en localhost.")
        except Exception as exc:
            log.warning("[ORCHESTRATOR] No pude iniciar webhook mode: %s", exc)

    def poll_remote_commands(self) -> list[OrchestrationResult]:
        """Procesa comandos remotos entrantes desde Telegram del chat dueño."""
        mode = str(getattr(config, "TELEGRAM_CONTROL_MODE", "polling")).strip().lower()
        if mode == "webhook":
            return self._poll_webhook_queue()
        batch = self.mobile_connector.fetch_updates(offset=self._telegram_offset)
        if batch.get("status") != "ok":
            return []
        self._telegram_offset = int(batch.get("next_offset", self._telegram_offset))
        results: list[OrchestrationResult] = []
        for item in batch.get("updates", []):
            if not isinstance(item, dict):
                continue
            chat_id = str(item.get("chat_id", "")).strip()
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            result = self._process_remote_command(text=text, chat_id=chat_id, source="telegram_polling")
            results.append(result)
            # Enviar confirmación al dueño.
            self.mobile_connector.enviar_mensaje(f"[EDA remoto] {result.answer}")
        return results

    def _poll_webhook_queue(self) -> list[OrchestrationResult]:
        queue_path = self._webhook_queue_path
        if not queue_path.exists():
            return []
        results: list[OrchestrationResult] = []
        with queue_path.open("r", encoding="utf-8") as fh:
            fh.seek(self._webhook_queue_offset)
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                text = str(item.get("command_text", "")).strip()
                chat_id = str(item.get("chat_id", "")).strip()
                if not text:
                    continue
                result = self._process_remote_command(text=text, chat_id=chat_id, source="telegram_webhook")
                results.append(result)
                self.mobile_connector.enviar_mensaje(f"[EDA remoto] {result.answer}")
            self._webhook_queue_offset = fh.tell()
        return results

    @staticmethod
    def _obfuscate_chat_id(chat_id: str) -> str:
        text = (chat_id or "").strip()
        if len(text) <= 4:
            return "***"
        return f"{text[:2]}****{text[-2:]}"

    def _append_audit_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _audit_remote_attempt(
        self,
        *,
        chat_id: str,
        text: str,
        outcome: str,
        reason: str = "",
        level: str = "",
        source: str = "",
    ) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        payload_hash = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        entry = {
            "timestamp": stamp,
            "chat_id": self._obfuscate_chat_id(chat_id),
            "action_name": (text.split()[0].lower() if text else "empty"),
            "level": level,
            "source": source,
            "outcome": outcome,
            "reason": reason,
            "raw_payload_hash": payload_hash,
        }
        self._append_audit_jsonl(self._remote_audit_log_path, entry)
        self._append_audit_jsonl(self._bootstrap_audit_log_path, {"event": "remote_command", **entry})

    def _process_remote_command(self, *, text: str, chat_id: str, source: str) -> OrchestrationResult:
        clean = (text or "").strip()
        owner_chat_id = self.mobile_connector.get_owner_chat_id()
        remote_chat = (chat_id or owner_chat_id or "owner").strip()

        lowered = clean.lower()
        if lowered.startswith("confirm "):
            otp = clean.split(" ", 1)[1].strip() if " " in clean else ""
            verified = self.otp_manager.verify(remote_chat, otp)
            if not verified.get("ok"):
                reason = str(verified.get("reason", "otp_invalid"))
                self._audit_remote_attempt(chat_id=remote_chat, text=clean, outcome="rejected", reason=reason, source=source)
                if self.otp_manager.should_alert_failed_otp(remote_chat):
                    self.mobile_connector.enviar_mensaje("Alerta: 3 intentos fallidos de OTP en 10 minutos.")
                return OrchestrationResult(True, "OTP inválido o expirado.", "remote_otp_invalid")
            approved_command = str(verified.get("command", "")).strip()
            self._audit_remote_attempt(
                chat_id=remote_chat,
                text=approved_command,
                outcome="approved",
                reason="otp_confirmed",
                level="critical",
                source=source,
            )
            return self.orchestrate(approved_command)

        acl = self.remote_acl.classify(clean)
        if not acl.allowed:
            self._audit_remote_attempt(
                chat_id=remote_chat,
                text=clean,
                outcome="rejected",
                reason=acl.reason or "acl_blocked",
                level=acl.level,
                source=source,
            )
            return OrchestrationResult(True, "Comando remoto bloqueado por ACL.", "remote_acl_blocked")

        if acl.level == "critical":
            otp = self.otp_manager.issue(remote_chat, clean)
            self.mobile_connector.enviar_mensaje(f"Confirmación requerida. Envía: confirm {otp} (expira en 2 min)")
            self._audit_remote_attempt(
                chat_id=remote_chat,
                text=clean,
                outcome="challenged",
                reason="otp_required",
                level=acl.level,
                source=source,
            )
            return OrchestrationResult(True, "Acción crítica detectada. OTP enviado por Telegram.", "remote_otp_challenge")

        result = self.orchestrate(clean)
        self._audit_remote_attempt(
            chat_id=remote_chat,
            text=clean,
            outcome="executed",
            reason="ok",
            level=acl.level,
            source=source,
        )
        return result

    @staticmethod
    def _build_risk_preview(text: str) -> str:
        lowered = (text or "").lower()
        if "ejecuta comando:" in lowered or lowered.startswith("corre comando:"):
            return (
                f"Comando solicitado: {text}\n"
                "Efectos previstos: ejecución de terminal con cambios potenciales en sistema/archivos."
            )
        if "mueve archivo:" in lowered:
            return (
                f"Acción solicitada: {text}\n"
                "Efectos previstos: movimiento de archivos/directorios; puede alterar rutas originales."
            )
        if any(k in lowered for k in ["borra", "elimina", "rm ", "del "]):
            return (
                f"Acción solicitada: {text}\n"
                "Efectos previstos: eliminación de datos potencialmente irreversible."
            )
        return ""

    @staticmethod
    def _response_instruction_for_intent(intent: str) -> str:
        if intent == "technical_question":
            return (
                "Responde en estilo técnico y claro: 1) definición, 2) cómo funciona, "
                "3) ejemplo corto, 4) cuándo se usa. Evita relleno conversacional."
            )
        if intent == "debugging_request":
            return (
                "Responde como diagnóstico técnico: causa probable, pasos de verificación, "
                "solución sugerida y advertencias. Sé concreto."
            )
        if intent == "explanation_request":
            return (
                "Responde con resumen breve + explicación desarrollada + ejemplo práctico. "
                "Evita metáforas innecesarias."
            )
        if intent == "theoretical_question":
            return "Responde de forma directa, precisa y breve. Sin texto irrelevante."
        if intent == "general_knowledge_question":
            return (
                "Responde con dato directo y contexto mínimo útil. Si hay incertidumbre, dilo claramente "
                "y ofrece ampliar."
            )
        return "Responde claro y directo."

    @staticmethod
    def _should_use_web_for_question(text: str, intent: str) -> bool:
        lowered = (text or "").lower()
        if intent == "search_request":
            return True
        explicit_web = ("busca en web" in lowered) or ("según internet" in lowered) or ("verifica en línea" in lowered)
        if explicit_web:
            return True
        freshness_markers = ("hoy", "actualmente", "última", "ultima", "reciente", "este año", "2026", "noticia")
        return any(marker in lowered for marker in freshness_markers)

    def set_youtube_auto_open(self, enabled: bool) -> None:
        try:
            config.YOUTUBE_AUTO_OPEN = bool(enabled)
        except Exception:
            pass

    def _audit_operate_secure(self, event: str, detail: str, extra: dict[str, Any] | None = None) -> None:
        path = config.LOGS_DIR / "operate_secure_audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "step": "orchestrator",
            "event": event,
            "detail": detail[:260],
        }
        if extra:
            payload.update(extra)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("[ORCHESTRATOR] No pude escribir audit log: %s", exc)

    def _route_play_music(self, query: str, preferred_app: str = "", utterance: str = "") -> str:
        q = (query or "").strip()
        utt = (utterance or q or "").strip()
        if not q and not utt:
            return "Necesito el nombre de la canción, artista o álbum para reproducir."

        app = (preferred_app or "spotify").lower().strip()
        if app and app != "spotify":
            # Hoy la ruta robusta de reproducción está integrada para Spotify.
            log.info("[ORCHESTRATOR] Fallback to spotify for playback (preferred_app=%s)", app)

        self.actions.open_app("spotify")

        try:
            smart = route_spotify_natural(self, utt, q)
            if smart is not None:
                if smart.lower().startswith("reproduciendo"):
                    return smart
                return f"Buscando {q or utt} en Spotify... {smart}"
        except Exception as exc:
            log.warning("[ORCHESTRATOR] spotify natural route: %s", exc)

        # Prioridad 1: Spotify Web API (si está configurada y hay dispositivo activo).
        try:
            status, detail = try_play_via_web_api(q or utt)
            if status == "ok":
                log.info("[ORCHESTRATOR] Playback success via spotify_web_api")
                return f"Buscando {q or utt} en Spotify... Reproduciendo ahora."
            if status == "fail" and detail == "no_active_device":
                self._audit_operate_secure(
                    "audio_device_failure",
                    "Spotify sin dispositivo activo para reproducción",
                    {"query": (q or utt)[:160]},
                )
                return (
                    "No encontré un dispositivo de audio activo en Spotify. "
                    "Registré el incidente en seguridad operativa y te lo notifico por UI."
                )
            log.info("[ORCHESTRATOR] spotify_web_api status=%s detail=%s", status, detail)
        except Exception as exc:
            log.warning("[ORCHESTRATOR] spotify_web_api exception: %s", exc)

        # Prioridad 2: URI de Spotify para abrir búsqueda en cliente.
        uri = f"spotify:search:{quote_plus(q)}"
        opened_uri = self.actions.open_website(uri)
        if opened_uri.get("status") == "ok":
            log.info("[ORCHESTRATOR] Fallback route used: spotify_uri_search")
            return f"Buscando {q or utt} en Spotify..."

        # Prioridad 3: Web de Spotify como último fallback.
        web_url = f"https://open.spotify.com/search/{quote_plus(q or utt)}/tracks"
        self.actions.open_website(web_url)
        log.info("[ORCHESTRATOR] Fallback route used: spotify_web_search")
        # Robustez adicional: si no era música, intentar como aplicación.
        app_attempt = self.actions.open_app(q or utt)
        if app_attempt.get("status") == "ok":
            return app_attempt.get("message", f"Abrí {(q or utt)} como aplicación.")
        return "No encontré esa app o canción, ¿te refieres a otra cosa?"

    def _route_search_in_app(self, app_name: str, query: str) -> str:
        app = (app_name or "").strip().lower()
        q = (query or "").strip()
        if not app or not q:
            return "Necesito app y término de búsqueda para completar esa acción."

        if app == "steam":
            self.actions.open_app("steam")
            steam_uri = f"steam://openurl/https://store.steampowered.com/search/?term={quote_plus(q)}"
            result = self.actions.open_website(steam_uri)
            if result.get("status") == "ok":
                log.info("[ORCHESTRATOR] Route: steam_in_app_search")
                return f"Abrí Steam y ejecuté la búsqueda interna de {q}."
            self.actions.open_website(f"https://store.steampowered.com/search/?term={quote_plus(q)}")
            log.info("[ORCHESTRATOR] Fallback: steam_web_search")
            return f"Abrí Steam Store con la búsqueda de {q}."

        if app == "spotify":
            return self._route_play_music(q, preferred_app="spotify")

        self.actions.open_app(app)
        # Fallback genérico para apps sin integración específica.
        self.actions.open_website(f"https://www.google.com/search?q={quote_plus(q)}")
        log.info("[ORCHESTRATOR] Fallback: generic_web_search_for_app=%s", app)
        return f"Abrí {app}; no tengo búsqueda interna dedicada, así que abrí búsqueda de apoyo para {q}."

    def _route_screen_comprehension(self, text: str) -> str:
        prompt = text.strip()
        result = self.vision.analyze_screen(prompt=prompt)
        if result.get("status") != "ok":
            return result.get("message", "No pude analizar la pantalla.")
        model = result.get("model", "modelo de visión")
        return f"[Visión {model}] {result.get('message', '').strip()}"

    def _route_organize_directory(self, entity: str, text: str) -> str:
        target = (entity or "").strip()
        if not target:
            target = self._extract_directory_target(text)
        if not target:
            target = "~/Downloads"

        plan = self.actions.plan_directory_organization(target)
        if plan.get("status") != "ok":
            return str(plan.get("message", "No pude preparar la organización."))

        moves = plan.get("moves", [])
        if not isinstance(moves, list) or not moves:
            return str(plan.get("message", "No hay archivos para organizar."))

        self._pending_organization_plan = plan
        preview = self._summarize_move_plan(moves)
        return (
            f"{plan.get('message', 'Plan preparado.')} {preview} "
            "¿Procedo con el movimiento real? Responde sí o no."
        )

    @staticmethod
    def _extract_directory_target(text: str) -> str:
        cleaned = re.sub(r"^\s*(organiza|ordena|clasifica|limpia)\s+", "", text, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^(la\s+carpeta|carpeta|directorio)\s+", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned.strip(" .")

    @staticmethod
    def _summarize_move_plan(moves: list[Any]) -> str:
        by_bucket: dict[str, int] = {}
        for move in moves:
            if not isinstance(move, dict):
                continue
            bucket = str(move.get("bucket", "")).strip() or "otros"
            by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
        if not by_bucket:
            return ""
        chunks = [f"{count} {bucket.lower()}" for bucket, count in sorted(by_bucket.items())]
        return "Voy a mover " + ", ".join(chunks) + "."

    def _route_create_presentation(self, text: str) -> str:
        lowered = (text or "").lower()
        slides_match = re.search(r"(\d+)\s+diaposit", lowered)
        slide_count = int(slides_match.group(1)) if slides_match else 5
        topic = re.sub(r".*sobre\s+", "", text, flags=re.IGNORECASE).strip(" .")
        if not topic:
            topic = "Tema general"
        safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "_", topic)[:40]
        output = str(Path("data") / "exports" / f"presentacion_{safe_topic}.pptx")
        result = create_presentation(topic=topic, slides=slide_count, output_path=output)
        if result.get("status") == "ok":
            return f"Presentación creada: {result.get('message')}"
        return f"No pude crear la presentación: {result.get('message', 'error desconocido')}"

    def persist(self, user_text: str, answer: str, record_behavior: bool = True) -> None:
        self.memory.add_history(user_text, answer)
        importance = 1
        tags: list[str] = ["interaction"]
        low = (user_text or "").lower()
        if any(k in low for k in ("me llamo", "mi nombre", "soy ", "recuerda que")):
            importance = 5
            tags.append("identity")
        elif "?" in low:
            importance = 2
            tags.append("question")
        self.memory.save_long_term_memory(user_text, answer, tags=tags, importance=importance)
        if not record_behavior:
            return
        try:
            parsed = parse_command(user_text)
            self.memory.record_behavior_event(parsed.intent, parsed.entity, user_text)
        except Exception:
            pass

    @staticmethod
    def _parse_trigger_chat_request(text: str) -> dict[str, Any] | None:
        low = (text or "").strip().lower()
        m = re.search(
            r"(?:crear disparador:|cada vez que diga)\s*[\"']?(.+?)[\"']?\s+(?:abre spotify y reproduce|reproduce)\s+(.+)$",
            low,
        )
        if not m:
            return None
        phrase = normalize_phrase(m.group(1))
        target = m.group(2).strip()
        if not phrase or not target:
            return None
        action_type = "play_spotify"
        payload = {"query": target}
        if "youtube" in target or "video" in target:
            action_type = "play_youtube"
            payload = {"query": target}
        return {
            "phrase": phrase,
            "match_type": "fuzzy",
            "action_type": action_type,
            "action_payload": payload,
            "require_confirm": True,
        }

    def _execute_trigger_action(self, trigger: dict[str, Any]) -> str:
        action_type = str(trigger.get("action_type", "")).strip()
        payload = trigger.get("action_payload", {})
        if not isinstance(payload, dict):
            payload = {}
        if action_type == "play_spotify":
            q = str(payload.get("query", "")).strip()
            return self._route_play_music(q or "música")
        if action_type == "play_youtube":
            q = str(payload.get("query", "")).strip()
            return self._route_play_youtube(q or "video") or "No pude abrir YouTube."
        if action_type == "open_app":
            app = str(payload.get("app", "")).strip()
            r = self.actions.open_app(app)
            return r.get("message", f"Abrí {app}.")
        if action_type == "URL Viewer":
            url = str(payload.get("url", "")).strip()
            parsed = url.lower()
            if not (parsed.startswith("http://") or parsed.startswith("https://")):
                return "URL inválida."
            self.actions.open_website(url)
            return f"Abrí {url}"
        if action_type == "run_script":
            if not config.TRIGGERS_ALLOW_RUN_SCRIPTS:
                return "run_script deshabilitado por configuración."
            script = Path(str(payload.get("script", "")).strip())
            approved = (config.BASE_DIR / "scripts" / "approved").resolve()
            try:
                if approved not in script.resolve().parents:
                    return "Script fuera de directorio aprobado."
            except Exception:
                return "Ruta de script inválida."
            result = self.actions.run_shell_command(f'python "{script}"')
            return result.get("message", "Script ejecutado.")
        return "Acción de trigger no soportada."

    def _route_play_youtube(self, utterance: str, intent_kind: str) -> tuple[str, str, dict[str, Any] | None]:
        urls = extract_youtube_candidates_from_text(utterance)
        if intent_kind == "play_youtube_url" and urls:
            direct = urls[0]
            if not validate_youtube_url(str(direct.get("url", ""))):
                return "La URL de YouTube no pasó validación.", "play_youtube_url", None
            meta = fetch_youtube_oembed(str(direct.get("url", "")))
            cand = {
                "url": str(direct.get("url", "")).strip(),
                "video_id": str(direct.get("video_id", "")).strip(),
                "title": meta.get("title") or str(direct.get("title", "Video de YouTube")),
                "channel": meta.get("channel") or str(direct.get("channel", "unknown")),
                "thumbnail": meta.get("thumbnail") or str(direct.get("thumbnail", "")),
                "duration": "",
                "confidence": "0.99",
                "source": "url",
            }
            self._pending_youtube_query = utterance
            require_confirm = bool(getattr(config, "YT_REQUIRE_CONFIRM", True))
            if not require_confirm:
                self._release_ollama_for_low_ram()
                webbrowser.open(cand["url"])
                self._log_youtube_search(utterance, [cand], cand, "opened", "url")
                return f"Abriendo YouTube: {cand['url']}", "play_youtube_url", {"youtube_candidates": [cand], "tts": self._youtube_tts_summary([cand])}
            self._pending_youtube_confirm = cand
            return (
                f"Encontré este video: {cand['title']} ({cand['channel']}). ¿Quieres que lo reproduzca? (Sí/No)",
                "play_youtube_url",
                {"youtube_candidates": [cand], "tts": self._youtube_tts_summary([cand])},
            )

        query = re.sub(r"^(reproduce|muestrame un video de|muéstrame un video de|abre un video de)\s+", "", utterance, flags=re.I).strip()
        if intent_kind == "channel_lookup":
            query = query or utterance.replace("reproduce", "").strip()
            cands = channel_lookup_candidates(query)
            source = "channel_lookup"
        else:
            cands = search_youtube_candidates(query or utterance)
            source = "search_youtube_query"
        cands = [c for c in cands if validate_youtube_url(str(c.get("url", "")))]
        if not cands:
            self._log_youtube_search(utterance, [], None, "ignored", source)
            return "No encontré resultados de YouTube válidos para esa consulta.", source, None

        self._pending_youtube_query = query or utterance
        top = cands[:5]
        self._pending_youtube_options = top
        top_conf = float(str(top[0].get("confidence", "0.0")))
        # Modo transparente: siempre presentar opciones y pedir elección explícita.
        auto_open = False
        conf_min = float(getattr(config, "YT_AUTO_OPEN_CONF", 0.95))
        auto_skip_memes = bool(getattr(config, "YT_AUTO_SKIP_KNOWN_MEMES", False))
        suspicious = is_suspicious_result_for_query(
            self._pending_youtube_query,
            str(top[0].get("title", "")),
            str(top[0].get("channel", "")),
        )
        if auto_open and top_conf >= conf_min and not (auto_skip_memes and suspicious):
            chosen = dict(top[0])
            self._pending_youtube_options = []
            self._release_ollama_for_low_ram()
            webbrowser.open(str(chosen.get("url", "")))
            self._log_youtube_search(self._pending_youtube_query, top, chosen, "opened", str(chosen.get("source", source)))
            return f"Auto-open habilitado. Abriendo: {chosen.get('title','video')}", source, {"youtube_candidates": top, "tts": self._youtube_tts_summary(top)}

        lines = [
            f"{i+1}) {c.get('title','video')} — {c.get('channel','canal')} (conf {c.get('confidence','0.0')})"
            for i, c in enumerate(top)
        ]
        answer = "He encontrado estos videos:\n" + "\n".join(lines) + "\nElige 1/2/3. ¿Cuál abro?"
        if intent_kind == "channel_lookup":
            answer = (
                "Encontré videos del creador/canal solicitado. Opciones: último video, más popular o top-5.\n"
                + "\n".join(lines)
                + "\nElige 1/2/3. ¿Cuál abro?"
            )
        return answer, source, {"youtube_candidates": top, "tts": self._youtube_tts_summary(top)}

    def _release_ollama_for_low_ram(self) -> None:
        releaser = getattr(self.core, "_maybe_release_ollama_memory", None)
        if callable(releaser):
            try:
                releaser(force=True)
            except Exception:
                pass

    @staticmethod
    def _youtube_tts_summary(cands: list[dict[str, str]]) -> str:
        if not cands:
            return "No encontré videos para esa consulta."
        head = cands[:3]
        parts = [f"{i+1}: {c.get('title','video')} de {c.get('channel','canal')}" for i, c in enumerate(head)]
        return f"He encontrado {len(cands)} videos. " + ". ".join(parts) + ". ¿Cuál abro?"

    def _log_youtube_search(
        self,
        user_query: str,
        top_candidates: list[dict[str, Any]],
        chosen_video: dict[str, Any] | None,
        action: str,
        source: str,
    ) -> None:
        row = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "user_query": (user_query or "")[:280],
            "top_candidates": [
                {
                    "video_id": str(c.get("video_id", "")),
                    "title": str(c.get("title", ""))[:180],
                    "channel": str(c.get("channel", ""))[:120],
                    "confidence": str(c.get("confidence", "")),
                }
                for c in (top_candidates or [])[:5]
            ],
            "chosen_video": (
                {
                    "video_id": str(chosen_video.get("video_id", "")),
                    "title": str(chosen_video.get("title", ""))[:180],
                    "channel": str(chosen_video.get("channel", ""))[:120],
                }
                if chosen_video
                else None
            ),
            "action": action,
            "source": source,
        }
        try:
            self._youtube_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._youtube_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _handle_volume(self, text: str) -> str:
        low = (text or "").lower()
        if any(word in low for word in ["mutea", "mutear", "silencia", "silenciar"]):
            result = self.actions.set_mute(True)
            return result.get("message", "No pude silenciar el audio.")
        if any(word in low for word in ["desmutea", "desmutear", "quita el mute", "activar sonido", "reactivar sonido"]):
            result = self.actions.set_mute(False)
            return result.get("message", "No pude reactivar el audio.")

        number_match = re.search(r"(\d{1,3})", low)
        if number_match:
            target = int(number_match.group(1))
            result = self.actions.set_volume(target)
            return result.get("message", "Volumen ajustado.")

        if "sube" in low or "subir" in low:
            delta_match = re.search(r"(\d{1,2})", low)
            delta = int(delta_match.group(1)) if delta_match else 10
            result = self.actions.adjust_volume(delta)
            return result.get("message", f"Volumen aumentado {delta}%.")

        if "baja" in low or "bajar" in low:
            delta_match = re.search(r"(\d{1,2})", low)
            delta = int(delta_match.group(1)) if delta_match else 10
            result = self.actions.adjust_volume(-delta)
            return result.get("message", f"Volumen reducido {delta}%.")

        result = self.actions.set_volume(50)
        return result.get("message", "Volumen ajustado a 50%.")

    def _handle_brightness(self, text: str) -> str:
        low = (text or "").lower()
        number_match = re.search(r"(\d{1,3})", low)
        if number_match:
            target = int(number_match.group(1))
            result = self.actions.set_brightness(target)
            return result.get("message", "Brillo ajustado.")

        if "sube" in low or "subir" in low:
            delta_match = re.search(r"(\d{1,2})", low)
            delta = int(delta_match.group(1)) if delta_match else 10
            result = self.actions.adjust_brightness(delta)
            return result.get("message", f"Brillo aumentado {delta}%.")

        if "baja" in low or "bajar" in low:
            delta_match = re.search(r"(\d{1,2})", low)
            delta = int(delta_match.group(1)) if delta_match else 10
            result = self.actions.adjust_brightness(-delta)
            return result.get("message", f"Brillo reducido {delta}%.")

        result = self.actions.set_brightness(70)
        return result.get("message", "Brillo ajustado a 70%.")

