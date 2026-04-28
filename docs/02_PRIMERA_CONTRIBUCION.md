# 02 - Primera Contribucion (segura)

Objetivo: hacer un cambio pequeno sin romper nada.

## Paso 1: valida entorno

Ejecuta:

```bash
python tools/system_check.py
```

## Paso 2: elige un cambio simple

Ejemplos:

- mejorar un mensaje de texto en `src/ui_main.py`,
- ajustar una regex de intencion en `src/eda/nlp_utils.py`,
- agregar un alias de app en `src/eda/actions.py`.

## Paso 3: prueba local minima

```bash
python -m unittest discover -v
python tools/intent_test_run.py --ci
```

## Paso 4: revisa resultado esperado

- unittest sin errores,
- precision de intents >= 0.9,
- `tools/system_check.py` en OK.

## Paso 5: documenta tu cambio

- Si tocaste comportamiento de usuario: actualiza `README.md`.
- Si tocaste estructura/codigo: actualiza `docs/GUIA_NOVATO_CODIGO.md`.

