"""Procesamiento básico de lenguaje natural para comandos."""

from __future__ import annotations

import re
import unicodedata
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
    "system_info": r"\b(estado del sistema|temperatura|hora|fecha|uso de cpu|uso de ram|ram actual|consumo de ram|cpu actual)\b",
    "optimize": r"\b(optimiza|limpia|acelera|mantenimiento)\b",
    "arduino_help": r"\b(arduino|led|millis|sensor|sketch|\.ino)\b\s*(.*)",
    "file_create": r"\b(crea archivo|nuevo archivo)\b",
    "bluetooth": r"\b(bluetooth|emparejar|dispositivo)\b",
    "remember": r"\b(recuerda|memoriza)\s+(.+)",
    "forget": r"\b(olvida|elimina recuerdo)\s+(.+)",
    "volume": r"\b(volumen|sube el volumen|baja el volumen|subir volumen|bajar volumen|mutea|mutear|silencia|silenciar|desmutea|desmutear)\b\s*(.*)",
    "brightness": r"\b(brillo|sube el brillo|baja el brillo|subir brillo|bajar brillo)\b\s*(.*)",
    "evolve": r"\b(evoluciona|autoevoluciona|autoevolución)\b",
    "organize_directory": r"\b(organiza|ordena|clasifica|limpia)\s+(?:la\s+carpeta\s+)?(.+)",
    "screen_comprehension": r"\b(que hay en mi pantalla|qué hay en mi pantalla|explicame este error|explícame este error|analiza mi pantalla|analiza esta pantalla)\b",
    "create_presentation": r"\b(hazme una presentación|crea una presentación|crear presentacion|crear presentación)\b\s*(.*)",
    "list_windows": r"\b(lista(?:r)?|muestra(?:r)?)\s+(?:las\s+)?ventanas\s+(?:abiertas|activas)\b",
    "focus_window": r"\b(?:enfoca|activar|activa)\s+ventana\s+(.+)",
    "activate_app_window": r"\b(?:activa|enfoca)\s+(.+)$",
    "shutdown_system": r"\b(?:apaga|apagar)\s+(?:el\s+)?(?:pc|equipo|sistema|computador|ordenador)\b",
    "restart_system": r"\b(?:reinicia|reiniciar)\s+(?:el\s+)?(?:pc|equipo|sistema|computador|ordenador)\b",
}

COMPOUND_CONNECTOR_REGEX = re.compile(r"\s+(?:y\s+luego|luego|después|despues|y)\s+", flags=re.IGNORECASE)

SECONDARY_ACTION_REGEX = {
    "write_text": re.compile(r"\b(?:escribe|escribir|teclea|escríbeme)\s+(.+)", flags=re.IGNORECASE),
    "search_web": re.compile(r"\b(?:busca|investiga|consulta)\s+(.+)", flags=re.IGNORECASE),
}

TECH_KEYWORDS = re.compile(
    r"\b(api|tcp|udp|ram|algoritmo|variable|python|javascript|sql|docker|kubernetes|"
    r"rest|http|https|socket|compilador|memoria|cache|latencia|backend|frontend|ollama|llm)\b",
    flags=re.IGNORECASE,
)
DEBUG_KEYWORDS = re.compile(
    r"\b(error|bug|traceback|stack trace|excepción|exception|no funciona|falla|falla con|"
    r"debug|depurar|rompe|crash)\b",
    flags=re.IGNORECASE,
)
EXPLANATION_START = re.compile(
    r"^\s*(explicame|explícame|explica|detalla|desglosa|desarrolla)\b",
    flags=re.IGNORECASE,
)
QUESTION_START = re.compile(
    r"^\s*(que|qué|quien|quién|cual|cuál|como|cómo|por que|por qué|cuando|cuándo|donde|dónde)\b",
    flags=re.IGNORECASE,
)
ACTION_START = re.compile(
    r"^\s*(abre|abrir|cierra|cerrar|ejecuta|inicia|reproduce|pon|busca|investiga|apaga|reinicia|mutea|desmutea)\b",
    flags=re.IGNORECASE,
)


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


def normalize_confirmation_text(text: str) -> str:
    """Normaliza confirmaciones: minúsculas, sin acentos y sin puntuación."""
    raw = (text or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", raw)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    clean = re.sub(r"[^\w\s]", " ", no_accents)
    return re.sub(r"\s+", " ", clean).strip()


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

    open_and_play_match = re.search(
        r"\b(?:abre|abrir|inicia|ejecuta)\s+([a-z0-9áéíóúñ._ -]+?)\s+y\s+(?:reproduce|reproducir|pon|ponme|toca|play|escucha)\s+(.+)$",
        text,
    )
    if open_and_play_match:
        app = open_and_play_match.group(1).strip()
        query = open_and_play_match.group(2).strip()
        entity = f"{app}|||{query}"
        log.info("[CMD_PARSE] intent=open_and_play_music entity='%s' raw='%s'", entity, raw)
        return ParsedCommand(intent="open_and_play_music", entity=entity, raw=raw, confidence=0.93)

    open_and_search_match = re.search(
        r"\b(?:abre|abrir|inicia|ejecuta)\s+([a-z0-9áéíóúñ._ -]+?)\s+y\s+(?:busca|buscar|búscame|buscame)\s+(.+)$",
        text,
    )
    if open_and_search_match:
        app = open_and_search_match.group(1).strip()
        query = open_and_search_match.group(2).strip()
        entity = f"{app}|||{query}"
        log.info("[CMD_PARSE] intent=open_and_search_in_app entity='%s' raw='%s'", entity, raw)
        return ParsedCommand(intent="open_and_search_in_app", entity=entity, raw=raw, confidence=0.91)

    search_in_app_match = re.search(
        r"\b(?:busca|buscar|búscame|buscame)\s+(.+?)\s+en\s+([a-z0-9áéíóúñ._ -]+)\b",
        text,
    )
    if search_in_app_match:
        query = search_in_app_match.group(1).strip()
        app = search_in_app_match.group(2).strip()
        entity = f"{app}|||{query}"
        log.info("[CMD_PARSE] intent=search_in_app entity='%s' raw='%s'", entity, raw)
        return ParsedCommand(intent="search_in_app", entity=entity, raw=raw, confidence=0.9)

    play_music_match = re.search(
        r"^\s*(?:reproduce|reproducir|pon|ponme|toca|play|escucha)\s+(.+?)\s*$",
        text,
    )
    if play_music_match:
        query = play_music_match.group(1).strip()
        log.info("[CMD_PARSE] intent=play_music entity='%s' raw='%s'", query, raw)
        return ParsedCommand(intent="play_music", entity=query, raw=raw, confidence=0.92)

    try:
        from .nlu.spotify_intent import utterance_might_be_spotify
    except Exception:  # pragma: no cover
        utterance_might_be_spotify = lambda _t: False
    if utterance_might_be_spotify(raw):
        log.info("[CMD_PARSE] intent=play_music (spotify hint) entity='%s' raw='%s'", raw.strip(), raw)
        return ParsedCommand(intent="play_music", entity=raw.strip(), raw=raw, confidence=0.89)

    for intent, pattern in INTENT_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            entity = ""
            if len(match.groups()) >= 2:
                entity = match.group(2).strip()
            log.info("[CMD_PARSE] intent=%s entity='%s' raw='%s'", intent, entity, raw)
            return ParsedCommand(intent=intent, entity=entity, raw=raw, confidence=0.78)

    if DEBUG_KEYWORDS.search(text):
        log.info("[CMD_PARSE] intent=debugging_request raw='%s'", raw)
        return ParsedCommand(intent="debugging_request", entity=text, raw=raw, confidence=0.88)

    if EXPLANATION_START.search(text):
        intent = "technical_question" if TECH_KEYWORDS.search(text) else "explanation_request"
        log.info("[CMD_PARSE] intent=%s raw='%s'", intent, raw)
        return ParsedCommand(intent=intent, entity=text, raw=raw, confidence=0.86)

    if QUESTION_START.search(text) or text.endswith("?"):
        if TECH_KEYWORDS.search(text):
            log.info("[CMD_PARSE] intent=technical_question raw='%s'", raw)
            return ParsedCommand(intent="technical_question", entity=text, raw=raw, confidence=0.87)
        if any(k in text for k in ["teoría", "teoria", "concepto", "definición", "definicion"]):
            log.info("[CMD_PARSE] intent=theoretical_question raw='%s'", raw)
            return ParsedCommand(intent="theoretical_question", entity=text, raw=raw, confidence=0.85)
        log.info("[CMD_PARSE] intent=general_knowledge_question raw='%s'", raw)
        return ParsedCommand(intent="general_knowledge_question", entity=text, raw=raw, confidence=0.82)

    if ACTION_START.search(text):
        log.info("[CMD_PARSE] intent=action_command raw='%s'", raw)
        return ParsedCommand(intent="action_command", entity=text, raw=raw, confidence=0.74)

    if text.endswith("?"):
        log.info("[CMD_PARSE] intent=question raw='%s'", raw)
        return ParsedCommand(intent="question", raw=raw, confidence=0.5)

    log.info("[CMD_PARSE] intent=chat raw='%s'", raw)
    return ParsedCommand(intent="chat", raw=raw, confidence=0.35)


def detect_confirmation(text: str) -> Optional[bool]:
    """Detecta confirmaciones explícitas del usuario."""
    mode = detect_confirmation_mode(text)
    if mode in {"yes", "force"}:
        return True
    if mode == "no":
        return False
    return None


def detect_confirmation_mode(text: str) -> str:
    """
    Devuelve modo de confirmación: yes | no | force | none.
    Se usa para respuestas cortas de UI/STT como 'si', 's', 'no', 'forzar'.
    """
    t = normalize_confirmation_text(text)
    if not t:
        return "none"
    yes_words = {
        "si",
        "s",
        "confirmo",
        "acepto",
        "ok",
        "dale",
        "vamos",
        "procede",
        "confirmar",
        "adelante",
    }
    no_words = {"no", "n", "nop", "cancelar", "nope", "detener", "stop", "cancela", "alto"}
    force_words = {"forzar", "forzar cierre", "forcer", "kill", "force", "si forzar", "si forzar cierre"}
    if t in force_words or t.startswith("forzar "):
        return "force"
    if t in yes_words:
        return "yes"
    if t in no_words:
        return "no"
    # Fallback tolerante para frases mayores.
    if any(token in t for token in ("forzar", "force", "kill")):
        return "force"
    if any(token in t.split() for token in ("si", "confirmo", "acepto", "procede")):
        return "yes"
    if any(token in t.split() for token in ("no", "cancelar", "detener", "stop")):
        return "no"
    return "none"
