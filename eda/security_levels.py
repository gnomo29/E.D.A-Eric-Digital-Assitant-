"""Modelo de seguridad por niveles y evaluación de riesgo de comandos."""

from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass
class SecurityDecision:
    allowed: bool
    risk: str  # low | medium | high
    reason: str


class SecurityManager:
    """Evalúa riesgo de comandos y define si se permite ejecución directa."""

    HIGH_RISK_MARKERS = (
        "apaga",
        "reinicia",
        "borra",
        "elimina",
        "formatea",
        "kill",
        "taskkill",
        "shutdown",
        "registro",
    )
    MEDIUM_RISK_MARKERS = (
        "instala",
        "descarga",
        "abre cmd",
        "powershell",
        "autoevoluciona",
        "evoluciona",
    )

    def assess(self, text: str) -> SecurityDecision:
        normalized = (text or "").lower().strip()
        if any(marker in normalized for marker in self.HIGH_RISK_MARKERS):
            risk = "high"
        elif any(marker in normalized for marker in self.MEDIUM_RISK_MARKERS):
            risk = "medium"
        else:
            risk = "low"

        level = str(getattr(config, "SECURITY_LEVEL", "strict")).lower().strip()
        if level == "relaxed":
            return SecurityDecision(True, risk, "Nivel relaxed")
        if level == "balanced":
            if risk == "high":
                return SecurityDecision(False, risk, "Bloqueado hasta confirmación manual")
            return SecurityDecision(True, risk, "Nivel balanced")

        # strict (default)
        if risk == "high" and getattr(config, "SECURITY_BLOCK_HIGH_RISK_BY_DEFAULT", True):
            return SecurityDecision(False, risk, "Comando de alto riesgo requiere confirmación explícita")
        return SecurityDecision(True, risk, "Nivel strict")
