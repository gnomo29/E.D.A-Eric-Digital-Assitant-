from __future__ import annotations

import unittest

from eda.qa import QAService


class QAAnswersTests(unittest.TestCase):
    def test_known_answer_from_local_kb(self) -> None:
        qa = QAService()
        answer, source = qa.answer("¿Quién descubrió América?")
        self.assertIn("Colon", answer)
        self.assertEqual(source, "qa_kb_local")


if __name__ == "__main__":
    unittest.main()
