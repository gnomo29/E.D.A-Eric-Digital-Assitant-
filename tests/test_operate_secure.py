from __future__ import annotations

import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import operate_secure


class OperateSecureTests(unittest.TestCase):
    def _args(self, **overrides) -> Namespace:
        base = {
            "dry_run": False,
            "rotate_keys": True,
            "smoke_loader": True,
            "revoke": "",
            "revoke_reason": "operate_secure",
            "rollback_on_fail": True,
            "yes": True,
            "telegram_smoke": False,
            "telegram_token": "",
            "telegram_chat": "",
            "timeout": 600,
            "verbose": False,
            "force": True,
            "no_tests": True,
        }
        base.update(overrides)
        return Namespace(**base)

    def test_dry_run_no_backup_created(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            code = operate_secure.run_operate_secure(self._args(dry_run=True), root=root)
            self.assertEqual(code, 0)
            backups = root / "data" / "backups"
            self.assertFalse(backups.exists())

    @patch("tools.operate_secure.send_telegram_summary")
    @patch("tools.operate_secure.smoke_loader", return_value={"ok": True, "loaded": ["example"], "missing": []})
    @patch("tools.operate_secure.run_rotation", return_value={"status": "ok", "message": "rotated"})
    def test_rotate_and_smoke_success(self, _mock_rotate, _mock_smoke, _mock_tg) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            code = operate_secure.run_operate_secure(self._args(), root=root)
            self.assertEqual(code, 0)
            self.assertTrue((root / "data" / "backups").exists())

    @patch("tools.operate_secure.restore_backup", return_value={"status": "ok", "message": "restored"})
    @patch("tools.operate_secure.rollback_rotation", return_value={"status": "ok", "message": "rolled"})
    @patch("tools.operate_secure.smoke_loader", return_value={"ok": False, "loaded": [], "missing": ["example"]})
    @patch("tools.operate_secure.run_rotation", return_value={"status": "ok", "message": "rotated"})
    def test_smoke_fail_triggers_rollback_exit2(self, _mock_rotate, _mock_smoke, mock_rb, _mock_restore) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            code = operate_secure.run_operate_secure(self._args(), root=root)
            self.assertEqual(code, 2)
            self.assertTrue(mock_rb.called)

    @patch("tools.operate_secure.revoke_skill", return_value=True)
    @patch("tools.operate_secure.smoke_loader", return_value={"ok": True, "loaded": ["example"], "missing": []})
    @patch("tools.operate_secure.run_rotation", return_value={"status": "ok", "message": "rotated"})
    def test_revoke_runs_only_after_smoke_success(self, _mock_rotate, _mock_smoke, mock_revoke) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            code = operate_secure.run_operate_secure(self._args(revoke="example.py"), root=root)
            self.assertEqual(code, 0)
            mock_revoke.assert_called_once()

    @patch("tools.operate_secure.send_telegram_summary")
    @patch("tools.operate_secure.smoke_loader", return_value={"ok": True, "loaded": ["example"], "missing": []})
    @patch("tools.operate_secure.run_rotation", return_value={"status": "ok", "message": "rotated"})
    def test_telegram_smoke_invoked_and_token_not_printed(self, _mock_rotate, _mock_smoke, mock_tg) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = operate_secure.run_operate_secure(
                    self._args(telegram_smoke=True, telegram_token="ABCDSECRETXYZ", telegram_chat="123456", verbose=True),
                    root=root,
                )
            self.assertEqual(code, 0)
            self.assertTrue(mock_tg.called)
            output = buffer.getvalue()
            self.assertNotIn("ABCDSECRETXYZ", output)


if __name__ == "__main__":
    unittest.main()

