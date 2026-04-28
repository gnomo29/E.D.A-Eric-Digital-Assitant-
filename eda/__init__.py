"""Compatibilidad: expone `src/eda` como paquete `eda`."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC_EDA = _ROOT / "src" / "eda"

__path__ = [str(_SRC_EDA)]
