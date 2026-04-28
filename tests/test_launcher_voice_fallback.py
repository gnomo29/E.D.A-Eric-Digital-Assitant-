from __future__ import annotations

import unittest
from unittest.mock import patch

import run_assistant
from eda.stt import STTManager


class _FakeRecognizer:
    dynamic_energy_threshold = True
    energy_threshold = 280
    pause_threshold = 0.75
    non_speaking_duration = 0.35


class _FakeSRModule:
    @staticmethod
    def Recognizer():
        return _FakeRecognizer()

    @staticmethod
    def Microphone():
        raise RuntimeError("Could not find PyAudio; check installation")


class LauncherVoiceFallbackTests(unittest.TestCase):
    def test_launcher_continues_when_pyaudio_missing(self) -> None:
        with (
            patch.object(run_assistant, "_missing_requirements", return_value=[]),
            patch.object(run_assistant, "_check_ollama", return_value=False),
            patch.object(run_assistant, "_launch", return_value=0),
            patch.object(run_assistant, "_is_pkg_installed", return_value=False),
            patch.object(run_assistant.os, "name", "nt"),
            patch("sys.argv", ["run_assistant.py"]),
        ):
            rc = run_assistant.main()
        self.assertEqual(rc, 0)

    def test_stt_reports_hint_when_pyaudio_not_available(self) -> None:
        from eda import stt as stt_module

        with patch.object(stt_module, "sr", _FakeSRModule):
            manager = STTManager(language="es-ES")
            ok = manager._ensure_backend()
            hint = manager.get_unavailable_hint()

        self.assertFalse(ok)
        self.assertIn("pipwin", hint.lower())
        self.assertIn("pyaudio", hint.lower())


if __name__ == "__main__":
    unittest.main()

