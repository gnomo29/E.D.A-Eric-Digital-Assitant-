from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from eda.orchestrator import CommandOrchestrator


class OrchestratorOpenAppFallbackTests(unittest.TestCase):
    def _build_orchestrator(self) -> tuple[CommandOrchestrator, MagicMock, MagicMock, MagicMock]:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (False, "")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        web_solver = MagicMock()
        web_solver.solve.return_value = {"answer": "fallback de búsqueda ejecutado"}
        orch = CommandOrchestrator(
            memory=memory,
            core=core,
            action_agent=action_agent,
            actions=actions,
            web_solver=web_solver,
        )
        return orch, actions, web_solver, core

    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_open_app_local_success_without_browser(self, _mock_browser_open) -> None:
        orch, actions, web_solver, core = self._build_orchestrator()
        actions.open_app.return_value = {"status": "ok", "message": "Abriendo notepad."}

        result = orch.orchestrate("abre notepad")

        self.assertEqual(result.source, "open_app", f"Expected open_app source, got {result.source}")
        actions.open_app.assert_called_once()
        actions.open_website.assert_not_called()
        web_solver.solve.assert_not_called()
        core.ask.assert_not_called()

    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_open_app_file_not_found_then_web_url_fallback(self, _mock_browser_open) -> None:
        orch, actions, web_solver, core = self._build_orchestrator()
        actions.open_app.side_effect = FileNotFoundError("not found")
        actions._resolve_web_target_url.return_value = "https://www.youtube.com"
        actions.open_website.return_value = {"status": "ok", "message": "web ok"}

        result = orch.orchestrate("abre youtube")

        self.assertEqual(
            result.source,
            "open_app_web_fallback",
            f"Expected open_app_web_fallback source, got {result.source}",
        )
        actions.open_website.assert_called_once_with("https://www.youtube.com")
        web_solver.solve.assert_not_called()
        core.ask.assert_not_called()

    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_open_app_file_not_found_then_search_fallback_solver(self, _mock_browser_open) -> None:
        orch, actions, web_solver, core = self._build_orchestrator()
        actions.open_app.side_effect = FileNotFoundError("not found")
        actions._resolve_web_target_url.return_value = ""

        result = orch.orchestrate("abre app_inexistente_xyz")

        self.assertEqual(
            result.source,
            "open_app_search_fallback",
            f"Expected open_app_search_fallback source, got {result.source}",
        )
        web_solver.solve.assert_called_once()
        actions.open_website.assert_not_called()
        core.ask.assert_not_called()

    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_direct_web_open_intent_uses_browser_path(self, _mock_browser_open) -> None:
        orch, actions, web_solver, core = self._build_orchestrator()
        actions.open_app.return_value = {"status": "error", "message": "not local"}
        actions._resolve_web_target_url.return_value = "https://example.com"
        actions.open_website.return_value = {"status": "ok", "message": "web ok"}

        result = orch.orchestrate("abre example.com")

        self.assertEqual(
            result.source,
            "open_app_web_fallback",
            f"Expected direct web path source open_app_web_fallback, got {result.source}",
        )
        actions.open_website.assert_called_once_with("https://example.com")
        web_solver.solve.assert_not_called()
        core.ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()

