# Operational Runbook (rápido)

## 1) Check de salud del ecosistema

```powershell
$env:PYTHONPATH="src"
python tools/system_check.py
```

Resultado esperado: `[OK]` en Groq remoto, Spotify auth, Ollama 1b y UI init.

## 2) Ejecutar test suite relevante (unittest)

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_orchestrator_routing_matrix tests.test_spotify_integration tests.test_spotify_web -v
```

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_intent_routing -v
python tools/intent_test_run.py
```

`tools/intent_test_run.py` genera `logs/intent_test_report.json` con precisión/recall, matriz de confusión, top-3 candidatos y pico de RSS.

## 3) Pruebas manuales de ruteo en UI

1. Abrir UI (`INICIAR_ASISTENTE.bat` o `python src/ui_main.py`).
2. Caso conversación:
   - Entrada: `que es eso?`
   - Esperado: respuesta explicativa de LLM (no error de acción directa).
3. Caso música clara:
   - Entrada: `reproduce AD/DC`
   - Esperado: ruta Spotify (`Buscando ... en Spotify...` / reproducción).
4. Caso ambiguo:
   - Entrada: `reproduce aiaia`
   - Esperado: intento Spotify, luego intento app, luego aclaración:
     `No encontré esa app o canción, ¿te refieres a otra cosa?`

## 4) Variables configurables recomendadas (.env)

- `EDA_SPOTIFY_CONF_AUTO` (default `0.82`)
- `EDA_COMMAND_CONFIDENCE_THRESHOLD` (default `0.78`)
- `EDA_RELEASE_OLLAMA_MEMORY` (`1`/`0`)

## 5) Logs de ruteo a inspeccionar

- `logs/eda.log` (o logger configurado): líneas `route chosen: ... (score=...)`
- `logs/operate_secure_audit.jsonl`: fallos operativos como `audio_device_failure`
