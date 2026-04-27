"""Gestión de modelos Ollama y métricas por tarea."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from . import config
from .telemetry import ResourceMonitor
from .utils import build_http_session


@dataclass
class TaskMetric:
    task: str
    latency_ms: float


class ModelManager:
    def __init__(self) -> None:
        self.http = build_http_session()
        self.monitor = ResourceMonitor()
        self.metrics: List[TaskMetric] = []

    def list_models(self) -> List[str]:
        try:
            response = self.http.get(config.OLLAMA_TAGS_URL, timeout=5)
            response.raise_for_status()
            data = response.json() if response.content else {}
            models = data.get("models") or []
            return [str(item.get("name", "")) for item in models if isinstance(item, dict)]
        except Exception:
            return []

    def suggest_model(self, current_model: str) -> str:
        if self.monitor.has_free_ram(1.0):
            return current_model
        models = self.list_models()
        quantized = [m for m in models if any(tag in m.lower() for tag in ("q4", "q5", "1b", "mini"))]
        if quantized:
            return quantized[0]
        return current_model

    def record_latency(self, task: str, latency_ms: float) -> None:
        self.metrics.append(TaskMetric(task=task, latency_ms=float(latency_ms)))
        self.metrics = self.metrics[-200:]

    def metrics_summary(self) -> Dict[str, float]:
        grouped: Dict[str, List[float]] = {}
        for item in self.metrics:
            grouped.setdefault(item.task, []).append(item.latency_ms)
        return {task: round(sum(values) / len(values), 2) for task, values in grouped.items() if values}

