"""Autoevolución controlada de módulos Python."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Dict, List

import config
from logger import get_logger
from utils import now_str, user_desktop_dir

log = get_logger("evolution")


class EvolutionEngine:
    """Aplica mejoras de código con backup previo y validación sintáctica."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def _backup_roots(self) -> List[Path]:
        """Define todos los destinos de backup disponibles."""
        ts = now_str()
        roots = [config.BACKUPS_DIR / ts]

        win_target = Path(config.WINDOWS_BACKUP_TARGET) / ts
        roots.append(win_target)

        desktop_target = user_desktop_dir() / "EDA_Backups" / ts
        roots.append(desktop_target)

        unique: List[Path] = []
        seen = set()
        for path in roots:
            key = str(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique

    def _backup_file(self, file_path: Path) -> Dict[str, str | List[str]]:
        """Crea backups múltiples antes de modificar un archivo."""
        rel = file_path.relative_to(self.project_root)
        created: List[str] = []
        failed: List[str] = []

        for root in self._backup_roots():
            try:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, target)
                created.append(str(target))
            except Exception as exc:
                failed.append(f"{root}: {exc}")

        log.info("Backup para %s | ok=%d | fail=%d", rel, len(created), len(failed))
        return {
            "status": "ok" if created else "error",
            "created": created,
            "failed": failed,
        }

    def _validate_python(self, content: str) -> bool:
        try:
            ast.parse(content)
            return True
        except SyntaxError as exc:
            log.error("Validación AST falló: %s", exc)
            return False

    def evolve_file(self, relative_file: str, new_content: str) -> Dict[str, str | List[str]]:
        """Aplica evolución a un archivo con backup y validación."""
        target = (self.project_root / relative_file).resolve()
        if not target.exists() or not target.is_file():
            return {"status": "error", "message": "Archivo no encontrado"}

        if self.project_root not in target.parents and target != self.project_root:
            return {"status": "error", "message": "Ruta fuera del proyecto"}

        if target.suffix == ".py" and not self._validate_python(new_content):
            return {"status": "error", "message": "Nuevo contenido inválido según ast.parse"}

        backup_info = self._backup_file(target)
        if backup_info.get("status") != "ok":
            return {
                "status": "error",
                "message": "No fue posible crear backup previo, evolución cancelada",
                "failed": backup_info.get("failed", []),
            }

        try:
            target.write_text(new_content, encoding="utf-8")
            log.info("Evolución aplicada en %s", relative_file)
            return {
                "status": "ok",
                "message": "Evolución aplicada correctamente",
                "backups": backup_info.get("created", []),
                "backup_failures": backup_info.get("failed", []),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def evolve_module(self, relative_file: str, function_code: str) -> Dict[str, str | List[str]]:
        """Agrega una nueva función al módulo indicado con validación y backup."""
        target = (self.project_root / relative_file).resolve()
        if self.project_root not in target.parents and target != self.project_root:
            return {"status": "error", "message": "Ruta fuera del proyecto"}

        if not target.exists():
            if target.suffix != ".py":
                return {"status": "error", "message": f"Módulo no encontrado: {relative_file}"}
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('"""Módulo de habilidades auto-aprendidas de E.D.A."""\n\n', encoding="utf-8")
                log.info("[EVOLUTION] Creado nuevo módulo: %s", relative_file)
            except Exception as exc:
                return {"status": "error", "message": f"No pude crear módulo nuevo: {exc}"}

        try:
            original = target.read_text(encoding="utf-8")
            appended = original.rstrip() + "\n\n\n" + function_code.strip() + "\n"

            if target.suffix == ".py" and not self._validate_python(appended):
                return {"status": "error", "message": "El código generado no pasa validación AST."}

            result = self.evolve_file(relative_file, appended)
            if result.get("status") != "ok":
                return result

            # Verificación post-escritura + auto-revert de respaldo reciente si algo quedó corrupto.
            written = target.read_text(encoding="utf-8")
            if target.suffix == ".py" and not self._validate_python(written):
                backups = result.get("backups", []) if isinstance(result, dict) else []
                if isinstance(backups, list) and backups:
                    last_backup = Path(backups[0])
                    if last_backup.exists():
                        shutil.copy2(last_backup, target)
                return {"status": "error", "message": "Se detectó error sintáctico tras escribir. Se revirtió automáticamente."}

            log.info("[EVOLUTION] Módulo evolucionado: %s", relative_file)
            return result
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def autonomous_evolve_project(self) -> Dict[str, str | int]:
        """Autoevolución autónoma segura: estandariza finales de línea y valida sintaxis."""
        changed = 0
        checked = 0
        for file_path in self.project_root.glob("*.py"):
            checked += 1
            try:
                original = file_path.read_text(encoding="utf-8")
                updated = original.rstrip() + "\n"
                if updated == original:
                    continue
                if not self._validate_python(updated):
                    continue
                rel = str(file_path.relative_to(self.project_root))
                result = self.evolve_file(rel, updated)
                if result.get("status") == "ok":
                    changed += 1
            except Exception as exc:
                log.warning("No se pudo autoevolucionar %s: %s", file_path, exc)

        return {
            "status": "ok",
            "message": "Autoevolución autónoma finalizada",
            "checked": checked,
            "changed": changed,
        }

    def propose_evolution(self, relative_file: str, suggestion: str) -> Dict[str, str]:
        """Guarda sugerencias de evolución para revisión."""
        target = config.SUGGESTIONS_DIR / f"{now_str()}_{Path(relative_file).name}.txt"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(suggestion, encoding="utf-8")
            return {"status": "ok", "message": f"Sugerencia guardada en {target}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
