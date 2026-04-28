"""Chequeo de salud del entorno (ejecutar desde la raíz del proyecto)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from eda.utils import load_env_dotfile

load_env_dotfile()

from eda.health_check import main

if __name__ == "__main__":
    main()
