# Legacy Components

Estos componentes se conservan solo por compatibilidad histórica y pruebas:

- `main.py` (entrada CLI/GUI legacy)
- `src/eda/gui.py` (UI anterior)
- `legacy/old_launchers/` (lanzadores históricos de Windows/Linux movidos en cleanup seguro)

Flujo recomendado de producción:

- `INICIAR_ASISTENTE.bat` / `iniciar.sh`
- `run_assistant.py` (arranca `src/ui_main.py` por defecto)

Si no necesitas retrocompatibilidad, puedes retirar los módulos legacy en una migración posterior.

## Nota de cleanup

Durante el refactor `ops/cleanup-refactor`, los elementos obsoletos se mueven primero aquí en lugar de borrarse.
Esto permite rollback rápido y auditoría de cambios.
