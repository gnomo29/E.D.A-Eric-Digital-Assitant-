"""Wrapper de compatibilidad para bootstrap de dependencias.

Implementacion real: scripts/setup/install_deps.py
"""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "scripts" / "setup" / "install_deps.py"
    runpy.run_path(str(target), run_name="__main__")
