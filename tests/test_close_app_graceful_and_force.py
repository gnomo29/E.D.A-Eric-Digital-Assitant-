from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from eda.actions import ActionController


class CloseAppRobustTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actions = ActionController()

    @patch("eda.actions.audit_event")
    @patch.object(ActionController, "_close_single_process", return_value="terminate")
    @patch.object(ActionController, "_find_processes_by_app_name")
    def test_close_app_graceful(self, mock_find: MagicMock, _mock_close: MagicMock, _mock_audit: MagicMock) -> None:
        proc = MagicMock()
        proc.pid = 1234
        proc.is_running.side_effect = [False]
        mock_find.return_value = [proc]
        out = self.actions.close_app_robust("chrome", force=False)
        self.assertEqual(out.get("status"), "ok")

    @patch("eda.actions.subprocess.run")
    @patch("eda.actions.audit_event")
    @patch.object(ActionController, "_find_processes_by_app_name")
    def test_close_app_force(self, mock_find: MagicMock, _mock_audit: MagicMock, mock_run: MagicMock) -> None:
        proc = MagicMock()
        proc.pid = 2222
        proc.is_running.side_effect = [True, False]
        proc.status.return_value = "stopped"
        mock_find.return_value = [proc]
        out = self.actions.close_app_robust("chrome", force=True)
        self.assertIn(out.get("status"), {"ok", "error"})
        self.assertTrue(mock_run.called)


if __name__ == "__main__":
    unittest.main()
