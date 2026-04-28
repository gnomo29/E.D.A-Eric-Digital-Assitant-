from __future__ import annotations

import unittest

from eda.nlp_utils import detect_confirmation_mode


class ConfirmationParsingTests(unittest.TestCase):
    def test_yes_variants(self) -> None:
        for sample in ["si", "sí", "s", "confirmo", "acepto", "ok", "dale", "procede"]:
            self.assertEqual(detect_confirmation_mode(sample), "yes")

    def test_no_variants(self) -> None:
        for sample in ["no", "n", "nop", "cancelar", "detener", "stop"]:
            self.assertEqual(detect_confirmation_mode(sample), "no")

    def test_force_variants(self) -> None:
        for sample in ["forzar", "forzar cierre", "kill", "force", "sí, forzar"]:
            self.assertEqual(detect_confirmation_mode(sample), "force")


if __name__ == "__main__":
    unittest.main()
