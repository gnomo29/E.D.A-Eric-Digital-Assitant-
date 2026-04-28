from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from skills.creative_blender import build_scene_script, run_blender_render
from skills.document_specialist import create_cv_docx, create_presentation, create_report_docx
from skills.gaming_specialist import detect_gaming_clients, launch_steam_game


class SpecialistsTests(unittest.TestCase):
    def test_blender_script_generation_cube(self) -> None:
        script = build_scene_script(shape="cubo", output_png="x.png")
        self.assertIn("primitive_cube_add", script)
        self.assertIn("x.png", script)

    def test_blender_script_generation_sphere(self) -> None:
        script = build_scene_script(shape="esfera", output_png="y.png")
        self.assertIn("primitive_uv_sphere_add", script)

    @patch("skills.creative_blender.ResourceMonitor.has_free_ram", return_value=False)
    def test_blender_ram_guard_blocks(self, _mock_ram) -> None:
        result = run_blender_render("blender.exe", shape="cube")
        self.assertEqual(result.get("status"), "error")
        self.assertIn("RAM insuficiente", result.get("message", ""))

    @patch("skills.creative_blender.ResourceMonitor.has_free_ram", return_value=True)
    @patch("skills.creative_blender.subprocess.run")
    def test_blender_run_invokes_background_python(self, mock_run, _mock_ram) -> None:
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        result = run_blender_render("blender.exe", shape="cube", script_path="tmp_scene.py")
        self.assertEqual(result.get("status"), "ok")
        args = mock_run.call_args.args[0]
        self.assertIn("--background", args)
        self.assertIn("--python", args)

    @patch("skills.document_specialist.Document")
    def test_create_report_docx(self, mock_document) -> None:
        doc_obj = MagicMock()
        mock_document.return_value = doc_obj
        result = create_report_docx("Informe", ["Uno", "Dos"], "informe.docx")
        self.assertEqual(result.get("status"), "ok")
        doc_obj.save.assert_called_once_with("informe.docx")

    @patch("skills.document_specialist.Document")
    def test_create_cv_docx(self, mock_document) -> None:
        doc_obj = MagicMock()
        mock_document.return_value = doc_obj
        result = create_cv_docx("Ada Lovelace", "Ingeniera de software", "cv.docx")
        self.assertEqual(result.get("status"), "ok")
        doc_obj.save.assert_called_once_with("cv.docx")

    @patch("skills.document_specialist.Presentation")
    def test_create_presentation_pptx(self, mock_presentation) -> None:
        deck = MagicMock()
        deck.slide_layouts = [MagicMock(), MagicMock()]
        deck.slides.add_slide.return_value = MagicMock(shapes=MagicMock(), placeholders=[MagicMock(), MagicMock()])
        mock_presentation.return_value = deck
        result = create_presentation("IA", 5, "ia.pptx")
        self.assertEqual(result.get("status"), "ok")
        deck.save.assert_called_once_with("ia.pptx")

    @patch("skills.gaming_specialist.Path.exists")
    def test_detect_gaming_clients_with_mocked_paths(self, mock_exists) -> None:
        mock_exists.side_effect = [True, False, False, False]
        result = detect_gaming_clients()
        self.assertTrue(result.get("steam_installed"))
        self.assertFalse(result.get("epic_installed"))

    @patch("skills.gaming_specialist.os.startfile", create=True)
    def test_launch_steam_game_uri(self, mock_startfile) -> None:
        result = launch_steam_game(570)
        self.assertEqual(result.get("status"), "ok")
        mock_startfile.assert_called_once()

    @patch("skills.gaming_specialist.os.startfile", side_effect=OSError("no"), create=True)
    @patch("skills.gaming_specialist.subprocess.run")
    def test_launch_steam_game_fallback_cmd(self, mock_run, _mock_startfile) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = launch_steam_game(730)
        self.assertEqual(result.get("status"), "ok")
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()

