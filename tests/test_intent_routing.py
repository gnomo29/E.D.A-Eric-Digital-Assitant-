from __future__ import annotations

import csv
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from eda.nlp_utils import parse_command
from eda.nlu.spotify_intent import parse_spotify_utterance
from eda.orchestrator import CommandOrchestrator


def infer_intent_entities(utterance: str) -> tuple[str, dict[str, Any], float]:
    txt = (utterance or "").strip()
    low = txt.lower()
    parsed = parse_command(txt)
    sp = parse_spotify_utterance(txt)
    liked_hint = any(k in low for k in ("me gusta", "liked", "likes", "favs", "favoritas", "favoritos"))

    # 1) reglas determinísticas de comandos/consultas específicas
    if ("video" in low or "videos" in low) and any(k in low for k in ("abre", "busca", "search")):
        if "search " in low:
            return "web_search_videos", {"query": txt}, 0.88
        return ("open_media_search" if "abre" in low else "web_search_videos"), {"query": txt}, 0.88
    if low.startswith("close "):
        return "close_app", {"target": txt[6:].strip()}, 0.78
    if low.startswith("open "):
        return "open_app", {"target": txt[5:].strip()}, 0.78
    if "noticias" in low:
        return "web_search_news", {"query": txt}, 0.87
    if "pdf" in low:
        return "create_pdf", {"query": txt}, 0.91
    if parsed.intent == "close_app":
        return "close_app", {"target": parsed.entity}, float(parsed.confidence)
    if parsed.intent == "open_app":
        return "open_app", {"target": parsed.entity}, float(parsed.confidence)

    # 2) conversación (pregunta o explicación)
    if parsed.intent in {"general_knowledge_question", "technical_question", "explanation_request"} or txt.endswith("?"):
        return "conversation_explanation", {"query": txt}, max(0.8, float(parsed.confidence))

    # 3) música (Spotify)
    if liked_hint and any(k in low for k in ("pon", "play", "reproduce", "spotify")):
        return "open_and_play_liked", {"query": txt}, 0.92
    if sp.kind == "liked":
        return "open_and_play_liked", {"query": txt}, 0.92
    if parsed.intent == "play_music":
        return "play_music", {"query": parsed.entity or txt}, float(parsed.confidence)
    # typo coloquial: reprodece
    if low.startswith("reprodece "):
        return "play_music", {"query": txt[10:].strip()}, 0.8
    if sp.kind in {"artist_top", "track", "album", "playlist", "generic_play", "similar", "latest_album"}:
        return "play_music", {"query": sp.primary_query or txt}, 0.89

    return parsed.intent, {"entity": parsed.entity}, float(parsed.confidence)


class IntentNLUTests(unittest.TestCase):
    def test_dataset_covers_core_intents(self) -> None:
        dataset = Path(__file__).resolve().parent / "intents_dataset.csv"
        rows = list(csv.DictReader(dataset.read_text(encoding="utf-8").splitlines()))
        present = {row["expected_intent"] for row in rows}
        required = {
            "play_music",
            "open_and_play_liked",
            "open_media_search",
            "web_search_videos",
            "web_search_news",
            "create_pdf",
            "conversation_explanation",
        }
        self.assertTrue(required.issubset(present), f"Missing intents: {sorted(required - present)}")

    def test_dataset_mapping(self) -> None:
        dataset = Path(__file__).resolve().parent / "intents_dataset.csv"
        rows = list(csv.DictReader(dataset.read_text(encoding="utf-8").splitlines()))
        self.assertGreater(len(rows), 8)
        mismatches: list[str] = []
        for row in rows:
            intent, entities, conf = infer_intent_entities(row["utterance"])
            if intent != row["expected_intent"]:
                mismatches.append(f"{row['utterance']} => {intent} != {row['expected_intent']}")
            self.assertGreaterEqual(conf, 0.5)
            self.assertIsInstance(entities, dict)
        self.assertEqual([], mismatches, "\n".join(mismatches))


class IntentRoutingIntegrationTests(unittest.TestCase):
    def _build_orchestrator(self) -> tuple[CommandOrchestrator, MagicMock, MagicMock, MagicMock, MagicMock]:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        core.ask.return_value = "explicación llm"
        core.filtered_remote_research_answer.return_value = "noticias sintetizadas"
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (False, "")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        actions.open_app.return_value = {"status": "ok", "message": "Abriendo app"}
        actions.open_website.return_value = {"status": "ok", "message": "open web"}
        actions.close_app.return_value = {"status": "ok", "message": "Cerrando app"}
        actions._resolve_web_target_url.return_value = ""
        web_solver = MagicMock()
        web_solver.solve.return_value = {"answer": "top-5 links"}
        orch = CommandOrchestrator(
            memory=memory,
            core=core,
            action_agent=action_agent,
            actions=actions,
            web_solver=web_solver,
        )
        return orch, actions, action_agent, core, web_solver

    @patch("eda.orchestrator.route_spotify_natural", return_value="Reproduciendo AD/DC")
    def test_reproduce_ad_dc(self, _mock_route: MagicMock) -> None:
        orch, actions, _ag, _core, _ws = self._build_orchestrator()
        result = orch.orchestrate("reproduce AD/DC")
        self.assertEqual("play_music", result.source)
        self.assertIn("reproduciendo", result.answer.lower())
        actions.open_app.assert_called()

    @patch("eda.orchestrator.route_spotify_natural", return_value=None)
    @patch("eda.orchestrator.try_play_via_web_api", return_value=("fail", "no_tracks_found"))
    def test_ambiguous_aiaia_fallback_clarify(self, _mock_try: MagicMock, _mock_route: MagicMock) -> None:
        orch, actions, _ag, _core, _ws = self._build_orchestrator()
        actions.open_app.side_effect = [
            {"status": "ok", "message": "Abriendo spotify"},
            {"status": "error", "message": "not found"},
        ]
        actions.open_website.return_value = {"status": "error", "message": "fail"}
        result = orch.orchestrate("reproduce aiaia")
        self.assertEqual("play_music", result.source)
        self.assertIn("no encontré esa app o canción", result.answer.lower())

    def test_open_media_search(self) -> None:
        orch, _actions, _ag, _core, _ws = self._build_orchestrator()
        result = orch.orchestrate("abre videos de minecraft")
        self.assertEqual("open_media_search", result.source)
        self.assertTrue(result.answer)

    @patch("eda.orchestrator.remote_llm.remote_search_mode_requested", return_value=True)
    @patch("eda.orchestrator.remote_llm.is_remote_fully_configured", return_value=True)
    def test_search_news_remote(self, _cfg: MagicMock, _req: MagicMock) -> None:
        orch, _actions, _ag, core, _ws = self._build_orchestrator()
        result = orch.orchestrate("busca noticias en japones")
        self.assertEqual("web_search_news", result.source)
        core.filtered_remote_research_answer.assert_called()

    def test_close_chrome_requires_confirmation(self) -> None:
        orch, actions, _ag, _core, _ws = self._build_orchestrator()
        first = orch.orchestrate("cierra chrome")
        self.assertEqual("close_app_confirm_required", first.source)
        self.assertIn("confirmas", first.answer.lower())
        second = orch.orchestrate("sí")
        self.assertEqual("close_app_confirmed", second.source)
        actions.close_app_robust.assert_called()

    def test_question_goes_to_llm(self) -> None:
        orch, _actions, _ag, core, _ws = self._build_orchestrator()
        result = orch.orchestrate("qué es eso?")
        self.assertIn(result.source, {"conversation_llm", "knowledge_answer"})
        self.assertNotIn("acción directa", result.answer.lower())
        core.ask.assert_called()

    def test_create_pdf_on_desktop(self) -> None:
        orch, _actions, _ag, _core, _ws = self._build_orchestrator()
        with tempfile.TemporaryDirectory() as td:
            fake_home = Path(td)
            (fake_home / "Desktop").mkdir(parents=True)
            with patch("eda.orchestrator.Path.home", return_value=fake_home):
                result = orch.orchestrate("crea un informe pdf en el escritorio")
                self.assertEqual("create_pdf", result.source)
                self.assertIn(".pdf", result.answer.lower())

    @patch("eda.orchestrator.search_youtube_candidates")
    @patch("eda.orchestrator.validate_youtube_url", return_value=True)
    @patch("eda.orchestrator.webbrowser.open")
    def test_youtube_intent_routes_to_play_youtube(self, _open: MagicMock, _valid: MagicMock, mock_search: MagicMock) -> None:
        mock_search.return_value = [
            {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "video_id": "dQw4w9WgXcQ",
                "title": "Rick",
                "channel": "RickAstley",
                "thumbnail": "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            }
        ]
        orch, _actions, _ag, _core, _ws = self._build_orchestrator()
        result = orch.orchestrate("muestrame un video de gatitos")
        self.assertEqual("search_youtube_query", result.source)

    @patch("eda.orchestrator.validate_youtube_url", return_value=True)
    def test_youtube_direct_url_routes_to_url_handler(self, _valid: MagicMock) -> None:
        orch, _actions, _ag, _core, _ws = self._build_orchestrator()
        result = orch.orchestrate("reproduce https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual("play_youtube_url", result.source)

    @patch("eda.orchestrator.channel_lookup_candidates")
    @patch("eda.orchestrator.validate_youtube_url", return_value=True)
    def test_youtube_creator_routes_channel_lookup(self, _valid: MagicMock, mock_lookup: MagicMock) -> None:
        mock_lookup.return_value = [
            {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "video_id": "dQw4w9WgXcQ",
                "title": "Vegeta777 latest",
                "channel": "Vegeta777",
                "thumbnail": "",
                "confidence": "0.91",
                "source": "api",
            }
        ]
        orch, _actions, _ag, _core, _ws = self._build_orchestrator()
        result = orch.orchestrate("reproduce vegeta777")
        self.assertEqual("channel_lookup", result.source)


class UISmokeMockedTests(unittest.TestCase):
    def test_ui_submit_to_orchestrator_mock(self) -> None:
        import ui_main

        class FakeOrchestrator:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def orchestrate(self, text: str) -> Any:
                class R:
                    handled = True
                    answer = f"mock:{text}"
                    source = "mocked"

                return R()

        class DummyUI(ui_main.EDABaseUI):
            def __init__(self) -> None:
                self.messages: list[str] = []
                with patch.object(ui_main, "CommandOrchestrator", FakeOrchestrator):
                    super().__init__(metrics_interval_ms=500)

            def schedule(self, delay_ms: int, fn: Any) -> None:
                fn()

            def show_message(self, title: str, message: str) -> None:
                self.messages.append(f"{title}:{message}")

            def open_approval_modal(self, req_id: str, summary: str, risk: str, command_preview: str) -> None:
                self.resolve_approval(req_id, "approve_once", trust=False)

            def set_send_enabled(self, enabled: bool) -> None:
                pass

            def append_user_bubble(self, text: str) -> None:
                self.messages.append(f"user:{text}")

            def append_assistant_bubble(self, text: str) -> None:
                self.messages.append(f"assistant:{text}")

            def append_log_line(self, category: str, message: str) -> None:
                self.messages.append(f"log:{category}:{message}")

            def apply_metrics(self, cpu: float, used_gb: float, total_gb: float, mem_ratio: float) -> None:
                pass

        ui = DummyUI()
        ui.submit_command("reproduce AD/DC", display_user="reproduce AD/DC")
        time.sleep(0.25)
        ui.pump_ui()
        joined = "\n".join(ui.messages).lower()
        self.assertIn("mock:reproduce ad/dc", joined)


if __name__ == "__main__":
    unittest.main()

