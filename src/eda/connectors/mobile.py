"""Conector móvil (estructura preparada, desactivado por defecto)."""

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


class MobileConnector:
    def __init__(self, config_obj: MobileConnectorConfig | None = None, config_file: Path | None = None) -> None:
        self.config_file = config_file or (config.CONFIG_DIR / "mobile_connector.json")
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config = config_obj or self._load_config()

    def _load_config(self) -> MobileConnectorConfig:
        data = safe_json_load(self.config_file, {})
        return MobileConnectorConfig(
            enabled=bool(data.get("enabled", False)),
            provider=str(data.get("provider", "disabled")),
            telegram_chat_id=str(data.get("telegram_chat_id", "")),
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

    def save_opt_in(self, provider: str, token: str, telegram_chat_id: str = "") -> None:
        payload = {
            "enabled": True,
            "provider": provider.strip().lower(),
            "telegram_chat_id": telegram_chat_id.strip(),
            "token_encrypted": encrypt_secret(token, label="mobile_token"),
        }
        safe_json_save(self.config_file, payload)
        self.config = self._load_config()

    def enviar_mensaje(self, texto: str) -> dict[str, str]:
        if not self.config.enabled:
            return {"status": "disabled", "message": "Conector móvil desactivado."}
        token = self._load_token()
        if not token:
            return {"status": "error", "message": "No hay token configurado para el conector móvil."}
        if self.config.provider == "telegram":
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
        if self.config.provider == "pushbullet":
            url = "https://api.pushbullet.com/v2/pushes"
            headers = {"Access-Token": token, "Content-Type": "application/json"}
            try:
                response = requests.post(url, headers=headers, json={"type": "note", "title": "EDA", "body": texto[:2000]}, timeout=8)
                if response.status_code >= 400:
                    return {"status": "error", "message": f"Pushbullet error {response.status_code}"}
                return {"status": "ok", "message": "Mensaje enviado a Pushbullet."}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}
        return {"status": "error", "message": f"Proveedor '{self.config.provider}' no soportado."}

