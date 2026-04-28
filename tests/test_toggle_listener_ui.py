from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import ui_main


class _Harness(ui_main.EDABaseUI):
    def schedule(self, delay_ms: int, fn):
        _ = (delay_ms, fn)

    def show_message(self, title: str, message: str) -> None:
        _ = (title, message)

    def open_approval_modal(self, req_id: str, summary: str, risk: str, command_preview: str) -> None:
        _ = (req_id, summary, risk, command_preview)

    def set_send_enabled(self, enabled: bool) -> None:
        _ = enabled

    def append_user_bubble(self, text: str) -> None:
        _ = text

    def append_assistant_bubble(self, text: str) -> None:
        _ = text

    def append_log_line(self, category: str, message: str) -> None:
        _ = (category, message)

    def apply_metrics(self, cpu: float, used_gb: float, total_gb: float, mem_ratio: float) -> None:
        _ = (cpu, used_gb, total_gb, mem_ratio)


class ToggleListenerUITests(unittest.TestCase):
    def test_toggle_on_off_calls_stt(self) -> None:
        fake_stt = MagicMock()
        fake_stt.start_continuous_listener.return_value = True
        ui = _Harness(stt=fake_stt)
        self.assertTrue(ui.toggle_continuous_listening(True))
        fake_stt.start_continuous_listener.assert_called_once()
        self.assertTrue(ui.continuous_enabled)
        ui.toggle_continuous_listening(False)
        fake_stt.stop_continuous_listener.assert_called()
        self.assertFalse(ui.continuous_enabled)


if __name__ == "__main__":
    unittest.main()
