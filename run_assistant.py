"""Lanzador unificado de E.D.A. (UI Obsidian por defecto)."""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import tempfile
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from eda.utils import load_env_dotfile
except Exception:  # pragma: no cover
    load_env_dotfile = None  # type: ignore[assignment]
REQ_FILE = ROOT / "requirements.txt"
VOICE_REQ_FILE = ROOT / "requirements-voice.txt"
LOG_DIR = ROOT / "data" / "logs"
INSTALLER_LOG = LOG_DIR / "installer.log"
OPTIONAL_PACKAGES = {"pyaudio"}


def _setup_installer_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("eda_installer")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(INSTALLER_LOG, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    return logger


LOG = _setup_installer_logger()


def _requirements_for_platform() -> list[str]:
    if not REQ_FILE.exists():
        return []
    out: list[str] = []
    is_windows = os.name == "nt"
    for raw in REQ_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ";" in line:
            pkg, marker = line.split(";", 1)
            marker = marker.strip().lower()
            if "platform_system" in marker and "windows" in marker and not is_windows:
                continue
            line = pkg.strip()
        if line:
            out.append(line)
    return out


def _normalize_pkg(requirement: str) -> str:
    base = re.split(r"(==|>=|<=|~=|>|<)", requirement, maxsplit=1)[0].strip()
    return base


def _missing_requirements() -> list[str]:
    missing: list[str] = []
    for req in _requirements_for_platform():
        pkg = _normalize_pkg(req)
        if not pkg:
            continue
        check = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode != 0:
            missing.append(req)
    return missing


def _is_windows_py312_or_newer() -> bool:
    return os.name == "nt" and sys.version_info >= (3, 12)


def _run_install_cmd(args: list[str], label: str) -> tuple[bool, str]:
    LOG.info("[INSTALL] %s", label)
    proc = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        LOG.info("[INSTALL] %s: OK", label)
        return True, ""
    tail = (proc.stderr or proc.stdout or "").strip()[-1200:]
    LOG.error("[INSTALL] %s: ERROR rc=%s | %s", label, proc.returncode, tail)
    return False, tail


def _is_pkg_installed(pkg: str) -> bool:
    check = subprocess.run(
        [sys.executable, "-m", "pip", "show", pkg],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return check.returncode == 0


def _find_local_pyaudio_wheel() -> Path | None:
    py_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    wheels_dir = ROOT / "data" / "resources" / "wheels"
    if not wheels_dir.exists():
        return None
    for wheel in sorted(wheels_dir.glob("*.whl")):
        name = wheel.name.lower()
        if "pyaudio" in name and py_tag in name and "win_amd64" in name:
            return wheel
    return None


def _attempt_install_pyaudio() -> tuple[bool, list[str]]:
    attempts: list[str] = []

    ok, _ = _run_install_cmd(
        [sys.executable, "-m", "pip", "install", "pipwin"],
        "Attempting pip install pipwin",
    )
    attempts.append("pip install pipwin")
    if ok:
        ok_pw, _ = _run_install_cmd(
            [sys.executable, "-m", "pipwin", "install", "pyaudio"],
            "Attempting pipwin install pyaudio",
        )
        attempts.append("pipwin install pyaudio")
        if ok_pw and _is_pkg_installed("pyaudio"):
            return True, attempts

    ok_bin, _ = _run_install_cmd(
        [sys.executable, "-m", "pip", "install", "--only-binary=:all:", "pyaudio"],
        "Attempting pip install --only-binary=:all: pyaudio",
    )
    attempts.append("pip install --only-binary=:all: pyaudio")
    if ok_bin and _is_pkg_installed("pyaudio"):
        return True, attempts

    local_wheel = _find_local_pyaudio_wheel()
    if local_wheel is not None:
        ok_whl, _ = _run_install_cmd(
            [sys.executable, "-m", "pip", "install", str(local_wheel)],
            f"Attempting local wheel install {local_wheel.name}",
        )
        attempts.append(f"pip install {local_wheel.name}")
        if ok_whl and _is_pkg_installed("pyaudio"):
            return True, attempts
    else:
        attempts.append("local wheel not found")

    # Último intento: compilación estándar (no bloqueante).
    ok_std, _ = _run_install_cmd(
        [sys.executable, "-m", "pip", "install", "pyaudio"],
        "Attempting standard pip install pyaudio (build)",
    )
    attempts.append("pip install pyaudio")
    if ok_std and _is_pkg_installed("pyaudio"):
        return True, attempts
    return False, attempts


def _install_requirements() -> bool:
    print("[setup] Instalando dependencias desde requirements.txt ...")
    reqs = _requirements_for_platform()
    required = [r for r in reqs if _normalize_pkg(r).lower() not in OPTIONAL_PACKAGES]
    optional = [r for r in reqs if _normalize_pkg(r).lower() in OPTIONAL_PACKAGES]

    # Instalar primero dependencias obligatorias para que un opcional no rompa todo.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
        for item in required:
            tmp.write(item + "\n")
        tmp_required = tmp.name
    try:
        proc_required = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", tmp_required],
            cwd=str(ROOT),
            check=False,
        )
        if proc_required.returncode != 0:
            return False
    finally:
        try:
            Path(tmp_required).unlink(missing_ok=True)
        except Exception:
            pass

    # Opcionales de voz: intentos robustos en Windows, no bloqueantes.
    if os.name == "nt":
        ok_audio, attempts = _attempt_install_pyaudio()
        LOG.info("[INSTALL] Fallbacks tried for pyaudio: %s", attempts)
        if not ok_audio:
            print("[aviso] PyAudio no se pudo instalar; micrófono/STT puede estar limitado.")
            print("[aviso] Ver README: pipwin / Build Tools / conda-forge.")
    elif optional:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp2:
            for item in optional:
                tmp2.write(item + "\n")
            tmp_optional = tmp2.name
        try:
            proc_optional = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", tmp_optional],
                cwd=str(ROOT),
                check=False,
            )
            if proc_optional.returncode != 0:
                print("[aviso] Falló instalación de paquetes opcionales; continuaré igualmente.")
        finally:
            try:
                Path(tmp_optional).unlink(missing_ok=True)
            except Exception:
                pass

    return True


def _check_ollama() -> bool:
    url = "http://127.0.0.1:11434"
    try:
        with urlopen(url, timeout=1.5):
            return True
    except URLError:
        return False
    except Exception:
        return False


def _has_ollama_model(model: str = "llama3.2:1b") -> bool:
    tags_url = "http://127.0.0.1:11434/api/tags"
    try:
        with urlopen(tags_url, timeout=2.5) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            payload = json.loads(body or "{}")
    except Exception:
        return False
    models = payload.get("models") or []
    names: list[str] = []
    for m in models:
        if isinstance(m, dict):
            nm = str(m.get("name") or "").strip()
            if nm:
                names.append(nm)
    return any(n == model or n.startswith(model + ":") for n in names)


def _launch(cli_mode: bool) -> int:
    if cli_mode:
        cmd = [sys.executable, "main.py", "--cli"]
    else:
        # UI Deep Obsidian (flujo principal).
        cmd = [sys.executable, "src/ui_main.py"]
    return subprocess.run(cmd, cwd=str(ROOT), check=False).returncode


def main() -> int:
    if load_env_dotfile is not None:
        try:
            load_env_dotfile()
        except Exception:
            pass
    print(f"[setup] Plataforma: {'Windows' if os.name == 'nt' else os.name} | Python: {sys.version.split()[0]}")
    LOG.info("[INSTALL] Startup platform=%s python=%s", os.name, sys.version.split()[0])
    if _is_windows_py312_or_newer():
        LOG.info("[INSTALL] Windows + Python 3.12+ detected; PyAudio wheel/build issues likely.")

    parser = argparse.ArgumentParser(description="Lanzador unificado de E.D.A. (Obsidian)")
    parser.add_argument("--cli", action="store_true", help="Inicia en modo terminal")
    parser.add_argument("--auto-install", action="store_true", help="Instalar dependencias faltantes sin preguntar")
    parser.add_argument(
        "--skip-ollama-check",
        action="store_true",
        help="Permite iniciar aunque Ollama/modelo no estén disponibles.",
    )
    args = parser.parse_args()

    if not REQ_FILE.exists():
        print("[error] No se encontró requirements.txt en la raíz del proyecto.")
        return 2

    missing = _missing_requirements()
    if missing:
        print("[setup] Faltan dependencias:")
        for item in missing[:12]:
            print(f"  - {item}")
        if len(missing) > 12:
            print(f"  ... y {len(missing) - 12} más")
        should_install = args.auto_install
        if not should_install:
            answer = input("¿Deseas instalarlas ahora? [Y/n]: ").strip().lower()
            should_install = answer in {"", "y", "yes", "s", "si", "sí"}
        if should_install:
            if not _install_requirements():
                print("[error] No se pudieron instalar dependencias.")
                return 3
            missing_after = _missing_requirements()
            blocking_missing = [m for m in missing_after if _normalize_pkg(m).lower() not in OPTIONAL_PACKAGES]
            optional_missing = [m for m in missing_after if _normalize_pkg(m).lower() in OPTIONAL_PACKAGES]
            if optional_missing:
                print("[aviso] Dependencias opcionales no instaladas:")
                for item in optional_missing:
                    print(f"  - {item}")
                print("[aviso] Voz: MODO LIMITADO (micrófono/STT puede estar desactivado).")
                print("[aviso] Instrucciones rápidas: pip install pipwin && pipwin install pyaudio")
            if blocking_missing:
                print("[error] Aún faltan dependencias obligatorias:")
                for item in blocking_missing[:12]:
                    print(f"  - {item}")
                return 3
        else:
            print("[error] No puedo iniciar sin dependencias completas.")
            return 4

    if _check_ollama():
        print("[ok] Ollama detectado (http://127.0.0.1:11434).")
        if _has_ollama_model("llama3.2:1b"):
            print("[ok] Modelo llama3.2:1b disponible.")
        else:
            print("[aviso] Ollama está arriba, pero falta el modelo llama3.2:1b.")
            print("        Ejecuta: ollama pull llama3.2:1b")
            if args.skip_ollama_check:
                print("[run] Continuando por --skip-ollama-check.")
            else:
                print("[run] Continuando en modo degradado sin modelo local.")
    else:
        print("[aviso] Ollama no está corriendo en http://127.0.0.1:11434.")
        print("        Inicia Ollama para máxima calidad, continúo en modo degradado.")
        if args.skip_ollama_check:
            print("[run] Continuando por --skip-ollama-check.")

    run_mode = "cli" if args.cli else "obsidian-ui"
    print(f"[run] Iniciando E.D.A. en modo: {run_mode}")
    if os.name == "nt" and not _is_pkg_installed("pyaudio"):
        print("[resumen] PyAudio: FALLO / no instalado")
        print("[resumen] Voz: MODO LIMITADO")
        print("[resumen] Solución: pip install pipwin && pipwin install pyaudio")
        print("[resumen] Alternativas: Visual Studio Build Tools o conda-forge.")
    return _launch(cli_mode=args.cli)


if __name__ == "__main__":
    raise SystemExit(main())

