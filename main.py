"""Punto de entrada principal de E.D.A."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from eda.utils import ensure_project_dirs, load_env_dotfile

load_env_dotfile()

from eda.logger import get_logger, setup_logging
from eda.memory import MemoryManager

log = get_logger("main")


def run_cli() -> None:
    """Modo simple por consola para diagnóstico rápido."""
    from eda.core import EDACore

    memory = MemoryManager()
    core = EDACore(memory_manager=memory)
    print("E.D.A. CLI iniciado. Escribe 'salir' para terminar.")
    while True:
        user = input("Tú: ").strip()
        if user.lower() in ["salir", "exit", "quit"]:
            break
        mem = memory.get_memory()
        history = mem.get("chat_history", []) or mem.get("history", [])
        answer = core.ask(user, history=history)
        memory.add_history(user, answer)
        print(f"E.D.A.: {answer}")


def main() -> None:
    """Arranque principal."""
    setup_logging()
    ensure_project_dirs()

    parser = argparse.ArgumentParser(description="E.D.A. Asistente Autónomo")
    parser.add_argument("--cli", action="store_true", help="Inicia en modo consola")
    args = parser.parse_args()

    if args.cli:
        run_cli()
        return

    log.info("Iniciando UI principal de E.D.A.")
    subprocess.run([sys.executable, "src/ui_main.py"], cwd=str(PROJECT_ROOT), check=False)


if __name__ == "__main__":
    main()
