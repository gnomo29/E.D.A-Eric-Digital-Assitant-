# Guia Novato: que tocar en cada archivo (estructura actual)

Esta guia explica el proyecto con la estructura real actual: `src/eda/`.

## Regla de oro

- Cambia una sola cosa por vez.
- Prueba despues de cada cambio.
- No edites librerias instaladas (`.venv/`, `venv312/`).

## Flujo principal de E.D.A.

1. Usuario escribe/habla en la UI.
2. `src/ui_main.py` envia el texto al orquestador.
3. `src/eda/orchestrator.py` decide la ruta:
   - acciones de sistema,
   - conectores (Spotify/YouTube),
   - consulta IA (`core.py`),
   - recordatorios, seguridad remota, etc.
4. `src/eda/memory.py` persiste historial/memoria.
5. UI muestra y locuta respuesta.

## Modulos mas importantes (donde tocar cada cosa)

### Entrada y UI

- `src/ui_main.py`: interfaz principal y eventos de usuario.
- `src/eda/ui_services.py`: utilidades compartidas de UI/voz.
- `src/eda/stt.py`, `src/eda/tts.py`: voz.

### Cerebro de enrutamiento

- `src/eda/orchestrator.py`: fuente de verdad del routing.
- `src/eda/nlp_utils.py`: parseo de intenciones.
- `src/eda/action_agent.py`: acciones aprendidas/dinamicas.

### Ejecucion de acciones

- `src/eda/actions.py`: abrir/cerrar apps, volumen, brillo, ventanas.
- `src/eda/connectors/spotify.py`: reproduccion Spotify.
- `src/eda/connectors/youtube.py`: busqueda/validacion YouTube.
- `src/eda/connectors/mobile.py`: Telegram/control movil.

### Persistencia y seguridad

- `src/eda/memory.py`: memoria persistente y KB local.
- `src/eda/background_tasks.py`: worker canónico de recordatorios.
- `src/eda/security/remote_acl.py`: ACL de comandos remotos.
- `src/eda/security/otp_manager.py`: OTP para acciones criticas.

### Core IA y utilidades

- `src/eda/core.py`: respuestas LLM/fallback.
- `src/eda/web_solver.py`, `src/eda/web_search.py`: investigacion web.
- `src/eda/config.py`: configuracion central.
- `src/eda/logger.py`: logging.

## Que NO tocar al principio

- `docs/legacy/`: historial/compatibilidad.
- `data/`: datos del runtime del usuario.
- scripts de seguridad avanzados si aun no dominas el flujo.

## Primer cambio recomendado (seguro)

1. Agrega un alias de app en `src/eda/actions.py`.
2. Prueba el comando desde UI.
3. Ejecuta:

```bash
python -m unittest discover -v
python tools/intent_test_run.py --ci
```

Si ambos pasan, tu cambio fue seguro.
