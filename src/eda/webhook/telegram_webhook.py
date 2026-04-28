"""Micro-servicio Flask para recibir webhooks de Telegram."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import config

try:
    from flask import Flask, jsonify, request
except Exception:
    Flask = None  # type: ignore[assignment]
    jsonify = None  # type: ignore[assignment]
    request = None  # type: ignore[assignment]


def _obfuscate_chat_id(chat_id: str) -> str:
    text = (chat_id or "").strip()
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}****{text[-2:]}"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def create_app(
    *,
    telegram_connector: Any,
    queue_path: Path | None = None,
    audit_path: Path | None = None,
    secret_token: str = "",
):
    if Flask is None:
        raise RuntimeError("Flask no disponible. Instala flask para modo webhook.")
    app = Flask(__name__)
    queue_file = queue_path or (config.DATA_DIR / "queue" / "telegram_queue.jsonl")
    audit_file = audit_path or (config.DATA_DIR / "logs" / "telegram_webhook_audit.jsonl")
    configured_secret = (secret_token or config.TELEGRAM_WEBHOOK_SECRET or "").strip()

    @app.post("/telegram/webhook")
    def telegram_webhook():
        ts = datetime.now().isoformat(timespec="seconds")
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        raw_payload = request.get_data() or b""
        payload_hash = hashlib.sha256(raw_payload).hexdigest()

        if not configured_secret or header_secret != configured_secret:
            _append_jsonl(
                audit_file,
                {
                    "timestamp": ts,
                    "chat_id": "***",
                    "action_name": "unknown",
                    "raw_payload_hash": payload_hash,
                    "outcome": "rejected",
                    "reason": "invalid_secret",
                },
            )
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        payload = request.get_json(silent=True) or {}
        msg = payload.get("message") if isinstance(payload, dict) else {}
        if not isinstance(msg, dict):
            msg = {}
        chat = msg.get("chat") if isinstance(msg, dict) else {}
        if not isinstance(chat, dict):
            chat = {}
        chat_id = str(chat.get("id", "")).strip()
        owner_chat_id = str(getattr(telegram_connector, "get_owner_chat_id", lambda: "")()).strip()
        text = str(msg.get("text", "")).strip()
        action_name = text.split()[0].lower() if text else "empty"

        if not chat_id or not owner_chat_id or chat_id != owner_chat_id:
            _append_jsonl(
                audit_file,
                {
                    "timestamp": ts,
                    "chat_id": _obfuscate_chat_id(chat_id),
                    "action_name": action_name,
                    "raw_payload_hash": payload_hash,
                    "outcome": "rejected",
                    "reason": "chat_not_allowed",
                },
            )
            return jsonify({"ok": True, "ignored": True}), 200

        # Encolar comando sin payload en claro.
        queue_item = {
            "timestamp": ts,
            "source": "telegram_webhook",
            "chat_id": chat_id,
            "chat_id_obfuscated": _obfuscate_chat_id(chat_id),
            "command_text": text[:1000],
            "action_name": action_name,
            "raw_payload_hash": payload_hash,
        }
        _append_jsonl(queue_file, queue_item)
        _append_jsonl(
            audit_file,
            {
                "timestamp": ts,
                "chat_id": _obfuscate_chat_id(chat_id),
                "action_name": action_name,
                "raw_payload_hash": payload_hash,
                "outcome": "accepted",
            },
        )
        return jsonify({"ok": True}), 200

    return app


def start_webhook_thread(*, telegram_connector: Any, host: str | None = None, port: int | None = None):
    app = create_app(telegram_connector=telegram_connector)
    bind_host = host or config.TELEGRAM_WEBHOOK_HOST
    bind_port = int(port or config.TELEGRAM_WEBHOOK_PORT)

    def _runner() -> None:
        app.run(host=bind_host, port=bind_port, debug=False, use_reloader=False)

    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    return th

