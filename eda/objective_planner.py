"""Planificador autónomo por objetivos (descomposición y seguimiento)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict


@dataclass
class PlanStep:
    text: str
    done: bool = False


@dataclass
class ObjectivePlan:
    goal: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    steps: List[PlanStep] = field(default_factory=list)

    def next_pending(self) -> PlanStep | None:
        for step in self.steps:
            if not step.done:
                return step
        return None

    def mark_next_done(self) -> bool:
        step = self.next_pending()
        if not step:
            return False
        step.done = True
        return True

    def is_completed(self) -> bool:
        return all(step.done for step in self.steps)

    def to_dict(self) -> Dict[str, object]:
        return {
            "goal": self.goal,
            "created_at": self.created_at,
            "steps": [{"text": s.text, "done": s.done} for s in self.steps],
        }


class ObjectivePlanner:
    """Genera planes simples pero accionables para objetivos del usuario."""

    def build_plan(self, goal: str) -> ObjectivePlan:
        g = (goal or "").strip()
        normalized = g.lower()
        steps: List[str]

        if "stream" in normalized or "obs" in normalized:
            steps = [
                "Abrir OBS y verificar perfil/escena",
                "Configurar fuente principal y audio",
                "Probar grabación/preview",
                "Iniciar transmisión o grabación",
            ]
        elif "musica" in normalized or "música" in normalized or "spotify" in normalized:
            steps = [
                "Abrir Spotify",
                "Buscar artista o playlist solicitada",
                "Iniciar reproducción",
                "Ajustar volumen y confirmar salida de audio",
            ]
        else:
            steps = [
                f"Analizar objetivo: {g}",
                "Seleccionar herramientas y aplicaciones necesarias",
                "Ejecutar acciones en orden",
                "Verificar resultado y reportar estado",
            ]

        return ObjectivePlan(goal=g, steps=[PlanStep(text=s) for s in steps])
