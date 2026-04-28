# Triggers (frases-disparador)

## Qué es
Los triggers permiten ejecutar acciones cuando el usuario dice una frase específica.

## Dónde se guardan
- `data/memory/long_term.db` tabla `triggers`
- Campos: `phrase`, `match_type`, `fuzzy_threshold`, `action_type`, `action_payload`, `require_confirm`, `active`

## Acciones soportadas
- `play_spotify`
- `play_youtube`
- `open_app`
- `URL Viewer`
- `run_script` (solo si `TRIGGERS_ALLOW_RUN_SCRIPTS=1` y script en `scripts/approved/`)

## Seguridad
- Si `require_confirm=true`, pide confirmación antes de ejecutar.
- `run_script` está bloqueado por defecto.
- Se registra auditoría en `logs/operate_secure_audit.jsonl`.
- Límite de ejecución: `TRIGGERS_RATE_LIMIT_PER_MIN` (por defecto 3/min).

## Comandos de chat
- `listar mis disparadores`
- `crear disparador: cuando diga 'ironman' reproduce acdc`
