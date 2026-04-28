"""Conector Telegram para notificaciones y control remoto seguro."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from .. import config
from ..utils import safe_json_load, safe_json_save
from ..utils.security import decrypt_secret, encrypt_secret


@dataclass
class MobileConnectorConfig:
    enabled: bool = False
    provider: str = "disabled"  # telegram | pushbullet | whatsapp
    telegram_chat_id: str = ""


class TelegramConnector:
    def __init__(self, config_obj: MobileConnectorConfig | None = None, config_file: Path | None = None) -> None:
        self.config_file = config_file or (config.CONFIG_DIR / "mobile_connector.json")
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config = config_obj or self._load_config()

    def _load_config(self) -> MobileConnectorConfig:
        data = safe_json_load(self.config_file, {})
        chat_id = str(data.get("telegram_chat_id", ""))
        if not chat_id:
            encrypted_chat = str(data.get("telegram_chat_id_encrypted", "")).strip()
            if encrypted_chat:
                try:
                    chat_id = decrypt_secret(encrypted_chat, label="mobile_chat_id")
                except Exception:
                    chat_id = ""
        return MobileConnectorConfig(
            enabled=bool(data.get("enabled", False)),
            provider=str(data.get("provider", "disabled")),
            telegram_chat_id=chat_id,
        )

    def _load_token(self) -> str:
        data = safe_json_load(self.config_file, {})
        encrypted = str(data.get("token_encrypted", "")).strip()
        if not encrypted:
            return ""
        try:
            return decrypt_secret(encrypted, label="mobile_token")
        except Exception:
            return ""

    def save_opt_in(self, token: str, telegram_chat_id: str) -> None:
        payload = {
            "enabled": True,
            "provider": "telegram",
            "telegram_chat_id_encrypted": encrypt_secret(telegram_chat_id.strip(), label="mobile_chat_id"),
            "token_encrypted": encrypt_secret(token, label="mobile_token"),
        }
        safe_json_save(self.config_file, payload)
        self.config = self._load_config()

    def get_owner_chat_id(self) -> str:
        return (self.config.telegram_chat_id or "").strip()

    def enviar_mensaje(self, texto: str) -> dict[str, str]:
        if not self.config.enabled:
            return {"status": "disabled", "message": "Conector móvil desactivado."}
        token = self._load_token()
        if not token:
            return {"status": "error", "message": "No hay token configurado para el conector móvil."}
        if not self.config.telegram_chat_id:
            return {"status": "error", "message": "Falta telegram_chat_id para Telegram."}
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={"chat_id": self.config.telegram_chat_id, "text": texto[:4000]},
                timeout=8,
            )
            if response.status_code >= 400:
                return {"status": "error", "message": f"Telegram error {response.status_code}"}
            return {"status": "ok", "message": "Mensaje enviado a Telegram."}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def fetch_updates(self, offset: int = 0) -> dict:
        """Lee updates del bot y filtra por chat_id dueño."""
        token = self._load_token()
        if not self.config.enabled or not token:
            return {"status": "disabled", "updates": [], "next_offset": offset}
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            resp = requests.get(url, params={"offset": offset, "timeout": 0}, timeout=8)
            if resp.status_code >= 400:
                return {"status": "error", "updates": [], "next_offset": offset}
            payload = resp.json()
            result = payload.get("result") or []
            updates = []
            next_offset = offset
            for item in result:
                if not isinstance(item, dict):
                    continue
                update_id = int(item.get("update_id", 0))
                next_offset = max(next_offset, update_id + 1)
                msg = item.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                text = str(msg.get("text", "")).strip()
                if chat_id and text and chat_id == str(self.config.telegram_chat_id):
                    updates.append({"chat_id": chat_id, "text": text, "update_id": update_id})
            return {"status": "ok", "updates": updates, "next_offset": next_offset}
        except Exception:
            return {"status": "error", "updates": [], "next_offset": offset}


class MobileConnector(TelegramConnector):
    """Compatibilidad retroactiva: MobileConnector alias de TelegramConnector."""

