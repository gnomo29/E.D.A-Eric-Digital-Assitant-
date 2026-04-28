# Legacy Components

Este directorio se utilizó como zona de transición para compatibilidad histórica.
Los componentes legacy fueron depurados en la limpieza final por solicitud del usuario.

## Movimientos realizados en cleanup

- **Recordatorios canónicos**: `src/eda/background_tasks.py` (worker único).
- **Compatibilidad de API**: `src/eda/scheduler.py` ahora es un facade ligero sobre el worker canónico.
- **Lanzadores antiguos y scheduler legacy**: eliminados en cleanup final.

## Política de legacy

Para nuevos cambios, usar solo la estructura canónica (`src/eda`, `scripts`, `tools`, `docs`).
