import unittest
from unittest.mock import MagicMock, patch

from eda import remote_llm


class RemoteLLMTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with patch.object(remote_llm, "remote_llm_effective_enabled", return_value=False):
            self.assertFalse(remote_llm.is_remote_fully_configured())

    def test_health_when_disabled(self) -> None:
        with patch.object(remote_llm, "remote_llm_effective_enabled", return_value=False):
            self.assertEqual(remote_llm.health_status(), "disabled")

    @patch.object(remote_llm, "remote_llm_effective_enabled", return_value=True)
    @patch.object(remote_llm, "remote_llm_base_url", return_value="https://example.com/v1")
    @patch.object(remote_llm, "remote_llm_model", return_value="test-model")
    @patch.object(remote_llm, "remote_llm_api_key", return_value="")
    def test_health_missing_key(self, *_mocks: object) -> None:
        self.assertEqual(remote_llm.health_status(), "missing_api_key")

    def test_chat_completion_parses_choice(self) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "  hola  "}}]}
        inst = MagicMock()
        inst.post.return_value = mock_resp
        remote_llm._HTTP_SESSION = None
        with patch.object(remote_llm, "is_remote_fully_configured", return_value=True):
            with patch.object(remote_llm, "remote_llm_base_url", return_value="https://x.com/v1"):
                with patch.object(remote_llm, "remote_llm_model", return_value="m"):
                    with patch.object(remote_llm, "remote_llm_api_key", return_value="k"):
                        with patch("eda.remote_llm.requests.Session", return_value=inst):
                            out = remote_llm.chat_completion(
                                [{"role": "user", "content": "ping"}],
                                temperature=0.1,
                                max_tokens=10,
                            )
        self.assertEqual(out, "hola")
        remote_llm._HTTP_SESSION = None


if __name__ == "__main__":
    unittest.main()
