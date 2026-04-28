"""Especialista creativo para tareas Blender offline."""

from __future__ import annotations

import subprocess
from pathlib import Path

from eda.telemetry import ResourceMonitor


def build_scene_script(shape: str = "cube", output_png: str = "render.png") -> str:
    primitive = "primitive_cube_add" if shape.lower().startswith("cub") else "primitive_uv_sphere_add"
    return (
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        f"bpy.ops.mesh.{primitive}(location=(0,0,0))\n"
        "cam_data = bpy.data.cameras.new(name='Cam')\n"
        "cam_obj = bpy.data.objects.new('Cam', cam_data)\n"
        "bpy.context.scene.collection.objects.link(cam_obj)\n"
        "cam_obj.location = (3.0, -3.0, 2.0)\n"
        "cam_obj.rotation_euler = (1.1, 0, 0.8)\n"
        "bpy.context.scene.camera = cam_obj\n"
        f"bpy.context.scene.render.filepath = r'{output_png}'\n"
        "bpy.ops.render.render(write_still=True)\n"
    )


def run_blender_render(
    blender_exe: str,
    *,
    shape: str = "cube",
    script_path: str = "temp_blender_scene.py",
    output_png: str = "render.png",
) -> dict[str, str]:
    monitor = ResourceMonitor()
    if not monitor.has_free_ram(1.0):
        return {
            "status": "error",
            "message": "RAM insuficiente (<1GB libre). Cierra procesos y reintenta.",
        }
    script_text = build_scene_script(shape=shape, output_png=output_png)
    path = Path(script_path)
    path.write_text(script_text, encoding="utf-8")
    try:
        completed = subprocess.run(
            [blender_exe, "--background", "--python", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            return {"status": "error", "message": (completed.stderr or "Fallo Blender")[:300]}
        return {"status": "ok", "message": f"Render generado en {output_png}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

