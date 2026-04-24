"""Herramientas de optimización y limpieza del sistema."""

from __future__ import annotations

import gc
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List
"""
Cómo guardar los cambios hechos en el proyecto en GitHub:

Pasos básicos por línea de comandos (Git):

1. Abre una terminal en la carpeta del proyecto.
2. Asegúrate de que tu repositorio está iniciado (ya tienes una carpeta .git). Si no, ejecuta:
   git init

3. Agrega los archivos modificados para guardar esos cambios:
   git add .

4. Haz un commit describiendo los cambios:
   git commit -m "Descripción breve de los cambios realizados"

5. Si ya tienes un repositorio remoto en GitHub y está enlazado, puedes subir así:
   git push

   Si es la primera vez, enlaza tu repositorio local con el remoto:
   git remote add origin https://github.com/TU-USUARIO/NOMBRE-REPO.git
   git push -u origin main   # O 'master', según tu rama principal

Notas:
- Debes tener configurado tu usuario y email en git (una sola vez):
  git config --global user.name "Tu Nombre"
  git config --global user.email "tu@email.com"
- Si usas autenticación por token de acceso personal, úsalo en lugar de tu contraseña.

También puedes hacer estos pasos desde interfaces gráficas como GitHub Desktop, VS Code o GitKraken.
"""

try:
    import psutil
except Exception:
    psutil = None

from logger import get_logger

log = get_logger("optimizer")


class Optimizer:
    """Ejecuta tareas de limpieza no destructivas."""

    def clean_temp_files(self) -> Dict[str, str]:
        """Elimina archivos temporales del sistema y usuario actual."""
        removed = 0
        errors = 0
        temp_paths = [Path(tempfile.gettempdir())]

        for temp_path in temp_paths:
            if not temp_path.exists():
                continue
            for item in temp_path.glob("*"):
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                    removed += 1
                except Exception:
                    errors += 1

        return {
            "status": "ok",
            "message": f"Limpieza temporal completada. Eliminados: {removed}, errores: {errors}",
        }

    def free_memory(self) -> Dict[str, str]:
        """Fuerza recolección de basura para liberar memoria Python."""
        try:
            gc.collect()
            return {"status": "ok", "message": "Recolección de memoria ejecutada correctamente"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def organize_files(self, target_dir: Path) -> Dict[str, str]:
        """Organiza archivos por extensión dentro de un directorio objetivo."""
        if not target_dir.exists() or not target_dir.is_dir():
            return {"status": "error", "message": f"Directorio no válido: {target_dir}"}

        moved = 0
        try:
            for item in target_dir.iterdir():
                if item.is_dir():
                    continue
                ext = item.suffix.lower().lstrip(".") or "otros"
                folder = target_dir / f"by_{ext}"
                folder.mkdir(exist_ok=True)
                destination = folder / item.name
                if destination.exists():
                    continue
                shutil.move(str(item), str(destination))
                moved += 1
            return {"status": "ok", "message": f"Organización completada. Archivos movidos: {moved}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def ram_status(self) -> Dict[str, str]:
        """Obtiene estado de RAM."""
        if psutil is None:
            return {"status": "error", "message": "psutil no disponible"}
        vm = psutil.virtual_memory()
        return {
            "status": "ok",
            "message": f"RAM usada: {vm.percent}% ({vm.used // (1024**2)} MB de {vm.total // (1024**2)} MB)",
        }

    def health_report(self) -> Dict[str, str | List[str]]:
        """Genera un reporte de salud del sistema."""
        checks: List[str] = []
        if psutil is None:
            return {"status": "error", "message": "psutil no disponible", "checks": checks}

        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent

        checks.append(f"CPU: {cpu:.0f}%")
        checks.append(f"RAM: {mem:.0f}%")
        checks.append(f"DISCO: {disk:.0f}%")

        status = "ok"
        if cpu > 90 or mem > 90 or disk > 95:
            status = "warning"

        return {"status": status, "message": " | ".join(checks), "checks": checks}

    def optimize(self) -> Dict[str, str]:
        """Secuencia de optimización segura."""
        temp_result = self.clean_temp_files()
        mem_result = self.free_memory()
        ram_result = self.ram_status()
        report = self.health_report()

        return {
            "status": "ok",
            "message": (
                f"{temp_result.get('message', '')} | "
                f"{mem_result.get('message', '')} | "
                f"{ram_result.get('message', '')} | "
                f"Salud: {report.get('message', '')}"
            ),
        }
