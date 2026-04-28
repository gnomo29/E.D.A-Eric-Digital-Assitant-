"""Gestor OTP temporal para confirmar comandos críticos remotos."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass
class OTPChallenge:
    chat_id: str
    command: str
    otp_hash: str
    expires_at: datetime
    failed_attempts: int = 0


class OTPManager:
    def __init__(self, ttl_seconds: int = 120) -> None:
        self.ttl_seconds = ttl_seconds
        self._challenges: dict[str, OTPChallenge] = {}
        self._failed_events: dict[str, list[datetime]] = {}
        self._last_alert: dict[str, datetime] = {}

    @staticmethod
    def _hash(chat_id: str, otp: str) -> str:
        raw = f"{chat_id}:{otp}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def issue(self, chat_id: str, command: str) -> str:
        self._purge()
        otp = f"{secrets.randbelow(1_000_000):06d}"
        expires = datetime.now() + timedelta(seconds=self.ttl_seconds)
        self._challenges[chat_id] = OTPChallenge(
            chat_id=chat_id,
            command=command,
            otp_hash=self._hash(chat_id, otp),
            expires_at=expires,
        )
        return otp

    def pending_command(self, chat_id: str) -> str:
        challenge = self._challenges.get(chat_id)
        if challenge is None:
            return ""
        if challenge.expires_at < datetime.now():
            self._challenges.pop(chat_id, None)
            return ""
        return challenge.command

    def verify(self, chat_id: str, otp: str) -> dict[str, Any]:
        self._purge()
        challenge = self._challenges.get(chat_id)
        if challenge is None:
            return {"ok": False, "reason": "no_pending_otp"}
        if challenge.expires_at < datetime.now():
            self._challenges.pop(chat_id, None)
            return {"ok": False, "reason": "otp_expired"}
        if self._hash(chat_id, otp.strip()) != challenge.otp_hash:
            challenge.failed_attempts += 1
            self._register_failed(chat_id)
            return {"ok": False, "reason": "otp_invalid"}
        command = challenge.command
        self._challenges.pop(chat_id, None)
        return {"ok": True, "command": command}

    def should_alert_failed_otp(self, chat_id: str) -> bool:
        now = datetime.now()
        events = [t for t in self._failed_events.get(chat_id, []) if now - t <= timedelta(minutes=10)]
        if len(events) < 3:
            return False
        last = self._last_alert.get(chat_id)
        if last is not None and (now - last) < timedelta(minutes=10):
            return False
        self._last_alert[chat_id] = now
        return True

    def _register_failed(self, chat_id: str) -> None:
        events = self._failed_events.setdefault(chat_id, [])
        events.append(datetime.now())
        if len(events) > 50:
            del events[:-50]

    def _purge(self) -> None:
        now = datetime.now()
        expired = [cid for cid, challenge in self._challenges.items() if challenge.expires_at < now]
        for cid in expired:
            self._challenges.pop(cid, None)
        for cid, events in list(self._failed_events.items()):
            kept = [t for t in events if now - t <= timedelta(minutes=10)]
            if kept:
                self._failed_events[cid] = kept
            else:
                self._failed_events.pop(cid, None)

