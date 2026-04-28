from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from eda.orchestrator import CommandOrchestrator


class RateLimitTests(unittest.TestCase):
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

    def test_remote_commands_are_not_rate_limited(self) -> None:
        orch = self._build_orch()
        r1 = orch._process_remote_command(text="estado", chat_id="100", source="test")
        r2 = orch._process_remote_command(text="estado", chat_id="100", source="test")
        r3 = orch._process_remote_command(text="estado", chat_id="100", source="test")
        self.assertNotEqual(r1.source, "remote_rate_limit")
        self.assertNotEqual(r2.source, "remote_rate_limit")
        self.assertNotEqual(r3.source, "remote_rate_limit")


if __name__ == "__main__":
    unittest.main()

