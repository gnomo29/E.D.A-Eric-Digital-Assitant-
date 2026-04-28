from __future__ import annotations

import unittest
from unittest.mock import patch

from eda.connectors.youtube import extract_video_id, extract_youtube_candidates_from_text, is_allowed_youtube_url
from eda.orchestrator import CommandOrchestrator


class YouTubeHandlingTests(unittest.TestCase):
    def test_extract_video_id(self) -> None:
        self.assertEqual("dQw4w9WgXcQ", extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_allowed_domain(self) -> None:
        self.assertTrue(is_allowed_youtube_url("https://youtu.be/dQw4w9WgXcQ"))
        self.assertFalse(is_allowed_youtube_url("https://evil.example.com/watch?v=dQw4w9WgXcQ"))

    def test_extract_candidates_from_text(self) -> None:
        txt = "mira https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        cands = extract_youtube_candidates_from_text(txt)
        self.assertTrue(cands)

    @patch("eda.orchestrator.search_youtube_candidates")
    @patch("eda.orchestrator.validate_youtube_url", return_value=True)
    @patch("eda.orchestrator.webbrowser.open")
    def test_orchestrator_youtube_intent(self, _open, _val, mock_search) -> None:
        mock_search.return_value = [
            {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video_id": "dQw4w9WgXcQ", "title": "x", "channel": "c", "thumbnail": "t"}
        ]
        memory = type("M", (), {"update_user_profile_from_text": lambda *_: {}, "get_user_profile": lambda *_: {"name": "Eric"}, "save_long_term_memory": lambda *_: None, "get_memory": lambda *_: {"chat_history": []}})()
        core = type("C", (), {"ask": lambda *_args, **_kwargs: "ok", "filtered_remote_research_answer": lambda *_: "ok"})()
        actions = type(
            "A",
            (),
            {
                "execute_navigation_command": lambda *_: None,
                "open_app": lambda *_: {"status": "ok", "message": "ok"},
                "open_website": lambda *_: {"status": "ok", "message": "ok"},
                "close_app": lambda *_: {"status": "ok", "message": "ok"},
                "_resolve_web_target_url": lambda *_: "",
            },
        )()
        ag = type("AG", (), {"try_handle": lambda *_: (False, "")})()
        orch = CommandOrchestrator(memory=memory, core=core, action_agent=ag, actions=actions, web_solver=None)
        out = orch.orchestrate("reproduce vegeta777")
        self.assertEqual("play_youtube", out.source)


if __name__ == "__main__":
    unittest.main()
