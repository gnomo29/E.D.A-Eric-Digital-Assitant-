from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eda.background_tasks import BackgroundReminderWorker
from eda.connectors.mobile import MobileConnector, TelegramConnector
from eda.orchestrator import CommandOrchestrator
from eda.plugin_loader import PluginLoader
from eda.undo_manager import UndoManager
from eda.utils.security import generate_skill_keypair, sign_file


class V3FinalTests(unittest.TestCase):
    def test_signed_skill_loads_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            skills = base / "skills"
            cfg = base / "config" / "keys"
            skills.mkdir(parents=True)
            cfg.mkdir(parents=True)
            (skills / "example.py").write_text("x = 1\n", encoding="utf-8")
            (skills / "manifest.json").write_text(json.dumps({"plugins": [{"name": "ex", "file": "example.py", "enabled": True}]}), encoding="utf-8")
            private_key = cfg / "skills_private.pem"
            public_key = cfg / "skills_public.pem"
            generate_skill_keypair(private_key, public_key)
            signatures = {
                "files": {
                    "manifest.json": sign_file(skills / "manifest.json", private_key),
                    "example.py": sign_file(skills / "example.py", private_key),
                }
            }
            (skills / "signatures.json").write_text(json.dumps(signatures), encoding="utf-8")
            with patch("eda.plugin_loader.config.CONFIG_DIR", base / "config"):
                loader = PluginLoader(plugins_dir=skills)
                loaded = loader.load_enabled()
            self.assertIn("ex", loaded)

    def test_tampered_skill_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            skills = base / "skills"
            cfg = base / "config" / "keys"
            skills.mkdir(parents=True)
            cfg.mkdir(parents=True)
            skill = skills / "example.py"
            skill.write_text("x = 1\n", encoding="utf-8")
            manifest = skills / "manifest.json"
            manifest.write_text(json.dumps({"plugins": [{"name": "ex", "file": "example.py", "enabled": True}]}), encoding="utf-8")
            private_key = cfg / "skills_private.pem"
            public_key = cfg / "skills_public.pem"
            generate_skill_keypair(private_key, public_key)
            signatures = {
                "files": {
                    "manifest.json": sign_file(manifest, private_key),
                    "example.py": sign_file(skill, private_key),
                }
            }
            (skills / "signatures.json").write_text(json.dumps(signatures), encoding="utf-8")
            skill.write_text("x = 2\n", encoding="utf-8")  # tamper
            with patch("eda.plugin_loader.config.CONFIG_DIR", base / "config"):
                loader = PluginLoader(plugins_dir=skills)
                loaded = loader.load_enabled()
            self.assertNotIn("ex", loaded)

    def test_reminders_persist_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "reminders.db"
            w1 = BackgroundReminderWorker(db_path=db)
            w1.add_reminder("Prueba", 4102444800.0)  # far future
            listed1 = w1.list_reminders()
            self.assertEqual(len(listed1), 1)
            w2 = BackgroundReminderWorker(db_path=db)
            listed2 = w2.list_reminders()
            self.assertEqual(len(listed2), 1)
            self.assertEqual(listed2[0]["message"], "Prueba")

    def test_cancel_reminder_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "reminders.db"
            w = BackgroundReminderWorker(db_path=db)
            w.add_reminder("Cancelar", 4102444800.0)
            rid = int(w.list_reminders()[0]["id"])
            self.assertTrue(w.cancel_reminder(rid))
            self.assertEqual(w.list_reminders(), [])

    def test_undo_manager_reverts_move(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "undo.db"
            manager = UndoManager(db_path=db)
            manager.record_move("C:/a.txt", "C:/b.txt")
            with patch("shutil.move") as mock_move:
                result = manager.undo_last()
            self.assertEqual(result.get("status"), "ok")
            mock_move.assert_called_once_with("C:/b.txt", "C:/a.txt")

    def test_mobile_connector_blocked_without_optin(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config_file = Path(td) / "mobile.json"
            connector = MobileConnector(config_file=config_file)
            result = connector.enviar_mensaje("hola")
            self.assertEqual(result.get("status"), "disabled")

    @patch("eda.connectors.mobile.requests.post")
    def test_telegram_send_message_mock(self, mock_post) -> None:
        mock_post.return_value = MagicMock(status_code=200)
        with tempfile.TemporaryDirectory() as td:
            config_file = Path(td) / "mobile.json"
            connector = TelegramConnector(config_file=config_file)
            connector.save_opt_in(token="123:abc", telegram_chat_id="999")
            result = connector.enviar_mensaje("estado")
        self.assertEqual(result.get("status"), "ok")
        mock_post.assert_called_once()

    def _build_orch(self) -> CommandOrchestrator:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (False, "")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        actions.undo_last_action.return_value = {"status": "ok", "message": "undo"}
        return CommandOrchestrator(memory=memory, core=core, action_agent=action_agent, actions=actions, vision=MagicMock())

    def test_orchestrator_mobile_opt_in_prompt(self) -> None:
        orch = self._build_orch()
        with patch.object(orch.mobile_connector, "config", type("C", (), {"enabled": False})()):
            result = orch.orchestrate("enviar mensaje al móvil: hola")
        self.assertEqual(result.source, "mobile_opt_in_prompt")

    @patch("eda.connectors.mobile.requests.get")
    @patch("eda.connectors.mobile.requests.post")
    def test_orchestrator_processes_owner_telegram_commands(self, mock_post, mock_get) -> None:
        mock_post.return_value = MagicMock(status_code=200)
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "ok": True,
                "result": [
                    {
                        "update_id": 10,
                        "message": {"text": "estado", "chat": {"id": "12345"}},
                    }
                ],
            },
        )
        orch = self._build_orch()
        with patch.object(orch.mobile_connector, "config", type("C", (), {"enabled": True, "telegram_chat_id": "12345"})()):
            with patch.object(orch.mobile_connector, "_load_token", return_value="tok"):
                results = orch.poll_remote_commands()
        self.assertEqual(len(results), 1)

    def test_orchestrator_mobile_opt_in_reject(self) -> None:
        orch = self._build_orch()
        with patch.object(orch.mobile_connector, "config", type("C", (), {"enabled": False})()):
            _first = orch.orchestrate("enviar mensaje al móvil: hola")
            second = orch.orchestrate("no")
        self.assertEqual(second.source, "mobile_opt_in_rejected")

    def test_orchestrator_undo_command(self) -> None:
        orch = self._build_orch()
        result = orch.orchestrate("deshaz lo último")
        self.assertEqual(result.source, "undo_last_action")


if __name__ == "__main__":
    unittest.main()

