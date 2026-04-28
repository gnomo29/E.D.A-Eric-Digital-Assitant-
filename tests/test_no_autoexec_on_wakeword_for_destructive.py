from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from eda.orchestrator import CommandOrchestrator


class NoAutoExecOnWakewordDestructiveTests(unittest.TestCase):
    def test_close_app_still_requires_confirmation(self) -> None:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (False, "")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        orch = CommandOrchestrator(memory=memory, core=core, action_agent=action_agent, actions=actions)
        out = orch.orchestrate("cierra chrome")
        self.assertEqual(out.source, "close_app_confirm_required")
        actions.close_app_robust.assert_not_called()


if __name__ == "__main__":
    unittest.main()
