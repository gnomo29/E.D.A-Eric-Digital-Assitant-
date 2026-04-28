from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from eda.actions import ActionController
from eda.nlp_utils import parse_command
from eda.orchestrator import CommandOrchestrator
from eda.vision import VisionService


class VisionAndFileSuperpowersTests(unittest.TestCase):
    def test_parse_command_detects_organize_directory(self) -> None:
        parsed = parse_command("organiza la carpeta C:/Temp/Descargas")
        self.assertEqual(parsed.intent, "organize_directory")
        self.assertEqual(parsed.entity, "c:/temp/descargas")

    @patch("eda.vision.pyautogui")
    def test_vision_capture_is_resized_and_returns_jpeg_bytes(self, mock_pyautogui) -> None:
        img = Image.new("RGB", (3840, 2160), color=(10, 10, 10))
        mock_pyautogui.screenshot.return_value = img
        service = VisionService()

        payload = service.capture_screen()

        self.assertTrue(payload.startswith(b"\xff\xd8"), "Expected JPEG header bytes")
        self.assertLess(len(payload), 2_000_000, "Optimized screenshot should stay compact in memory")

    @patch("eda.vision.VisionService.capture_screen", return_value=b"fake-bytes")
    def test_vision_uses_available_ollama_model(self, _mock_capture) -> None:
        service = VisionService()
        service._pick_vision_model = MagicMock(return_value="llava")  # type: ignore[method-assign]
        mock_response = MagicMock()
        mock_response.content = b'{"response":"Se ve una terminal con un traceback."}'
        mock_response.json.return_value = {"response": "Se ve una terminal con un traceback."}
        mock_response.raise_for_status.return_value = None
        service.http.post = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

        result = service.analyze_screen(prompt="Explícame este error")

        self.assertEqual(result.get("status"), "ok")
        self.assertIn("traceback", result.get("message", "").lower())
        self.assertEqual(result.get("model"), "llava")

    def test_actions_builds_file_organization_plan(self) -> None:
        controller = ActionController()
        with patch("eda.actions.os.path.isdir", return_value=True), patch("eda.actions.os.scandir") as mock_scandir:
            file_jpg = MagicMock()
            file_jpg.is_file.return_value = True
            file_jpg.name = "foto.jpg"
            file_jpg.path = "C:/Temp/Descargas/foto.jpg"
            file_pdf = MagicMock()
            file_pdf.is_file.return_value = True
            file_pdf.name = "manual.pdf"
            file_pdf.path = "C:/Temp/Descargas/manual.pdf"
            mock_scandir.return_value = [file_jpg, file_pdf]

            plan = controller.plan_directory_organization("C:/Temp/Descargas")

        self.assertEqual(plan.get("status"), "ok")
        moves = plan.get("moves", [])
        self.assertEqual(len(moves), 2)
        buckets = {move["bucket"] for move in moves}
        self.assertEqual(buckets, {"Imagenes", "Documentos"})

    def test_actions_apply_plan_moves_files(self) -> None:
        controller = ActionController()
        plan = {
            "moves": [
                {
                    "source": "C:/Temp/Descargas/foto.jpg",
                    "destination_dir": "C:/Temp/Descargas/Imagenes",
                    "destination": "C:/Temp/Descargas/Imagenes/foto.jpg",
                    "bucket": "Imagenes",
                }
            ]
        }
        with patch("eda.actions.os.makedirs") as mock_makedirs, patch("eda.actions.shutil.move") as mock_move:
            result = controller.apply_directory_organization_plan(plan)

        self.assertEqual(result.get("status"), "ok")
        mock_makedirs.assert_called_once()
        mock_move.assert_called_once_with(
            "C:/Temp/Descargas/foto.jpg",
            "C:/Temp/Descargas/Imagenes/foto.jpg",
        )

    def test_orchestrator_requires_confirmation_before_move(self) -> None:
        memory = MagicMock()
        memory.get_memory.return_value = {"chat_history": []}
        core = MagicMock()
        action_agent = MagicMock()
        action_agent.try_handle.return_value = (False, "")
        actions = MagicMock()
        actions.execute_navigation_command.return_value = None
        actions.plan_directory_organization.return_value = {
            "status": "ok",
            "message": "Plan listo",
            "moves": [
                {
                    "source": "a.jpg",
                    "destination_dir": "Imagenes",
                    "destination": "Imagenes/a.jpg",
                    "bucket": "Imagenes",
                }
            ],
        }
        actions.apply_directory_organization_plan.return_value = {"status": "ok", "message": "Organización completada"}
        vision = MagicMock()

        orchestrator = CommandOrchestrator(
            memory=memory,
            core=core,
            action_agent=action_agent,
            actions=actions,
            vision=vision,
        )

        first = orchestrator.orchestrate("organiza la carpeta C:/Temp/Descargas")
        second = orchestrator.orchestrate("sí")

        self.assertEqual(first.source, "organize_directory_plan")
        self.assertIn("¿Procedo", first.answer)
        self.assertEqual(second.source, "organize_directory_apply")
        actions.apply_directory_organization_plan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
