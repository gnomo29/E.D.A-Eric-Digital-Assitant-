from __future__ import annotations

import unittest

from eda.memory import MemoryManager


class PersistentMemoryTests(unittest.TestCase):
    def test_profile_updates_from_identity_phrase(self) -> None:
        mm = MemoryManager()
        facts = mm.update_user_profile_from_text("Me llamo Eric y soy programador")
        self.assertIn("name", facts)
        profile = mm.get_user_profile()
        self.assertEqual("Eric", profile.get("name"))

    def test_long_term_store_and_retrieve(self) -> None:
        mm = MemoryManager()
        mm.save_long_term_memory(
            "recuerda que mi color favorito es azul",
            "Entendido, guardado.",
            tags=["remember"],
            importance=5,
        )
        hits = mm.search_long_term_memory("color favorito", limit=2)
        self.assertTrue(hits)
        self.assertIn("azul", hits[0].get("user_text", ""))

    def test_identity_query_answer(self) -> None:
        mm = MemoryManager()
        mm.update_user_profile_from_text("Mi nombre es Eric")
        answer = mm.remember_identity_answer("¿cómo me llamo?")
        self.assertIn("Eric", answer)


if __name__ == "__main__":
    unittest.main()
