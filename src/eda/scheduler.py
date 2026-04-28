"""Compatibilidad de recordatorios sobre BackgroundReminderWorker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
import time
import unicodedata
from typing import Callable, Dict, List, Optional

from .background_tasks import BackgroundReminderWorker

# TaskScheduler queda sólo por compatibilidad API.
class TaskScheduler:
    def __init__(self) -> None:
        self.running = False
        self.jobs: List[str] = []

    def every_minutes(self, minutes: int, task: Callable[[], None], tag: str = "") -> None:
        self.jobs.append(tag or f"cada_{minutes}_min")

    def every_day_at(self, hour_minute: str, task: Callable[[], None], tag: str = "") -> None:
        self.jobs.append(tag or f"diaria_{hour_minute}")

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


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
    """Facade legacy que delega a BackgroundReminderWorker (canonical)."""

    def __init__(self, on_due: Callable[[Dict[str, str]], None]) -> None:
        self._worker = BackgroundReminderWorker(on_due=on_due)

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()

    def add(self, request: ReminderRequest) -> Dict[str, str]:
        message = request.message.strip() or "tienes un recordatorio pendiente."
        due_ts = request.remind_at.timestamp()
        reminder_id = self._worker.add_reminder(message, due_ts)
        return {
            "id": str(reminder_id),
            "message": message,
            "scheduled_for": request.remind_at.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": request.mode,
        }

    def add_existing(self, reminder_payload: Dict[str, str]) -> bool:
        return self._worker.add_existing(reminder_payload)

    def list_pending(self) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for item in self._worker.list_reminders():
            due = str(item.get("due_ts", "")).strip()
            scheduled = ""
            if due:
                try:
                    scheduled = datetime.fromtimestamp(float(due)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    scheduled = due
            out.append(
                {
                    "id": str(item.get("id", "")),
                    "message": str(item.get("message", "")),
                    "scheduled_for": scheduled,
                    "mode": "relative",
                }
            )
        return out

    def cancel(self, reminder_id: str) -> bool:
        rid = str(reminder_id or "").strip()
        if not rid.isdigit():
            return False
        return self._worker.cancel_reminder(int(rid))

    def clear_all(self) -> None:
        self._worker.clear_all()
