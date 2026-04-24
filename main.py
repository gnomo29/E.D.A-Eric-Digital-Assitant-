"""Punto de entrada principal de E.D.A."""

from __future__ import annotations

import argparse

from eda.gui import EDAGUI
from eda.logger import get_logger, setup_logging
from eda.memory import MemoryManager
from eda.utils import ensure_project_dirs

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

    log.info("Iniciando GUI de E.D.A.")
    app = EDAGUI()
    app.run()


if __name__ == "__main__":
    main()
