from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock

from eda.stt import STTManager


class PostActivationFlowTests(unittest.TestCase):
    def test_flow_activation_to_orchestrator(self) -> None:
        stt = STTManager()
        stt._ensure_backend = lambda: True  # type: ignore[assignment]
        seq = iter(["eda", "cierra chrome", ""])
        stt.listen_once = lambda **_kwargs: next(seq, "")  # type: ignore[assignment]

        orchestrator = MagicMock()
        orchestrator.orchestrate.return_value = MagicMock(handled=True, answer="ok", source="close_app_confirm_required")
        done = threading.Event()

        def on_command(text: str) -> None:
            orchestrator.orchestrate(text)
            done.set()
            stt.stop_continuous_listener()

        stt.start_continuous_listener(on_command=on_command, wake_word="eda", post_activation_window=5.0)
        done.wait(timeout=3.0)
        orchestrator.orchestrate.assert_called_once_with("cierra chrome")


if __name__ == "__main__":
    unittest.main()
