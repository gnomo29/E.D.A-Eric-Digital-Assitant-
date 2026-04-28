"""Build portable executable with PyInstaller."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "EDA.spec"
ENTRY = ROOT / "main.py"


def _venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def main() -> int:
    py = _venv_python()
    if not py.exists():
        print("[build] entorno no inicializado. Ejecuta primero: python install_deps.py")
        return 2

    subprocess.run([str(py), "-m", "pip", "install", "pyinstaller"], check=False)

    if BUILD.exists():
        shutil.rmtree(BUILD, ignore_errors=True)
    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)
    if SPEC.exists():
        SPEC.unlink(missing_ok=True)

    cmd = [
        str(py),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        "EDA",
        "--onedir",
        "--add-data",
        f"{ROOT / 'src'}{os.pathsep}src",
        "--add-data",
        f"{ROOT / 'docs'}{os.pathsep}docs",
        "--hidden-import",
        "tkinter",
        str(ENTRY),
    ]
    print("[build] ejecutando:", " ".join(cmd))
    code = subprocess.run(cmd, cwd=str(ROOT), check=False).returncode
    if code != 0:
        return code
    print(f"[build] listo: {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
