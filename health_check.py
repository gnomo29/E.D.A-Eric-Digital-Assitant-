"""Chequeo de salud del entorno (ejecutar desde la raíz del proyecto)."""

from eda.utils import load_env_dotfile

load_env_dotfile()

from eda.health_check import main

if __name__ == "__main__":
    main()
