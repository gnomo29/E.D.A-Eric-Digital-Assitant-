from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from eda.orchestrator import CommandOrchestrator


class OrchestratorRoutingMatrixTests(unittest.TestCase):
    def _build(self) -> tuple[CommandOrchestrator, MagicMock, MagicMock, MagicMock]:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        core.ask.return_value = "Respuesta explicativa"
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (False, "")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        actions.open_app.return_value = {"status": "ok", "message": "ok"}
        actions.open_website.return_value = {"status": "error", "message": "error"}
        actions._resolve_web_target_url.return_value = ""
        orch = CommandOrchestrator(
            memory=memory,
            core=core,
            action_agent=action_agent,
            actions=actions,
            web_solver=MagicMock(),
        )
        return orch, actions, action_agent, core

    @patch("eda.orchestrator.route_spotify_natural", return_value=None)
    @patch("eda.orchestrator.try_play_via_web_api", return_value=("skip", "not_configured"))
    def test_que_es_eso_routes_to_llm_not_action_error(
        self,
        _mock_try_play: MagicMock,
        _mock_spotify_route: MagicMock,
    ) -> None:
        orch, _actions, action_agent, core = self._build()
        res = orch.orchestrate("que es eso?")
        self.assertIn(res.source, {"knowledge_answer", "conversation_llm"})
        self.assertTrue(res.answer)
        self.assertNotIn("acción directa", res.answer.lower())
        core.ask.assert_called()
        action_agent.try_handle.assert_called()

    @patch("eda.orchestrator.route_spotify_natural", return_value="Reproduciendo AD/DC")
    def test_reproduce_ad_dc_routes_to_spotify_bridge(self, _mock_spotify_route: MagicMock) -> None:
        orch, actions, _action_agent, _core = self._build()
        res = orch.orchestrate("reproduce AD/DC")
        self.assertEqual(res.source, "play_music")
        self.assertIn("reproduciendo", res.answer.lower())
        actions.open_app.assert_called()

    @patch("eda.orchestrator.route_spotify_natural", return_value=None)
    @patch("eda.orchestrator.try_play_via_web_api", return_value=("fail", "no_tracks_found"))
    def test_reproduce_aiaia_spotify_then_app_then_clarify(
        self,
        _mock_try_play: MagicMock,
        _mock_spotify_route: MagicMock,
    ) -> None:
        orch, actions, _action_agent, _core = self._build()
        actions.open_app.side_effect = [
            {"status": "ok", "message": "spotify open"},
            {"status": "error", "message": "not found"},
        ]
        actions.open_website.return_value = {"status": "error", "message": "fail"}
        res = orch.orchestrate("reproduce aiaia")
        self.assertEqual(res.source, "play_music")
        self.assertIn("no encontré esa app o canción", res.answer.lower())
        self.assertGreaterEqual(actions.open_app.call_count, 2)


if __name__ == "__main__":
    unittest.main()

