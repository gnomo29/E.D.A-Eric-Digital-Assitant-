#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[setup] Creando entorno virtual en .venv ..."
  python3 -m venv .venv
fi

source ".venv/bin/activate"

python -m pip --version >/dev/null 2>&1 || python -m ensurepip --upgrade
python -m pip install --upgrade pip >/dev/null

if [[ -f ".env" ]]; then
  echo "[setup] Cargando variables de .env ..."
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

if ! python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11434', timeout=2)"; then
  echo "[error] Ollama no detectado en http://127.0.0.1:11434"
  echo "[error] Inicia Ollama antes de abrir E.D.A."
  exit 2
else
  echo "[ok] Ollama detectado."
fi

if ! python -c "import json,urllib.request,sys; d=json.loads(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=3).read().decode()); names=[(m.get('name') or '') for m in d.get('models', []) if isinstance(m, dict)]; sys.exit(0 if any(n=='llama3.2:1b' or n.startswith('llama3.2:1b:') for n in names) else 1)"; then
  echo "[error] Falta el modelo llama3.2:1b en Ollama."
  echo "[error] Ejecuta: ollama pull llama3.2:1b"
  exit 3
else
  echo "[ok] Modelo llama3.2:1b disponible."
fi

python run_assistant.py --auto-install "$@"
echo "[info] Log de instalacion: logs/installer.log"

