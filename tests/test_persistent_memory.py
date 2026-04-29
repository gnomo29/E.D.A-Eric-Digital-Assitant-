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

    def test_preference_and_context_split(self) -> None:
        mm = MemoryManager()
        updated = mm.update_preferences_from_text("Prefiero respuestas cortas y directas")
        self.assertTrue(updated)
        prefs = mm.get_user_preferences()
        self.assertIn("preferencia_general", prefs)

        mm.update_preferences_from_text("Por ahora responde en formato lista")
        ctx = mm.get_active_context()
        self.assertIn("preferencia_temporal", ctx)

    def test_memory_snapshot_cycle(self) -> None:
        mm = MemoryManager()
        snap = mm.create_memory_snapshot("test")
        self.assertIsNotNone(snap)
        rows = mm.list_memory_snapshots(limit=5)
        self.assertTrue(rows)
        ok = mm.restore_memory_snapshot(rows[0])
        self.assertTrue(ok)
        cmp = mm.compare_memory_snapshots(rows[0], rows[0])
        self.assertTrue(cmp.get("ok"))
        self.assertTrue(cmp.get("same"))

    def test_persist_interaction_single_write_path(self) -> None:
        mm = MemoryManager()
        ok = mm.persist_interaction("hola eda", "hola", intent="chat", entity="", record_behavior=True)
        self.assertTrue(ok)
        mem = mm.get_memory()
        self.assertTrue(mem.get("history"))
        self.assertTrue(mem.get("chat_history"))


if __name__ == "__main__":
    unittest.main()
