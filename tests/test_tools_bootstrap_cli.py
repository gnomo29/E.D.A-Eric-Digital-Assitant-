from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools import bootstrap_v3


class BootstrapCliTests(unittest.TestCase):
    def _args(self, **kwargs):
        base = {
            "only_sign": False,
            "no_tests": False,
            "telegram_smoke": False,
            "telegram_token": "",
            "telegram_chat": "",
            "skip_logs": False,
            "dry_run": False,
            "yes": False,
            "verbose": False,
        }
        base.update(kwargs)
        return argparse.Namespace(**base)

    @patch("tools.bootstrap_v3.run_tests")
    @patch("tools.bootstrap_v3.telegram_smoke_test")
    @patch("tools.bootstrap_v3.rotate_and_compress_logs")
    @patch("tools.bootstrap_v3.validate_integrity")
    @patch("tools.bootstrap_v3.sign_all_skills")
    @patch("tools.bootstrap_v3.backup_signatures")
    def test_only_sign_calls_only_signing_steps(
        self,
        mock_backup,
        mock_sign,
        mock_validate,
        mock_rotate,
        mock_smoke,
        mock_tests,
    ) -> None:
        rc = bootstrap_v3.run_bootstrap(self._args(only_sign=True))
        self.assertEqual(rc, 0)
        mock_backup.assert_called_once()
        mock_sign.assert_called_once()
        mock_validate.assert_not_called()
        mock_rotate.assert_not_called()
        mock_smoke.assert_not_called()
        mock_tests.assert_not_called()

    @patch("tools.bootstrap_v3.subprocess.run")
    @patch("tools.bootstrap_v3.resolve_telegram_credentials", return_value=("", ""))
    def test_no_tests_skips_test_execution(self, _mock_creds, mock_subprocess_run) -> None:
        rc = bootstrap_v3.run_bootstrap(self._args(no_tests=True, skip_logs=True))
        self.assertEqual(rc, 0)
        # signing still calls subprocess for sign_skill.py
        called = [" ".join(call.args[0]) for call in mock_subprocess_run.call_args_list]
        self.assertTrue(any("sign_skill.py" in c for c in called))
        self.assertFalse(any("unittest discover" in c for c in called))

    def test_dry_run_does_not_modify_signatures_or_create_backup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skills = root / "skills"
            backups = root / "data" / "backups" / "signatures"
            skills.mkdir(parents=True)
            signatures = skills / "signatures.json"
            signatures.write_text('{"files":{"a.py":"sig"}}', encoding="utf-8")
            before = signatures.read_text(encoding="utf-8")
            with patch("tools.bootstrap_v3.Path.resolve", return_value=(root / "tools" / "bootstrap_v3.py")):
                rc = bootstrap_v3.run_bootstrap(self._args(dry_run=True, no_tests=True, skip_logs=True))
            self.assertEqual(rc, 0)
            self.assertEqual(signatures.read_text(encoding="utf-8"), before)
            self.assertFalse(backups.exists())

    @patch("tools.bootstrap_v3.requests.post")
    def test_telegram_smoke_requires_credentials(self, mock_post) -> None:
        with self.assertRaises(ValueError):
            bootstrap_v3.telegram_smoke_test(force=True, token="", chat_id="", dry_run=False, verbose=False)
        mock_post.assert_not_called()
        bootstrap_v3.telegram_smoke_test(force=True, token="123:abc", chat_id="999", dry_run=False, verbose=False)
        mock_post.assert_called_once()


if __name__ == "__main__":
    unittest.main()

