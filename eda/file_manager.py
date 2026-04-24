"""Gestor CRUD de archivos con validaciones."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .logger import get_logger

log = get_logger("file_manager")


class FileManager:
    """CRUD completo para archivos dentro de un directorio base."""

    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path.resolve()

    def _resolve(self, relative_path: str) -> Path:
        target = (self.base_path / relative_path).resolve()
        if self.base_path not in target.parents and target != self.base_path:
            raise ValueError("Ruta fuera del proyecto no permitida")
        return target

    def create_file(self, relative_path: str, content: str = "") -> Dict[str, str]:
        try:
            path = self._resolve(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"status": "ok", "message": f"Archivo creado: {path}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def read_file(self, relative_path: str) -> Dict[str, str]:
        try:
            path = self._resolve(relative_path)
            text = path.read_text(encoding="utf-8")
            return {"status": "ok", "content": text}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def update_file(self, relative_path: str, content: str) -> Dict[str, str]:
        try:
            path = self._resolve(relative_path)
            if not path.exists():
                return {"status": "error", "message": "El archivo no existe"}
            path.write_text(content, encoding="utf-8")
            return {"status": "ok", "message": "Archivo actualizado"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def delete_file(self, relative_path: str) -> Dict[str, str]:
        try:
            path = self._resolve(relative_path)
            if path.exists():
                path.unlink()
            return {"status": "ok", "message": "Archivo eliminado"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def list_files(self, relative_dir: str = ".") -> List[str]:
        try:
            path = self._resolve(relative_dir)
            return [str(p.relative_to(self.base_path)) for p in path.rglob("*") if p.is_file()]
        except Exception as exc:
            log.error("Error listando archivos: %s", exc)
            return []
