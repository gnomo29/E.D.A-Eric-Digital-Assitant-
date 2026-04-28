from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eda.action_agent import ActionAgent
from eda.memory import MemoryManager
from eda.orchestrator import CommandOrchestrator
from eda.task_membership import LearnedTask
from eda.utils.security import redact_sensitive_data, sanitize_app_target, validate_shell_command


class V2CoreSecurityPrivacyTests(unittest.TestCase):
    def test_shell_injection_is_blocked(self) -> None:
        blocked = validate_shell_command("dir && whoami")
        self.assertFalse(blocked.allowed)
        self.assertIn("metacaracter", blocked.reason)

    def test_non_whitelisted_command_is_blocked(self) -> None:
        blocked = validate_shell_command("powershell -Command Get-Process")
        self.assertFalse(blocked.allowed)
        self.assertIn("no permitido", blocked.reason)

    def test_app_target_sanitization_blocks_meta(self) -> None:
        blocked = sanitize_app_target("notepad; calc")
        self.assertFalse(blocked.allowed)

    def test_redaction_masks_email_and_tokens(self) -> None:
        text = "mail test@example.com token=sk_test_1234567890"
        masked = redact_sensitive_data(text)
        self.assertNotIn("test@example.com", masked)
        self.assertNotIn("sk_test_1234567890", masked)
        self.assertIn("[REDACTED]", masked)

    def test_memory_encrypts_payload_when_saved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch("eda.memory.config.MEMORY_FILE", Path(td) / "memoria.json"):
                with patch("eda.memory.config.BT_MEMORY_FILE", Path(td) / "bt.json"):
                    with patch("eda.memory.config.SOLUTIONS_CACHE_FILE", Path(td) / "cache.json"):
                        mgr = MemoryManager()
                        data = mgr.get_memory()
                        data["remembered"]["api_key"] = {"value": "sk_test_1234567890"}
                        self.assertTrue(mgr.save_memory(data))
                        raw = (Path(td) / "memoria.json").read_text(encoding="utf-8")
                        self.assertIn("__encrypted__", raw)
                        self.assertNotIn("sk_test_1234567890", raw)

    def test_memory_roundtrip_decrypt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch("eda.memory.config.MEMORY_FILE", Path(td) / "memoria.json"):
                with patch("eda.memory.config.BT_MEMORY_FILE", Path(td) / "bt.json"):
                    with patch("eda.memory.config.SOLUTIONS_CACHE_FILE", Path(td) / "cache.json"):
                        mgr = MemoryManager()
                        self.assertTrue(mgr.remember("email", "dev@example.com"))
                        loaded = mgr.load_memory()
                        remembered = loaded.get("remembered", {}).get("email", {})
                        self.assertIn("[REDACTED]", remembered.get("value", ""))

    def test_action_agent_blocks_terminal_injection(self) -> None:
        agent = ActionAgent(actions=MagicMock(), mouse_keyboard=MagicMock())
        msg, ok = agent._run_terminal_command("dir && del *", require_confirm=True)  # pylint: disable=protected-access
        self.assertFalse(ok)
        self.assertIn("bloqueado por seguridad", msg.lower())

    def test_action_agent_sandbox_timeout(self) -> None:
        agent = ActionAgent(actions=MagicMock(), mouse_keyboard=MagicMock())
        task = LearnedTask(name="x", trigger="y", steps=[{"tool": "open_dynamic", "value": "notepad"}], source="t")
        with patch("eda.action_agent.subprocess.run", side_effect=TimeoutError("boom")):
            answer, ok, _err = agent._run_task_sandboxed(task)  # pylint: disable=protected-access
        self.assertFalse(ok)
        self.assertIn("sandbox", answer.lower())

    def _build_orchestrator(self) -> CommandOrchestrator:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (True, "ejecutado")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        return CommandOrchestrator(
            memory=memory,
            core=core,
            action_agent=action_agent,
            actions=actions,
            web_solver=None,
            vision=MagicMock(),
        )

    def test_orchestrator_requires_approval_for_terminal(self) -> None:
        orch = self._build_orchestrator()
        first = orch.orchestrate("ejecuta comando: dir")
        self.assertEqual(first.source, "risky_action_requires_confirmation")
        self.assertIn("Aprobación PRO", first.answer)

    def test_orchestrator_approval_yes_executes(self) -> None:
        orch = self._build_orchestrator()
        _first = orch.orchestrate("ejecuta comando: dir")
        second = orch.orchestrate("sí")
        self.assertEqual(second.source, "approved_risky_action")

    def test_orchestrator_approval_no_cancels(self) -> None:
        orch = self._build_orchestrator()
        _first = orch.orchestrate("ejecuta comando: dir")
        second = orch.orchestrate("no")
        self.assertEqual(second.source, "risky_action_cancelled")

    def test_orchestrator_waits_for_explicit_yes_no(self) -> None:
        orch = self._build_orchestrator()
        _first = orch.orchestrate("ejecuta comando: dir")
        second = orch.orchestrate("tal vez")
        self.assertEqual(second.source, "risky_action_waiting_confirmation")

    def test_vector_search_semantic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch("eda.memory.config.MEMORY_FILE", Path(td) / "memoria.json"):
                with patch("eda.memory.config.BT_MEMORY_FILE", Path(td) / "bt.json"):
                    with patch("eda.memory.config.SOLUTIONS_CACHE_FILE", Path(td) / "cache.json"):
                        mgr = MemoryManager()
                        mgr.save_knowledge("tcp", "qué es tcp", "TCP es un protocolo de transporte.")
                        hit = mgr.search_knowledge("protocolo transporte tcp")
                        self.assertIsNotNone(hit)
                        self.assertIn("tcp", str(hit.get("topic", "")).lower())

    def test_maintenance_purges_old_records(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch("eda.memory.config.MEMORY_FILE", Path(td) / "memoria.json"):
                with patch("eda.memory.config.BT_MEMORY_FILE", Path(td) / "bt.json"):
                    with patch("eda.memory.config.SOLUTIONS_CACHE_FILE", Path(td) / "cache.json"):
                        mgr = MemoryManager()
                        data = mgr.get_memory()
                        data["history"] = [{"ts": "2000-01-01T00:00:00", "user": "x", "assistant": "y"}]
                        mgr.save_memory(data)
                        report = mgr.run_maintenance(days_to_keep_logs=30)
                        self.assertGreaterEqual(int(report.get("old_records_purged", 0)), 1)


if __name__ == "__main__":
    unittest.main()

