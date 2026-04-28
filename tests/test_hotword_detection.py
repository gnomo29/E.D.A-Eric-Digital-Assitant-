from __future__ import annotations

import threading
import unittest

from eda.stt import STTManager


class HotwordDetectionTests(unittest.TestCase):
    def test_detects_wakeword_and_dispatches_command(self) -> None:
        stt = STTManager()
        seq = iter(["ruido cualquiera", "eda", "abre chrome", ""])
        stt._ensure_backend = lambda: True  # type: ignore[assignment]
        stt.listen_once = lambda **_kwargs: next(seq, "")  # type: ignore[assignment]
        got: list[str] = []
        evt = threading.Event()

        def on_cmd(text: str) -> None:
            got.append(text)
            evt.set()
            stt.stop_continuous_listener()

        ok = stt.start_continuous_listener(on_command=on_cmd, wake_word="eda", post_activation_window=3.0)
        self.assertTrue(ok)
        evt.wait(timeout=3.0)
        self.assertTrue(got)
        self.assertEqual(got[0].strip().lower(), "abre chrome")

    def test_no_wakeword_no_command(self) -> None:
        stt = STTManager()
        seq = iter(["hola", "como estas", "ninguna orden", ""])
        stt._ensure_backend = lambda: True  # type: ignore[assignment]
        stt.listen_once = lambda **_kwargs: next(seq, "")  # type: ignore[assignment]
        got: list[str] = []
        done = threading.Event()

        def on_cmd(text: str) -> None:
            got.append(text)

        def on_state(state: str, _conf: float) -> None:
            if state == "wait_wakeword":
                # Después de algunos ciclos, cortamos.
                done.set()

        stt.start_continuous_listener(on_command=on_cmd, on_state=on_state, wake_word="eda", post_activation_window=2.0)
        done.wait(timeout=1.0)
        stt.stop_continuous_listener()
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
