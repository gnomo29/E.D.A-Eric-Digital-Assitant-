# Cleanup Candidates

Estos elementos son candidatos seguros para limpieza manual.

## Runtime files (seguros de borrar si no se necesitan)
- `data\logs\eda.log`
- `data\logs\eda_audit.jsonl`
- `__pycache__\actions.cpython-312.pyc`
- `__pycache__\actions.cpython-314.pyc`
- `__pycache__\bluetooth_manager.cpython-312.pyc`
- `__pycache__\bluetooth_manager.cpython-314.pyc`
- `__pycache__\config.cpython-312.pyc`
- `__pycache__\config.cpython-314.pyc`
- `__pycache__\core.cpython-312.pyc`
- `__pycache__\core.cpython-314.pyc`
- `__pycache__\evolution.cpython-312.pyc`
- `__pycache__\gui.cpython-312.pyc`
- `__pycache__\gui.cpython-314.pyc`
- `__pycache__\health_check.cpython-314.pyc`
- `__pycache__\integration_hub.cpython-312.pyc`
- `__pycache__\logger.cpython-312.pyc`
- `__pycache__\logger.cpython-314.pyc`
- `__pycache__\main.cpython-314.pyc`
- `__pycache__\memory.cpython-312.pyc`
- `__pycache__\memory.cpython-314.pyc`
- `__pycache__\mouse_keyboard.cpython-312.pyc`
- `__pycache__\multimodal.cpython-312.pyc`
- `__pycache__\nlp_utils.cpython-312.pyc`
- `__pycache__\nlp_utils.cpython-314.pyc`
- `__pycache__\objective_planner.cpython-312.pyc`
- `__pycache__\objective_planner.cpython-314.pyc`
- `__pycache__\obs_controller.cpython-312.pyc`
- `__pycache__\optimizer.cpython-312.pyc`
- `__pycache__\scheduler.cpython-312.pyc`
- `__pycache__\scheduler.cpython-314.pyc`
- `__pycache__\security_levels.cpython-312.pyc`
- `__pycache__\security_levels.cpython-314.pyc`
- `__pycache__\skills_auto.cpython-312.pyc`
- `__pycache__\system_info.cpython-312.pyc`
- `__pycache__\utils.cpython-312.pyc`
- `__pycache__\utils.cpython-314.pyc`
- `__pycache__\voice.cpython-312.pyc`
- `__pycache__\web_search.cpython-312.pyc`
- `__pycache__\web_search.cpython-314.pyc`
- `__pycache__\web_solver.cpython-312.pyc`
- `__pycache__\web_solver.cpython-314.pyc`

## Empty directories (revisar antes de borrar)
- `data\captures`
- `data\exports`
- `data\solutions`
- `data\suggestions`
- `temp\cache`
- `temp\runtime`

## Reglas rápidas
- `data/logs`, `temp/`, `__pycache__/` son seguros de limpiar.
- No borrar `src/`, `docs/`, `tests/`, `scripts/` ni `data/memory/*.example.json`.

## Auditoría automática (ops/cleanup-refactor)

- Reporte JSON: `logs/cleanup_audit_report.json`
- Mapa de imports canónicos: `logs/import_map.csv`
- Canonical modules:
  - Spotify: `src/eda/connectors/spotify.py`
  - YouTube: `src/eda/connectors/youtube.py`
  - Orquestador: `src/eda/orchestrator.py`
  - UI principal: `src/ui_main.py`

### Archivos movidos a legacy en esta pasada
- `old_launchers/` -> `legacy/old_launchers/` (lanzadores antiguos, no requeridos por flujo principal).

### Safe-delete
- En esta pasada no se borraron archivos de forma permanente.
- Criterio aplicado: mover primero a `legacy/` y validar tests/checks antes de cualquier borrado definitivo.
