"""Bootstrap de entorno: valida Python, crea venv e instala dependencias faltantes."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ_FILE = ROOT / "requirements.txt"
VENV_DIR = ROOT / ".venv"
MIN_PY = (3, 9)


def _run(cmd: list[str], env: dict[str, str] | None = None) -> int:
    return subprocess.run(cmd, cwd=str(ROOT), env=env, check=False).returncode


def _python_ok() -> bool:
    return sys.version_info >= MIN_PY


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _ensure_venv() -> None:
    if _venv_python().exists():
        return
    print("[setup] creando entorno virtual...")
    code = _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if code != 0:
        raise RuntimeError("No se pudo crear el entorno virtual.")


def _normalize_req(line: str) -> str:
    clean = line.strip()
    clean = re.split(r"[;#]", clean)[0].strip()
    clean = re.split(r"(?:==|>=|<=|~=|>|<)", clean)[0].strip()
    return clean


def _load_requirements() -> list[str]:
    if not REQ_FILE.exists():
        return []
    items: list[str] = []
    for line in REQ_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        pkg = _normalize_req(line)
        if pkg:
            items.append(pkg)
    return items


def _missing_packages(py: Path, requirements: list[str]) -> list[str]:
    missing: list[str] = []
    for pkg in requirements:
        code = _run([str(py), "-m", "pip", "show", pkg])
        if code != 0:
            missing.append(pkg)
    return missing


def main() -> int:
    if not _python_ok():
        print(f"[setup] Python {MIN_PY[0]}.{MIN_PY[1]}+ requerido.")
        return 2

    _ensure_venv()
    py = _venv_python()

    print("[setup] actualizando pip base...")
    _run([str(py), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"])

    requirements = _load_requirements()
    missing = _missing_packages(py, requirements)
    if missing:
        print(f"[setup] instalando dependencias faltantes ({len(missing)})...")
        code = _run([str(py), "-m", "pip", "install", "-r", str(REQ_FILE)])
        if code != 0:
            print("[setup] error instalando dependencias.")
            return code
    else:
        print("[setup] dependencias ya satisfechas.")

    print("[setup] entorno listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
