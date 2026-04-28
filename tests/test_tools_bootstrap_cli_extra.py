from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, mock_open, patch

from tools import bootstrap_v3


class BootstrapCliExtraTests(unittest.TestCase):
    def _args(self, **kwargs):
        base = {
            "only_sign": False,
            "no_tests": True,
            "telegram_smoke": False,
            "telegram_token": "",
            "telegram_chat": "",
            "skip_logs": True,
            "dry_run": False,
            "yes": False,
            "verbose": False,
        }
        base.update(kwargs)
        return argparse.Namespace(**base)

    @patch("builtins.input", side_effect=AssertionError("No debe pedir input en --yes"))
    @patch("tools.bootstrap_v3.Path.open", new_callable=mock_open)
    @patch("tools.bootstrap_v3.run_tests")
    @patch("tools.bootstrap_v3.telegram_smoke_test")
    @patch("tools.bootstrap_v3.rotate_and_compress_logs")
    @patch("tools.bootstrap_v3.validate_integrity")
    @patch("tools.bootstrap_v3.sign_all_skills")
    @patch("tools.bootstrap_v3.backup_signatures")
    def test_yes_mode_non_interactive_and_audited(
        self,
        mock_backup,
        mock_sign,
        mock_validate,
        _mock_rotate,
        _mock_smoke,
        _mock_tests,
        mock_file_open,
        _mock_input,
    ) -> None:
        args = self._args(yes=True, no_tests=False, skip_logs=False, telegram_smoke=False)
        output = io.StringIO()
        with redirect_stdout(output):
            rc = bootstrap_v3.run_bootstrap(args)
        self.assertEqual(rc, 0)
        self.assertIn("modo CI confirmado", output.getvalue())
        mock_backup.assert_called_once()
        mock_sign.assert_called_once()
        mock_validate.assert_called_once()
        # Verifica escritura audit JSONL
        handle = mock_file_open()
        self.assertTrue(handle.write.called, "Se esperaba escritura de auditoría en bootstrap_actions.log")
        writes = "".join(call.args[0] for call in handle.write.call_args_list if call.args)
        self.assertIn('"mode": "yes"', writes)

    @patch("tools.bootstrap_v3.requests.post")
    def test_telegram_smoke_with_explicit_args_calls_api(self, mock_post) -> None:
        mock_post.return_value = MagicMock(status_code=200)
        args = self._args(
            telegram_smoke=True,
            telegram_token="FAKETOKEN",
            telegram_chat="12345",
            verbose=True,
            skip_logs=True,
            no_tests=True,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            rc = bootstrap_v3.run_bootstrap(args)
        self.assertEqual(rc, 0)
        mock_post.assert_called_once()
        called_url = mock_post.call_args.args[0]
        payload = mock_post.call_args.kwargs.get("json", {})
        self.assertEqual(called_url, "https://api.telegram.org/botFAKETOKEN/sendMessage")
        self.assertEqual(str(payload.get("chat_id")), "12345")
        # El token no debe mostrarse en claro en logs
        text = output.getvalue()
        self.assertNotIn("FAKETOKEN", text)
        self.assertIn("FA****EN", text)

    @patch("tools.bootstrap_v3.requests.post")
    def test_telegram_smoke_missing_credentials_returns_friendly_error(self, mock_post) -> None:
        args = self._args(telegram_smoke=True, telegram_token="", telegram_chat="", no_tests=True, skip_logs=True)
        output = io.StringIO()
        with redirect_stdout(output):
            rc = bootstrap_v3.run_bootstrap(args)
        self.assertEqual(rc, 1)
        self.assertIn("Faltan credenciales Telegram", output.getvalue())
        mock_post.assert_not_called()

    @patch("tools.bootstrap_v3.requests.post")
    def test_obfuscated_token_helper(self, _mock_post) -> None:
        obf = bootstrap_v3._obfuscate_secret("ABCD1234")  # pylint: disable=protected-access
        self.assertEqual(obf, "AB****34")


if __name__ == "__main__":
    unittest.main()

