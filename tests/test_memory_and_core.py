import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eda import config
from eda.core import EDACore
from eda.memory import MemoryManager


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

    def test_forget_learned_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                patch.object(config, "MEMORY_FILE", base / "memoria.json"),
                patch.object(config, "BT_MEMORY_FILE", base / "bluetooth_devices.json"),
                patch.object(config, "SOLUTIONS_CACHE_FILE", base / "solutions_cache.json"),
            ):
                memory = MemoryManager()
                memory.save_learned_skill("abrir obs", "abre obs", "eda/actions.py", "open_app")
                self.assertTrue(memory.forget_learned_skill("abrir obs"))
                skills = memory.get_learned_skills()
                self.assertEqual(skills, {})

    def test_learned_commands_support_multiple_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                patch.object(config, "MEMORY_FILE", base / "memoria.json"),
                patch.object(config, "BT_MEMORY_FILE", base / "bluetooth_devices.json"),
                patch.object(config, "SOLUTIONS_CACHE_FILE", base / "solutions_cache.json"),
            ):
                memory = MemoryManager()
                self.assertTrue(memory.learn_command("abre nintendo", "abre obs", append=True))
                self.assertTrue(memory.learn_command("abre nintendo", "cambia a escena nintendo", append=True))
                actions = memory.get_learned_actions("abre nintendo")
                self.assertEqual(len(actions), 2)
                self.assertIn("abre obs", actions)
                self.assertIn("cambia a escena nintendo", actions)

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
        self.assertFalse(core.is_research_like_query("abre spotify?"))
        self.assertFalse(core.is_research_like_query("sube el volumen?"))
        self.assertFalse(core.is_research_like_query("¿abre chrome?"))
        self.assertTrue(core.is_research_like_query("¿Qué es un agujero negro?"))

    def test_should_activate_auto_learn_ignores_trivial_phrases(self) -> None:
        core = EDACore(memory_manager=object())
        self.assertFalse(
            core.should_activate_auto_learn("habla", "no puedo hablar en este momento"),
        )
        self.assertFalse(
            core.should_activate_auto_learn("hola", "no puedo ayudarte"),
        )

    @patch("eda.core.webbrowser.open")
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

    def test_find_learned_skill_rejects_short_substring(self) -> None:
        """Evita que 're' active una skill cuyo trigger contiene 'aprender'."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                patch.object(config, "MEMORY_FILE", base / "memoria.json"),
                patch.object(config, "BT_MEMORY_FILE", base / "bluetooth_devices.json"),
                patch.object(config, "SOLUTIONS_CACHE_FILE", base / "solutions_cache.json"),
            ):
                memory = MemoryManager()
                data = memory.get_memory()
                data["learned_skills"] = {
                    "cam": {
                        "trigger": "aprender a controlar la cámara",
                        "module": "eda/skills_auto.py",
                        "function": "learned_aprender_a_controlar_la",
                    }
                }
                memory.save_memory(data)
                self.assertIsNone(memory.find_learned_skill("re"))
                hit = memory.find_learned_skill("aprender a controlar la cámara")
                self.assertIsNotNone(hit)
                self.assertEqual(hit.get("function"), "learned_aprender_a_controlar_la")


if __name__ == "__main__":
    unittest.main()
