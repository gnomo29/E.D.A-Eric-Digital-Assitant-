from __future__ import annotations

import unittest
from unittest.mock import patch

from eda.actions import ActionController


class WebAppDetectionTests(unittest.TestCase):
    def _controller(self) -> ActionController:
        ctrl = ActionController()
        ctrl.platform = "win32"
        return ctrl

    @patch("eda.actions.log.info")
    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_open_youtube_uses_browser(self, mock_web_open, mock_log_info) -> None:
        ctrl = self._controller()
        result = ctrl.open_app("youtube")
        self.assertEqual(result.get("status"), "ok", f"Expected OK opening youtube, got: {result}")
        mock_web_open.assert_called_once_with("https://www.youtube.com")
        self.assertTrue(
            any("detectado como sitio web" in str(c.args[0]).lower() for c in mock_log_info.call_args_list),
            "Expected web-detection log message for youtube opening",
        )

    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_open_domain_normalizes_https(self, mock_web_open) -> None:
        ctrl = self._controller()
        result = ctrl.open_app("example.com")
        self.assertEqual(result.get("status"), "ok", f"Expected OK opening example.com, got: {result}")
        mock_web_open.assert_called_once_with("https://example.com")

    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_open_localhost_with_port(self, mock_web_open) -> None:
        ctrl = self._controller()
        result = ctrl.open_app("localhost:8000")
        self.assertEqual(result.get("status"), "ok", f"Expected OK opening localhost:8000, got: {result}")
        mock_web_open.assert_called_once_with("http://localhost:8000")

    @patch("eda.actions.subprocess.Popen")
    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_open_notepad_stays_local_app(self, mock_web_open, mock_popen) -> None:
        ctrl = self._controller()
        result = ctrl.open_app("notepad")
        self.assertEqual(result.get("status"), "ok", f"Expected local app open for notepad, got: {result}")
        mock_popen.assert_called_once()
        mock_web_open.assert_not_called()

    @patch.object(ActionController, "_find_app_path", return_value=None)
    @patch.object(ActionController, "_find_start_menu_app_id", return_value=None)
    @patch("eda.actions.shutil.which", return_value=None)
    @patch("eda.actions.webbrowser.open", return_value=True)
    def test_false_positive_local_file_like_domain_is_not_web(
        self, mock_web_open, _mock_which, _mock_appid, _mock_find_path
    ) -> None:
        ctrl = self._controller()
        result = ctrl.open_app("lista.com.txt")
        self.assertNotEqual(
            result.get("status"),
            "ok",
            f"Expected local attempt to fail for fake file-like target, got: {result}",
        )
        mock_web_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()

