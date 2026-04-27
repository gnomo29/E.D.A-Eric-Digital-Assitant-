"""Telemetría interna: RAM, latencia Ollama y fallbacks."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict

from .logger import get_logger

log = get_logger("telemetry")

try:
    import psutil
except Exception:
    psutil = None


@dataclass
class TelemetrySnapshot:
    ram_used_gb: float
    ram_free_gb: float
    ram_percent: float
    ollama_latency_ms: float
    fallback_failures: int


class ResourceMonitor:
    def __init__(self, ram_guard_gb: float = 7.0) -> None:
        self.ram_guard_gb = ram_guard_gb
        self.fallback_failures = 0

    def record_fallback_failure(self) -> None:
        self.fallback_failures += 1

    def snapshot(self, ollama_latency_ms: float = 0.0) -> TelemetrySnapshot:
        if psutil is None:
            return TelemetrySnapshot(0.0, 0.0, 0.0, ollama_latency_ms, self.fallback_failures)
        vm = psutil.virtual_memory()
        return TelemetrySnapshot(
            ram_used_gb=round((vm.total - vm.available) / (1024**3), 2),
            ram_free_gb=round(vm.available / (1024**3), 2),
            ram_percent=float(vm.percent),
            ollama_latency_ms=float(ollama_latency_ms),
            fallback_failures=self.fallback_failures,
        )

    def enforce_guard(self) -> Dict[str, str]:
        snap = self.snapshot()
        if snap.ram_used_gb < self.ram_guard_gb:
            return {"status": "ok", "message": "RAM dentro de umbral."}
        # Evita procesos agresivos para no romper UX: registra recomendación y permite al caller decidir.
        log.warning("RAM alta detectada: %.2f GB (umbral %.2f).", snap.ram_used_gb, self.ram_guard_gb)
        return {
            "status": "warning",
            "message": (
                f"RAM alta ({snap.ram_used_gb} GB). Se recomienda cerrar procesos secundarios "
                "y degradar features pesadas."
            ),
        }

    def has_free_ram(self, min_free_gb: float = 1.0) -> bool:
        snap = self.snapshot()
        return snap.ram_free_gb >= max(0.1, float(min_free_gb))

    @staticmethod
    def timed_call(fn, *args, **kwargs):
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000.0
        return result, elapsed

