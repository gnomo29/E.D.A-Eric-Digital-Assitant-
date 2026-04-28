# Contributing Guide

Gracias por tu interés en contribuir a E.D.A.

## Flujo recomendado

1. Haz fork del repositorio.
2. Crea una rama por cambio (`feature/...`, `fix/...`, `docs/...`).
3. Mantén cambios pequeños y con alcance claro.
4. Ejecuta pruebas locales antes de abrir PR.

## Entorno local

```bash
python -m venv .venv
```

- Windows:
```bat
.venv\Scripts\activate
pip install -r requirements.txt
```

- Linux:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Validaciones mínimas

```bash
python -m unittest discover -s tests -p "test_*.py"
python health_check.py
```

## Estilo de cambios

- No subir secretos ni archivos runtime (`.env`, `data/`, logs, caches).
- Evitar romper compatibilidad de `main.py` y scripts de arranque.
- Si cambias comportamiento de usuario, actualiza `README.md`.

## Issues y PRs

Al reportar bugs incluye:
- Sistema operativo.
- Versión de Python.
- Pasos de reproducción.
- Log o traceback.

En PRs incluye:
- Resumen del problema.
- Qué se cambió.
- Cómo se probó.
