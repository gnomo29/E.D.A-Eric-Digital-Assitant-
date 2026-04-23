import unittest
from unittest.mock import MagicMock, patch

from actions import ActionController
from nlp_utils import parse_command
from web_search import WebSearch
from web_solver import WebSolver


class WebAndActionsTests(unittest.TestCase):
    def test_normalize_results_deduplicates_urls(self) -> None:
        ws = WebSearch()
        items = [
            {"title": "A", "url": "https://site.com/x", "snippet": "uno"},
            {"title": "B", "url": "https://site.com/x/", "snippet": "dos"},
            {"title": "C", "url": "https://site.com/y#ref", "snippet": "tres"},
        ]
        normalized = ws._normalize_results(items, max_results=5)
        self.assertEqual(len(normalized), 2)

    def test_action_controller_alias_resolution(self) -> None:
        ac = ActionController()
        self.assertEqual(ac._normalize_app("abre la calculadora por favor"), "calc")
        self.assertEqual(ac._normalize_app("abre chrome"), "chrome")

    def test_parse_navigation_command(self) -> None:
        ac = ActionController()
        self.assertEqual(ac.parse_navigation_command("busca lofi hip hop en youtube"), ("youtube_first", "lofi hip hop"))
        self.assertEqual(ac.parse_navigation_command("reproduce metallica en spotify"), ("spotify_search", "metallica"))
        self.assertEqual(ac.parse_navigation_command("busca hollow knight en steam"), ("steam_search", "hollow knight"))

    def test_extract_spotify_play_query_without_platform(self) -> None:
        ac = ActionController()
        self.assertEqual(ac.extract_spotify_play_query("reproduce ironman 2 soundtrack"), "ironman 2 soundtrack")
        self.assertEqual(ac.extract_spotify_play_query("pon canción de queen"), "de queen")
        self.assertEqual(ac.extract_spotify_play_query("reproduce algo en youtube"), "")

    @patch("actions.webbrowser.open")
    def test_execute_navigation_command_steam(self, mock_open) -> None:
        ac = ActionController()
        result = ac.execute_navigation_command("busca terraria en steam")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "ok")
        mock_open.assert_called_once()

    def test_parse_volume_brightness_commands(self) -> None:
        parsed_volume = parse_command("sube el volumen")
        parsed_brightness = parse_command("baja el brillo")
        parsed_mute = parse_command("mutea la pc")
        self.assertEqual(parsed_volume.intent, "volume")
        self.assertEqual(parsed_brightness.intent, "brightness")
        self.assertEqual(parsed_mute.intent, "volume")

    @patch("actions.subprocess.run")
    def test_list_usb_devices_windows(self, mock_run) -> None:
        ac = ActionController()
        ac.platform = "win32"
        mock_run.return_value = MagicMock(
            stdout="USB Composite Device\nNintendo Controller\n",
            returncode=0,
        )
        result = ac.list_usb_devices()
        self.assertEqual(result.get("status"), "ok")
        self.assertGreaterEqual(len(result.get("devices", [])), 1)

    def test_web_solver_problem_type(self) -> None:
        solver = WebSolver()
        self.assertEqual(solver.detect_problem_type("arduino sensor led"), "arduino")
        self.assertEqual(solver.detect_problem_type("python error api"), "programming")


if __name__ == "__main__":
    unittest.main()
