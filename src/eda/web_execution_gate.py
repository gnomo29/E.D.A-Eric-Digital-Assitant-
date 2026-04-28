"""Cierre temporal tras síntesis web remota: bloquea ejecución local automática de comandos."""

from __future__ import annotations

import time

_DEFAULT_TTL_SEC = 600.0
_ARM_UNTIL: float = 0.0

LIBERATE_PHRASES = frozenset(
    {
        "liberar acciones locales",
        "desbloquear acciones locales",
        "fin bloqueo acciones",
    }
)


def arm_after_external_research(seconds: float | None = None) -> None:
    """Activa el candado tras una respuesta basada en investigación externa filtrada por LLM remoto."""
    global _ARM_UNTIL
    ttl = float(seconds if seconds is not None else _DEFAULT_TTL_SEC)
    _ARM_UNTIL = time.monotonic() + max(60.0, ttl)


def disarm() -> None:
    global _ARM_UNTIL
    _ARM_UNTIL = 0.0


def is_armed() -> bool:
    global _ARM_UNTIL
    now = time.monotonic()
    if _ARM_UNTIL <= 0:
        return False
    if now >= _ARM_UNTIL:
        _ARM_UNTIL = 0.0
        return False
    return True


def text_disarms_gate(text: str) -> bool:
    return (text or "").strip().lower() in LIBERATE_PHRASES
