"""Comportamiento de EDA_REMOTE_SEARCH_MODE (sin red real)."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class RemoteSearchModeTests(unittest.TestCase):
    def test_unavailable_without_config(self) -> None:
        from eda import remote_llm

        with patch.dict("os.environ", {"EDA_REMOTE_SEARCH_MODE": "1"}, clear=False):
            with patch.object(remote_llm, "is_remote_fully_configured", return_value=False):
                self.assertFalse(remote_llm.remote_deep_research_pipeline_available())

    def test_synthesize_uses_chat_completion(self) -> None:
        from eda import remote_llm

        with patch.object(remote_llm, "is_remote_fully_configured", return_value=True):
            with patch.object(remote_llm, "chat_completion", return_value="respuesta sintetizada") as mock_cc:
                out = remote_llm.synthesize_filtered_web_answer("tema", "snippet1\nsnippet2")
        self.assertEqual(out, "respuesta sintetizada")
        mock_cc.assert_called_once()


if __name__ == "__main__":
    unittest.main()
