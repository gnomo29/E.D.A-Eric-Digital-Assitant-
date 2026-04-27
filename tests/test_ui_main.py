"""Tests headless para la UI (sin CustomTkinter/tk real)."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import ui_main  # noqa: E402


class _HeadlessHarness(ui_main.EDABaseUI):
    """Backend mínimo para tests: sin ventana ni mainloop."""

    def __init__(
        self,
        *,
        action_agent=None,
        stt=None,
        metrics_interval_ms: int = 2000,
    ) -> None:
        super().__init__(action_agent=action_agent, stt=stt, metrics_interval_ms=metrics_interval_ms)
        self.scheduled: list[tuple[int, object]] = []
        self.assistant_lines: list[str] = []

    def schedule(self, delay_ms: int, fn: object) -> None:
        self.scheduled.append((delay_ms, fn))

    def show_message(self, title: str, message: str) -> None:
        pass

    def open_approval_modal(self, req_id: str, summary: str, risk: str, command_preview: str) -> None:
        self.resolve_approval(req_id, "approve_once", trust=False)

    def set_send_enabled(self, enabled: bool) -> None:
        pass

    def append_user_bubble(self, text: str) -> None:
        pass

    def append_assistant_bubble(self, text: str) -> None:
        self.assistant_lines.append(text)

    def append_log_line(self, category: str, message: str) -> None:
        pass

    def apply_metrics(self, cpu: float, used_gb: float, total_gb: float, mem_ratio: float) -> None:
        pass


def _pump_worker_and_ui(ui: _HeadlessHarness, timeout: float = 2.5) -> None:
    """Hilo que vacía la cola UI mientras el worker del pool ejecuta."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        ui.pump_ui(max_items=100)
        time.sleep(0.01)


class UiMainTests(unittest.TestCase):
    def test_ui_no_blocking(self) -> None:
        """main(--no-gui) no debe abrir ventana ni bloquear."""
        t0 = time.time()
        rc = ui_main.main(["--no-gui"])
        elapsed = time.time() - t0
        self.assertEqual(rc, 0)
        self.assertLess(elapsed, 2.0, "main thread no debe quedar bloqueado")

    def test_actionagent_threading(self) -> None:
        """try_handle debe ejecutarse en el ThreadPoolExecutor, resultados vía cola UI."""
        main_ident = threading.get_ident()
        ran_in: list[int] = []

        mock_agent = MagicMock()

        def _try_handle(text: str) -> tuple[bool, str]:
            ran_in.append(threading.get_ident())
            return True, "ok-mock"

        mock_agent.try_handle.side_effect = _try_handle

        ui = _HeadlessHarness(action_agent=mock_agent, metrics_interval_ms=2000)
        pumper = threading.Thread(target=_pump_worker_and_ui, args=(ui,), daemon=True)
        pumper.start()

        ui.submit_command("abre calculadora", display_user="abre calculadora")
        pumper.join(timeout=5.0)

        self.assertTrue(ran_in, "try_handle debió ejecutarse")
        self.assertNotEqual(ran_in[0], main_ident)
        mock_agent.try_handle.assert_called()

    def test_stt_integration_mock(self) -> None:
        """listen_once corre en worker; la cola UI recibe el resultado."""
        heard_thread: list[int] = []

        mock_stt = MagicMock()

        def _listen_once(**kwargs: object) -> str:
            heard_thread.append(threading.get_ident())
            time.sleep(0.05)
            return "comando simulado"

        mock_stt.listen_once.side_effect = _listen_once

        ui = _HeadlessHarness(stt=mock_stt, metrics_interval_ms=2000)
        main_ident = threading.get_ident()

        pumper = threading.Thread(target=_pump_worker_and_ui, args=(ui,), daemon=True)
        pumper.start()

        ui.listen_mic()
        pumper.join(timeout=5.0)

        mock_stt.listen_once.assert_called()
        self.assertTrue(heard_thread)
        self.assertNotEqual(heard_thread[0], main_ident)


if __name__ == "__main__":
    unittest.main()
