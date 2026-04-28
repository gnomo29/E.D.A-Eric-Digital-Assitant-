from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from eda.orchestrator import CommandOrchestrator
from eda.security.otp_manager import OTPManager


class OTPFlowTests(unittest.TestCase):
    def _build_orch(self) -> CommandOrchestrator:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        core.ask.return_value = "ok"
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (False, "")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        actions.undo_last_action.return_value = {"status": "ok", "message": "undo"}
        return CommandOrchestrator(memory=memory, core=core, action_agent=action_agent, actions=actions, vision=MagicMock())

    def test_otp_manager_issue_and_verify(self) -> None:
        manager = OTPManager(ttl_seconds=120)
        otp = manager.issue("123", "borra archivo temporal")
        self.assertEqual(len(otp), 6)
        invalid = manager.verify("123", "000000")
        self.assertFalse(invalid.get("ok"))
        valid = manager.verify("123", otp)
        self.assertTrue(valid.get("ok"))
        self.assertEqual(valid.get("command"), "borra archivo temporal")

    def test_critical_remote_command_requires_confirm_and_executes_after_otp(self) -> None:
        orch = self._build_orch()
        orch.mobile_connector.enviar_mensaje = MagicMock(return_value={"status": "ok", "message": "sent"})
        # Fuerza comando crítico.
        orch.remote_acl.classify = MagicMock(return_value=type("D", (), {"allowed": True, "level": "critical", "reason": ""})())
        first = orch._process_remote_command(text="borra archivo x", chat_id="123", source="test")
        self.assertEqual(first.source, "remote_otp_challenge")
        sent_text = orch.mobile_connector.enviar_mensaje.call_args[0][0]
        otp = sent_text.split("confirm ", 1)[1].split(" ", 1)[0]
        second = orch._process_remote_command(text=f"confirm {otp}", chat_id="123", source="test")
        self.assertNotEqual(second.source, "remote_otp_invalid")

    def test_alert_after_three_failed_otp_attempts(self) -> None:
        orch = self._build_orch()
        orch.mobile_connector.enviar_mensaje = MagicMock(return_value={"status": "ok", "message": "sent"})
        orch.remote_acl.classify = MagicMock(return_value=type("D", (), {"allowed": True, "level": "critical", "reason": ""})())
        _challenge = orch._process_remote_command(text="borra archivo x", chat_id="123", source="test")
        _f1 = orch._process_remote_command(text="confirm 111111", chat_id="123", source="test")
        _f2 = orch._process_remote_command(text="confirm 222222", chat_id="123", source="test")
        _f3 = orch._process_remote_command(text="confirm 333333", chat_id="123", source="test")
        calls = [c.args[0] for c in orch.mobile_connector.enviar_mensaje.call_args_list]
        self.assertTrue(any("3 intentos fallidos de OTP" in msg for msg in calls))


if __name__ == "__main__":
    unittest.main()

