import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eda import config
from eda.improvement_planner import ImprovementPlanner
from eda.memory import MemoryManager
from eda.nlp_utils import parse_command
from eda.web_solver import WebSolver


class ImprovementPlannerTests(unittest.TestCase):
    def test_scan_eda_finds_volume_related_module(self) -> None:
        root = Path(__file__).resolve().parent.parent
        planner = ImprovementPlanner(root)
        hits = planner.scan_eda_python("subir volumen y audio del sistema")
        paths = [h["path"] for h in hits]
        self.assertTrue(any("actions" in p for p in paths) or any("gui" in p for p in paths))

    def test_build_plan_without_web(self) -> None:
        root = Path(__file__).resolve().parent.parent
        planner = ImprovementPlanner(root)
        plan = planner.build_plan("memoria y recordatorios", include_web=False, web_solver=None)
        self.assertIn("request", plan)
        self.assertEqual(plan.get("web"), [])
        text = planner.format_plan_for_user(plan)
        self.assertIn("Plan de capacidad", text)

    def test_parse_capability_plan(self) -> None:
        p = parse_command("¿cómo implementarías abrir Spotify y ajustar volumen?")
        self.assertEqual(p.intent, "capability_plan")
        self.assertTrue(len(p.entity) > 3)


class MemoryBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._mem_path = Path(self._tmpdir.name) / "memoria.json"
        self._patch = patch.object(config, "MEMORY_FILE", self._mem_path)
        self._patch.start()
        self.mem = MemoryManager()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    def test_record_and_insights(self) -> None:
        for i in range(15):
            self.mem.record_behavior_event("open_app", "notepad", f"abre notepad test {i}")
        ins = self.mem.get_behavior_insights(window=50)
        self.assertGreaterEqual(ins["total"], 12)
        self.assertEqual(ins["top_intents"][0][0], "open_app")

    def test_clear_behavior_events(self) -> None:
        self.mem.record_behavior_event("chat", "", "hola")
        self.assertTrue(self.mem.clear_behavior_events())
        data = self.mem.get_memory()
        self.assertEqual(data.get("behavior_events"), [])


class WebSolverImportPolicyTests(unittest.TestCase):
    def test_rejects_disallowed_import(self) -> None:
        mock_core = MagicMock()
        mock_core.is_ollama_alive = lambda: True
        mock_core.ask = lambda _prompt: (
            "```python\ndef learned_x(command_text: str = \"\") -> dict:\n"
            "    import os\n"
            "    return {'status': 'ok', 'message': 'x'}\n```"
        )
        solver = WebSolver(core=mock_core)
        with patch.object(solver, "search_learning_resources", return_value=[]):
            payload = solver.generate_autolearn_payload("tarea ficticia xyz123only", intent="chat")
        self.assertEqual(payload.get("status"), "ok")
        code = str(payload.get("code", ""))
        self.assertNotIn("import os", code)


if __name__ == "__main__":
    unittest.main()
