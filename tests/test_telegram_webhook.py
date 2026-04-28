from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eda.webhook.telegram_webhook import create_app


class _FakeConnector:
    def __init__(self, owner_chat_id: str) -> None:
        self._owner_chat_id = owner_chat_id

    def get_owner_chat_id(self) -> str:
        return self._owner_chat_id


class TelegramWebhookTests(unittest.TestCase):
    def test_rejects_without_secret_header(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.jsonl"
            audit = Path(td) / "audit.jsonl"
            app = create_app(
                telegram_connector=_FakeConnector("123"),
                queue_path=queue,
                audit_path=audit,
                secret_token="secret123",
            )
            client = app.test_client()
            resp = client.post("/telegram/webhook", json={"message": {"chat": {"id": "123"}, "text": "estado"}})
            self.assertEqual(resp.status_code, 401)
            self.assertFalse(queue.exists())
            self.assertTrue(audit.exists())

    def test_ignores_non_owner_chat_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.jsonl"
            audit = Path(td) / "audit.jsonl"
            app = create_app(
                telegram_connector=_FakeConnector("123"),
                queue_path=queue,
                audit_path=audit,
                secret_token="secret123",
            )
            client = app.test_client()
            resp = client.post(
                "/telegram/webhook",
                json={"message": {"chat": {"id": "999"}, "text": "estado"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "secret123"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(queue.exists(), "No debe encolar comandos de chat no dueño.")
            self.assertTrue(audit.exists())

    def test_writes_queue_and_audit_for_owner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.jsonl"
            audit = Path(td) / "audit.jsonl"
            app = create_app(
                telegram_connector=_FakeConnector("123"),
                queue_path=queue,
                audit_path=audit,
                secret_token="secret123",
            )
            client = app.test_client()
            payload = {"message": {"chat": {"id": "123"}, "text": "organiza descargas"}}
            resp = client.post(
                "/telegram/webhook",
                data=json.dumps(payload),
                content_type="application/json",
                headers={"X-Telegram-Bot-Api-Secret-Token": "secret123"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(queue.exists())
            qline = queue.read_text(encoding="utf-8").strip().splitlines()[-1]
            qobj = json.loads(qline)
            self.assertEqual(qobj.get("action_name"), "organiza")
            self.assertIn("raw_payload_hash", qobj)
            self.assertNotIn("message", qline.lower())
            self.assertTrue(audit.exists())


if __name__ == "__main__":
    unittest.main()

