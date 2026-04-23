import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from core import EDACore
from memory import MemoryManager


class MemoryAndCoreTests(unittest.TestCase):
    def test_add_history_updates_legacy_and_chat_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                patch.object(config, "MEMORY_FILE", base / "memoria.json"),
                patch.object(config, "BT_MEMORY_FILE", base / "bluetooth_devices.json"),
                patch.object(config, "SOLUTIONS_CACHE_FILE", base / "solutions_cache.json"),
            ):
                memory = MemoryManager()
                self.assertTrue(memory.add_history("hola", "que tal"))
                data = memory.get_memory()
                self.assertEqual(data["history"][-1]["user"], "hola")
                self.assertEqual(data["history"][-1]["assistant"], "que tal")
                self.assertEqual(data["chat_history"][-2]["role"], "user")
                self.assertEqual(data["chat_history"][-1]["role"], "assistant")

    def test_clear_all_memory_resets_learned_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                patch.object(config, "MEMORY_FILE", base / "memoria.json"),
                patch.object(config, "BT_MEMORY_FILE", base / "bluetooth_devices.json"),
                patch.object(config, "SOLUTIONS_CACHE_FILE", base / "solutions_cache.json"),
            ):
                memory = MemoryManager()
                memory.remember("clave", "valor")
                memory.save_knowledge("tema", "pregunta", "respuesta breve suficiente", source="test")
                memory.add_history("hola", "respuesta")
                self.assertTrue(memory.clear_all_memory())
                data = memory.get_memory()
                self.assertEqual(data.get("remembered", {}), {})
                self.assertEqual(data.get("knowledge_base", {}), {})
                self.assertEqual(data.get("history", []), [])

    def test_save_and_get_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                patch.object(config, "MEMORY_FILE", base / "memoria.json"),
                patch.object(config, "BT_MEMORY_FILE", base / "bluetooth_devices.json"),
                patch.object(config, "SOLUTIONS_CACHE_FILE", base / "solutions_cache.json"),
            ):
                memory = MemoryManager()
                reminders = [{"id": "1", "message": "probar", "scheduled_for": "2026-04-23 15:00:00", "mode": "relative"}]
                self.assertTrue(memory.save_reminders(reminders))
                loaded = memory.get_reminders()
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0]["id"], "1")
                self.assertTrue(memory.remember("web_url::youtube", "https://www.youtube.com"))
                self.assertEqual(memory.recall("web_url::youtube"), "https://www.youtube.com")

    def test_build_prompt_accepts_both_history_formats(self) -> None:
        core = EDACore(memory_manager=object())
        history = [
            {"user": "legacy user", "assistant": "legacy assistant"},
            {"role": "user", "content": "new user"},
            {"role": "assistant", "content": "new assistant"},
        ]
        prompt = core.build_prompt("mensaje actual", history=history)
        self.assertIn("Usuario: legacy user", prompt)
        self.assertIn("E.D.A.: legacy assistant", prompt)
        self.assertIn("Usuario: new user", prompt)
        self.assertIn("E.D.A.: new assistant", prompt)

    def test_is_research_like_query(self) -> None:
        core = EDACore(memory_manager=object())
        self.assertTrue(core.is_research_like_query("quien descubrio america"))
        self.assertTrue(core.is_research_like_query("que es un condensador"))
        self.assertFalse(core.is_research_like_query("abre spotify"))

    @patch("core.webbrowser.open")
    def test_open_browser_for_research(self, mock_open) -> None:
        core = EDACore(memory_manager=object())
        core.web_search.search_google_snippets = lambda _q, max_results=4: [
            {"title": "Wikipedia", "url": "https://es.wikipedia.org/wiki/Condensador_el%C3%A9ctrico", "snippet": "x"},
            {"title": "Otra", "url": "https://example.com/condensador", "snippet": "y"},
        ]
        opened = core.open_browser_for_research("que es un condensador", max_pages=2)
        self.assertGreaterEqual(len(opened), 2)
        self.assertTrue(any("google.com/search" in url for url in opened))
        self.assertTrue(mock_open.called)


if __name__ == "__main__":
    unittest.main()
