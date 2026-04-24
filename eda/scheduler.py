"""Programador de tareas y recordatorios para E.D.A."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import itertools
import re
import threading
import time
import unicodedata
from typing import Callable, Dict, List, Optional

from .logger import get_logger

log = get_logger("scheduler")

try:
    import schedule
except Exception:
    schedule = None


class TaskScheduler:
    """Encapsula la librería schedule en un hilo daemon."""

    def __init__(self) -> None:
        self.running = False
        self.thread: threading.Thread | None = None
        self.jobs: List[str] = []

    def every_minutes(self, minutes: int, task: Callable[[], None], tag: str = "") -> None:
        if schedule is None:
            return
        schedule.every(minutes).minutes.do(task)
        self.jobs.append(tag or f"cada_{minutes}_min")

    def every_day_at(self, hour_minute: str, task: Callable[[], None], tag: str = "") -> None:
        if schedule is None:
            return
        schedule.every().day.at(hour_minute).do(task)
        self.jobs.append(tag or f"diaria_{hour_minute}")

    def start(self) -> None:
        if self.running or schedule is None:
            return
        self.running = True

        def run_loop() -> None:
            log.info("Scheduler iniciado")
            while self.running:
                schedule.run_pending()
                time.sleep(1)
            log.info("Scheduler detenido")

        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if schedule is not None:
            schedule.clear()


@dataclass
class ReminderRequest:
    """Estructura normalizada de un recordatorio parseado desde texto libre."""

    remind_at: datetime
    message: str
    original_text: str
    mode: str  # "relative" | "absolute"


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def parse_reminder_request(text: str, now: Optional[datetime] = None) -> Optional[ReminderRequest]:
    """
    Parsea frases como:
    - "recuérdame en una hora"
    - "recuérdame en 20 min de estudiar"
    - "recuérdame a las 3 de la tarde de empezar mi proyecto"
    """
    raw = (text or "").strip()
    if not raw:
        return None

    now = now or datetime.now()
    normalized = _strip_accents(raw.lower())

    if "recuerdame" not in normalized and "recordatorio" not in normalized:
        return None

    relative_match = re.search(
        r"\ben\s+(un\s+ratito|media\s+hora|una\s+hora|un\s+minuto|un\s+hora|\d+\s*(?:seg|segundo|segundos|min|minuto|minutos|hora|horas))\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if relative_match:
        amount_text = relative_match.group(1).strip()
        delta_minutes = 0
        if amount_text == "un ratito":
            delta_minutes = 10
        elif amount_text == "media hora":
            delta_minutes = 30
        elif amount_text == "una hora":
            delta_minutes = 60
        elif amount_text == "un minuto":
            delta_minutes = 1
        elif amount_text == "un hora":
            delta_minutes = 60
        else:
            num_match = re.search(r"(\d+)", amount_text)
            unit_match = re.search(r"(seg|segundo|segundos|min|minuto|minutos|hora|horas)", amount_text)
            if not num_match or not unit_match:
                return None
            value = int(num_match.group(1))
            unit = unit_match.group(1)
            if unit.startswith("seg"):
                delta_minutes = max(1, int(round(value / 60)))
            elif unit.startswith("min"):
                delta_minutes = value
            else:
                delta_minutes = value * 60

        if delta_minutes <= 0:
            return None

        # Cola tras la ventana temporal ("... en 5 min de tomar agua", "... en 20 min que revise").
        tail = normalized[relative_match.end() :].strip(" .,:;")
        if tail.startswith("de "):
            tail = tail[3:].strip()
        elif tail.startswith("que "):
            tail = tail[4:].strip()

        # Cuerpo antes de "en ..." ("recuérdame tomar agua en un minuto", "... apagar la música en un minuto").
        head = normalized[: relative_match.start()].strip()
        head = re.sub(r"^(?:recuerdame|recordatorio)\b\s*", "", head, flags=re.IGNORECASE).strip()

        if head:
            message = head.strip(" ,.;:") or "tienes un recordatorio pendiente."
        elif tail:
            message = tail
        else:
            message = "tienes un recordatorio pendiente."
        remind_at = now + timedelta(minutes=delta_minutes)
        return ReminderRequest(remind_at=remind_at, message=message, original_text=raw, mode="relative")

    absolute_match = re.search(
        r"\ba\s+las\s+(\d{1,2})(?::(\d{1,2}))?\s*(am|pm|de la manana|de la tarde|de la noche)?\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if absolute_match:
        hour = int(absolute_match.group(1))
        minute = int(absolute_match.group(2) or "0")
        period = (absolute_match.group(3) or "").strip()

        if minute < 0 or minute > 59:
            return None

        if period in {"pm", "de la tarde", "de la noche"} and hour < 12:
            hour += 12
        if period in {"am", "de la manana"} and hour == 12:
            hour = 0
        if hour > 23:
            return None

        remind_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if remind_at <= now:
            remind_at = remind_at + timedelta(days=1)

        tail = normalized[absolute_match.end() :].strip(" .,:;")
        if tail.startswith("de "):
            tail = tail[3:].strip()
        elif tail.startswith("que "):
            tail = tail[4:].strip()

        message = tail or "tienes un recordatorio pendiente."
        return ReminderRequest(remind_at=remind_at, message=message, original_text=raw, mode="absolute")

    return None


class ReminderScheduler:
    """Scheduler simple de recordatorios one-shot, sin dependencias externas."""

    def __init__(self, on_due: Callable[[Dict[str, str]], None]) -> None:
        self._on_due = on_due
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._id_seq = itertools.count(1)
        self._reminders: List[Dict[str, str | float]] = []

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        def loop() -> None:
            log.info("ReminderScheduler iniciado")
            while self._running:
                due_batch: List[Dict[str, str | float]] = []
                now_ts = time.time()
                with self._lock:
                    pending: List[Dict[str, str | float]] = []
                    for item in self._reminders:
                        if float(item["due_ts"]) <= now_ts:
                            due_batch.append(item)
                        else:
                            pending.append(item)
                    self._reminders = pending

                for due in due_batch:
                    payload = {
                        "id": str(due["id"]),
                        "message": str(due["message"]),
                        "scheduled_for": str(due["scheduled_for"]),
                    }
                    try:
                        self._on_due(payload)
                    except Exception as exc:
                        log.error("Error ejecutando recordatorio %s: %s", payload["id"], exc)
                time.sleep(1.0)
            log.info("ReminderScheduler detenido")

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def add(self, request: ReminderRequest) -> Dict[str, str]:
        reminder_id = str(next(self._id_seq))
        reminder = {
            "id": reminder_id,
            "message": request.message.strip() or "tienes un recordatorio pendiente.",
            "scheduled_for": request.remind_at.strftime("%Y-%m-%d %H:%M:%S"),
            "due_ts": request.remind_at.timestamp(),
            "mode": request.mode,
        }
        with self._lock:
            self._reminders.append(reminder)
        return {
            "id": reminder_id,
            "message": str(reminder["message"]),
            "scheduled_for": str(reminder["scheduled_for"]),
            "mode": request.mode,
        }

    def add_existing(self, reminder_payload: Dict[str, str]) -> Optional[Dict[str, str]]:
        """Restaura recordatorio persistido (si aún no expiró)."""
        try:
            reminder_id = str(reminder_payload.get("id", "")).strip() or str(next(self._id_seq))
            message = str(reminder_payload.get("message", "")).strip() or "tienes un recordatorio pendiente."
            scheduled_for = str(reminder_payload.get("scheduled_for", "")).strip()
            mode = str(reminder_payload.get("mode", "relative")).strip() or "relative"
            if not scheduled_for:
                return None
            remind_at = datetime.strptime(scheduled_for, "%Y-%m-%d %H:%M:%S")
            due_ts = remind_at.timestamp()
            if due_ts <= time.time():
                return None
            reminder = {
                "id": reminder_id,
                "message": message,
                "scheduled_for": scheduled_for,
                "due_ts": due_ts,
                "mode": mode,
            }
            with self._lock:
                self._reminders.append(reminder)
            return {"id": reminder_id, "message": message, "scheduled_for": scheduled_for, "mode": mode}
        except Exception:
            return None

    def list_pending(self) -> List[Dict[str, str]]:
        """Lista recordatorios pendientes ordenados por fecha."""
        with self._lock:
            items = sorted(self._reminders, key=lambda x: float(x["due_ts"]))
            return [
                {
                    "id": str(item["id"]),
                    "message": str(item["message"]),
                    "scheduled_for": str(item["scheduled_for"]),
                    "mode": str(item["mode"]),
                }
                for item in items
            ]

    def cancel(self, reminder_id: str) -> bool:
        """Cancela un recordatorio por ID."""
        rid = str(reminder_id or "").strip()
        if not rid:
            return False
        with self._lock:
            before = len(self._reminders)
            self._reminders = [item for item in self._reminders if str(item.get("id")) != rid]
            return len(self._reminders) < before

    def clear_all(self) -> None:
        """Elimina todos los recordatorios pendientes."""
        with self._lock:
            self._reminders = []
