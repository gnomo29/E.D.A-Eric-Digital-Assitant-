from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from eda.nlp_utils import parse_command
from eda.orchestrator import CommandOrchestrator
from eda.stt import STTManager
from eda.ui_services import VoiceSessionService


class IntentsAndResponsesTests(unittest.TestCase):
    def _build_orchestrator(self) -> tuple[CommandOrchestrator, MagicMock, MagicMock, MagicMock, MagicMock]:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (False, "")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        web_solver = MagicMock()
        web_solver.solve.return_value = {"answer": "resultado web"}
        orch = CommandOrchestrator(
            memory=memory,
            core=core,
            action_agent=action_agent,
            actions=actions,
            web_solver=web_solver,
        )
        return orch, memory, core, actions, web_solver

    def test_parse_command_intents_and_entities(self) -> None:
        cases = [
            ("quién descubrió américa", "general_knowledge_question", "quién descubrió américa"),
            ("qué es una API", "technical_question", "qué es una api"),
            ("cómo funciona TCP", "technical_question", "cómo funciona tcp"),
            ("abre spotify y reproduce AC/DC", "open_and_play_music", "spotify|||ac/dc"),
            ("busca cuphead en steam", "search_in_app", "steam|||cuphead"),
        ]
        for text, expected_intent, expected_entity in cases:
            parsed = parse_command(text)
            self.assertEqual(
                parsed.intent,
                expected_intent,
                msg=f"Parse failed for: '{text}': expected intent '{expected_intent}' got '{parsed.intent}'",
            )
            self.assertEqual(
                parsed.entity,
                expected_entity,
                msg=f"Parse failed for: '{text}': expected entity '{expected_entity}' got '{parsed.entity}'",
            )

    def test_orchestrator_route_play_music_without_web_solver(self) -> None:
        orch, _memory, core, _actions, web_solver = self._build_orchestrator()
        with patch.object(orch, "_route_play_music", return_value="ok_music") as mock_play:
            result = orch.orchestrate("reproduce AC/DC")
        self.assertTrue(result.handled, "Expected handled=True for play_music route")
        self.assertEqual(result.source, "play_music", "Expected source=play_music for music route")
        mock_play.assert_called_once()
        web_solver.solve.assert_not_called()
        core.ask.assert_not_called()

    def test_orchestrator_route_search_in_app_without_web_solver(self) -> None:
        orch, _memory, core, _actions, web_solver = self._build_orchestrator()
        with patch.object(orch, "_route_search_in_app", return_value="ok_search_in_app") as mock_search:
            result = orch.orchestrate("busca cuphead en steam")
        self.assertTrue(result.handled, "Expected handled=True for search_in_app route")
        self.assertEqual(result.source, "search_in_app", "Expected source=search_in_app for app search route")
        mock_search.assert_called_once()
        web_solver.solve.assert_not_called()
        core.ask.assert_not_called()

    def test_orchestrator_general_knowledge_uses_core_ask_directly(self) -> None:
        orch, _memory, core, _actions, web_solver = self._build_orchestrator()
        core.ask.return_value = "Cristóbal Colón llegó a América en 1492."
        result = orch.orchestrate("quién descubrió américa")
        self.assertTrue(result.handled, "Expected handled=True for general_knowledge_question")
        self.assertIn(result.source, {"knowledge_answer", "qa_kb_local", "qa_wikipedia"})
        if result.source == "knowledge_answer":
            core.ask.assert_called_once()
            kwargs = core.ask.call_args.kwargs
            self.assertIn(
                "Responde con dato directo",
                kwargs.get("response_instruction", ""),
                msg="Expected concise direct-response instruction for general knowledge question",
            )
            self.assertFalse(
                kwargs.get("allow_web_fallback", True),
                msg="General knowledge should not allow automatic web fallback by default",
            )
        else:
            self.assertIn("Colon", result.answer)
        web_solver.solve.assert_not_called()

    def test_web_fallback_only_for_freshness_question(self) -> None:
        orch, _memory, core, _actions, web_solver = self._build_orchestrator()
        core.ask.return_value = "respuesta"

        result_recent = orch.orchestrate("¿Cuál es la última noticia sobre X en 2026?")
        self.assertTrue(result_recent.handled, "Expected handled=True for freshness question")
        recent_kwargs = core.ask.call_args.kwargs
        self.assertTrue(
            recent_kwargs.get("allow_web_fallback", False),
            msg="Freshness question should allow web fallback",
        )
        web_solver.solve.assert_not_called()

        core.ask.reset_mock()
        result_plain = orch.orchestrate("qué es una API")
        self.assertTrue(result_plain.handled, "Expected handled=True for technical question")
        plain_kwargs = core.ask.call_args.kwargs
        self.assertFalse(
            plain_kwargs.get("allow_web_fallback", True),
            msg="Technical definition should avoid web fallback by default",
        )
        web_solver.solve.assert_not_called()

    def test_technical_question_style_is_non_theatrical(self) -> None:
        orch, _memory, core, _actions, _web_solver = self._build_orchestrator()
        core.ask.return_value = "Una API es una interfaz para comunicar sistemas de software."
        result = orch.orchestrate("qué es una API")
        self.assertNotIn("Señor", result.answer, "Technical answer should avoid theatrical 'Señor' style")
        self.assertIn("API", result.answer, "Technical answer should retain core concept mention")
        kwargs = core.ask.call_args.kwargs
        self.assertIn(
            "definición",
            kwargs.get("response_instruction", ""),
            msg="Expected technical response instruction to include structured explanation",
        )

    def test_voice_session_stt_unavailable_hint_when_pyaudio_missing(self) -> None:
        with patch("eda.stt.sr", None):
            stt = STTManager(language="es-ES")
            service = VoiceSessionService(stt, None)
            started = service.start_continuous(lambda _text: None)
            hint = service.get_stt_hint().lower()
        self.assertFalse(started, "STT should not start when backend is unavailable")
        self.assertIn("pipwin", hint, "STT unavailable hint should mention pipwin for repair")
        self.assertIn("pyaudio", hint, "STT unavailable hint should mention pyaudio for repair")


if __name__ == "__main__":
    unittest.main()

