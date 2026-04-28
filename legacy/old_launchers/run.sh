#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 install_deps.py

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  echo "[run] No se encontro Python del entorno virtual."
  exit 1
fi

"$ROOT_DIR/.venv/bin/python" main.py "$@"

