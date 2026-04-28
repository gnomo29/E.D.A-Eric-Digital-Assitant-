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
- Se registra auditoría en `data/logs/operate_secure_audit.jsonl`.

## Comandos de chat
- `listar mis disparadores`
- `crear disparador: cuando diga 'ironman' reproduce acdc`

## Nota YouTube en triggers
- Cuando un trigger usa `play_youtube`, el asistente primero busca y muestra candidatos (top resultados) antes de abrir.
- Solo abre automáticamente si `YOUTUBE_AUTO_OPEN=true` y la confianza supera `YT_AUTO_OPEN_CONF`.
- Toda búsqueda/selección se audita en `data/logs/search_history.jsonl`.
