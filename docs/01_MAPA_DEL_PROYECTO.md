# 01 - Mapa del Proyecto (version simple)

## Estructura mental en 5 capas

1. **Entrada** (UI/voz): recibe lo que dice/escribe el usuario.
2. **Orquestacion**: decide que modulo debe resolver cada orden.
3. **Acciones/Conectores**: ejecuta cosas reales (apps, web, spotify, youtube).
4. **Memoria y seguridad**: persistencia, permisos, ACL, OTP, auditoria.
5. **Herramientas/tests**: validacion automatica del comportamiento.

## Donde esta cada capa

- `main.py` / `start_eda.py`: punto de entrada.
- `src/ui_main.py`: interfaz principal.
- `src/eda/orchestrator.py`: cerebro de enrutamiento.
- `src/eda/actions.py`: acciones de sistema.
- `src/eda/connectors/`: conectores externos (spotify/youtube/mobile).
- `src/eda/memory.py`: memoria persistente.
- `src/eda/security/`: seguridad remota (ACL/OTP).
- `src/eda/background_tasks.py`: worker de recordatorios.
- `tests/`: suite de pruebas.
- `tools/`: scripts de chequeo y operacion.

## Si quieres editar algo, toca solo esto

- UI: `src/ui_main.py`
- Enrutado: `src/eda/orchestrator.py`
- Acciones del sistema: `src/eda/actions.py`
- Spotify/YouTube: `src/eda/connectors/spotify.py` y `src/eda/connectors/youtube.py`
- Memoria: `src/eda/memory.py`

## Que NO tocar al empezar

- `venv312/`, `.venv/`: librerias instaladas.
- `data/*.db`: datos runtime del usuario.
- `docs/legacy/` (salvo lectura).

