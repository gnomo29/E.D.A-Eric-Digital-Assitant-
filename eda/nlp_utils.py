"""Procesamiento básico de lenguaje natural para comandos."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .logger import get_logger

log = get_logger("nlp_utils")


@dataclass
class ParsedCommand:
    """Representa un comando interpretado."""

    intent: str
    entity: str = ""
    raw: str = ""
    confidence: float = 0.0


INTENT_PATTERNS: Dict[str, str] = {
    "capability_plan": (
        r"\b(cómo implementarías|como implementarias|qué harías para cumplir|que harías para cumplir|"
        r"planea cómo cumplir|planea como cumplir|diseña un plan para|analiza el proyecto para|"
        r"plan de capacidad para)\b\s*(.*)"
    ),
    "open_app": r"\b(abrir|abre|inicia|ejecuta)\s+(.+)",
    "close_app": r"\b(cerrar|cierra|termina|finaliza)\s+(.+)",
    "search_web": r"\b(busca|investiga|consulta|resuelve)\b\s*(.*)",
    "system_info": r"\b(cpu|ram|estado del sistema|temperatura|hora|fecha)\b",
    "optimize": r"\b(optimiza|limpia|acelera|mantenimiento)\b",
    "arduino_help": r"\b(arduino|led|millis|sensor|sketch|\.ino)\b\s*(.*)",
    "file_create": r"\b(crea archivo|nuevo archivo)\b",
    "bluetooth": r"\b(bluetooth|emparejar|dispositivo)\b",
    "remember": r"\b(recuerda|memoriza)\s+(.+)",
    "forget": r"\b(olvida|elimina recuerdo)\s+(.+)",
    "volume": r"\b(volumen|sube el volumen|baja el volumen|subir volumen|bajar volumen|mutea|mutear|silencia|silenciar|desmutea|desmutear)\b\s*(.*)",
    "brightness": r"\b(brillo|sube el brillo|baja el brillo|subir brillo|bajar brillo)\b\s*(.*)",
    "evolve": r"\b(evoluciona|autoevoluciona|autoevolución)\b",
}

COMPOUND_CONNECTOR_REGEX = re.compile(r"\s+(?:y\s+luego|luego|después|despues|y)\s+", flags=re.IGNORECASE)

SECONDARY_ACTION_REGEX = {
    "write_text": re.compile(r"\b(?:escribe|escribir|teclea|escríbeme)\s+(.+)", flags=re.IGNORECASE),
    "search_web": re.compile(r"\b(?:busca|investiga|consulta)\s+(.+)", flags=re.IGNORECASE),
}


def split_compound_command(text: str) -> List[str]:
    """Separa comandos unidos por conectores secuenciales simples."""
    if not text:
        return []
    parts = [p.strip(" ,.;") for p in COMPOUND_CONNECTOR_REGEX.split(text) if p.strip(" ,.;")]
    return parts


def detect_secondary_action(text: str) -> tuple[str, str]:
    """Detecta acción secundaria en comando compuesto."""
    normalized = normalize_text(text)
    for action_name, pattern in SECONDARY_ACTION_REGEX.items():
        match = pattern.search(normalized)
        if match:
            payload = match.group(1).strip(" \t\n\r.,;:!?¡¿\"'")
            return action_name, payload
    return "", ""


def normalize_text(text: str) -> str:
    """Normaliza texto para análisis ligero."""
    return re.sub(r"\s+", " ", text.strip().lower())


def normalize_learned_trigger_key(text: str) -> str:
    """
    Normaliza gatillos de automatización para coincidir con la misma clave
    al aprender y al ejecutar (puntuación, mayúsculas).
    """
    cleaned = re.sub(r"[¿?¡!.,;:\"'()\[\]]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_command(text: str) -> ParsedCommand:
    """Detecta intención de comando por patrones."""
    raw = text
    text = normalize_text(text)

    for intent, pattern in INTENT_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            entity = ""
            if len(match.groups()) >= 2:
                entity = match.group(2).strip()
            log.info("[CMD_PARSE] intent=%s entity='%s' raw='%s'", intent, entity, raw)
            return ParsedCommand(intent=intent, entity=entity, raw=raw, confidence=0.78)

    if text.endswith("?"):
        log.info("[CMD_PARSE] intent=question raw='%s'", raw)
        return ParsedCommand(intent="question", raw=raw, confidence=0.5)

    log.info("[CMD_PARSE] intent=chat raw='%s'", raw)
    return ParsedCommand(intent="chat", raw=raw, confidence=0.35)


def detect_confirmation(text: str) -> Optional[bool]:
    """Detecta confirmaciones explícitas del usuario."""
    t = normalize_text(text)
    yes_words = ["sí", "si", "confirmo", "acepto", "ok", "adelante"]
    no_words = ["no", "cancela", "detener", "alto"]

    if any(word in t for word in yes_words):
        return True
    if any(word in t for word in no_words):
        return False
    return None
