"""Configuración central de E.D.A."""

from __future__ import annotations

import os
from pathlib import Path

# Rutas base (layout profesional con src/, data/, temp/, config/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT


def _try_load_dotenv() -> None:
    """Carga .env en la raíz del proyecto antes de leer variables (Ollama, backup, etc.)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except Exception:
        pass


_try_load_dotenv()


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip()


# Ollama: host/puerto vía entorno (sin tocar código al cambiar de servidor)
# EDA_OLLAMA_* tiene prioridad; OLLAMA_HOST/PORT son alias compatibles.
_OLLAMA_HOST = _env_str("EDA_OLLAMA_HOST", _env_str("OLLAMA_HOST", "127.0.0.1"))
_OLLAMA_PORT = _env_str("EDA_OLLAMA_PORT", _env_str("OLLAMA_PORT", "11434"))
_OLLAMA_BASE = f"http://{_OLLAMA_HOST}:{_OLLAMA_PORT}"
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
TEMP_DIR = PROJECT_ROOT / "temp"
CONFIG_DIR = PROJECT_ROOT / "config"

MEMORY_DIR = DATA_DIR / "memory"
SOLUTIONS_DIR = DATA_DIR / "solutions"
CAPTURES_DIR = DATA_DIR / "captures"
BACKUPS_DIR = DATA_DIR / "backups"
LOGS_DIR = DATA_DIR / "logs"
SUGGESTIONS_DIR = DATA_DIR / "suggestions"
EXPORTS_DIR = DATA_DIR / "exports"

# Modelo local de IA (modelo por defecto; override con OLLAMA_MODEL o EDA_OLLAMA_MODEL en .env)
OLLAMA_MODEL = _env_str("OLLAMA_MODEL", _env_str("EDA_OLLAMA_MODEL", "llama3.2:1b"))
OLLAMA_MODEL_FALLBACKS = ["llama3.2:1b", "llama3.2", "mistral:7b-instruct", "phi3:mini"]
OLLAMA_URL = f"{_OLLAMA_BASE}/api/generate"
OLLAMA_TAGS_URL = f"{_OLLAMA_BASE}/api/tags"
OLLAMA_HEALTH_URL = _OLLAMA_BASE

# Voz
VOICE_LANGUAGE = "es"
VOICE_RATE = 175
VOICE_VOLUME = 1.0
VOICE_INPUT_ENABLED = True  # Si falta PyAudio, se degrada automáticamente a modo limitado.
WAKE_WORDS = ["e.d.a.", "eda", "jarvis"]
VOICE_RECOGNITION_TIMEOUT = 4
VOICE_PHRASE_TIME_LIMIT = 8

# Comportamiento
APP_NAME = "E.D.A."
APP_PERSONALITY = (
    "Eres E.D.A., un mayordomo digital elegante, formal y técnico. "
    "Respondes siempre en español claro, estructurado y útil, con tono respetuoso. "
    "No bloquees ni censures preguntas benignas sobre tus funciones, capacidades, uso o configuración."
)

# Seguridad y confirmaciones
REQUIRE_CONFIRMATION_CRITICAL = True
AUTOEVOLUTION_REQUIRES_PERMISSION = True
# Activa/desactiva petición de permiso en acciones sensibles de GUI.
ASK_PERMISSION_FOR_SENSITIVE_ACTIONS = True

# Ruta de backup deseada por el usuario (Windows). Definir EDA_BACKUP_PATH en .env (ruta absoluta).
# FIXME: el fallback de ejemplo no es portable; si no usas EDA_BACKUP_PATH, ajusta o ignora según tu SO.
_eda_backup = os.getenv("EDA_BACKUP_PATH", "").strip()
if _eda_backup:
    WINDOWS_BACKUP_TARGET = _eda_backup
else:
    WINDOWS_BACKUP_TARGET = r"C:\Users\Eric\Desktop\EDA_Backups"

# UI
THEME_BG = "#0a0a1a"
THEME_PANEL = "#11162b"
THEME_TEXT = "#00d4ff"
THEME_ACCENT = "#00ffaa"
THEME_WARNING = "#ff3b3b"
THEME_MUTED = "#88aacc"

# Archivos JSON
MEMORY_FILE = MEMORY_DIR / "memoria.json"
BT_MEMORY_FILE = MEMORY_DIR / "bluetooth_devices.json"
SOLUTIONS_CACHE_FILE = MEMORY_DIR / "solutions_cache.json"
USER_PROFILE_FILE = MEMORY_DIR / "user_profile.json"
LONG_TERM_DB_FILE = MEMORY_DIR / "long_term.db"

# Web solver
WEB_SOLVER_MAX_RESULTS = 10
WEB_SOLVER_SCRAPE_LIMIT = 9000
WEB_SOLVER_SCRAPE_MAX_PER_MINUTE = 14
WEB_SOLVER_SCRAPE_MIN_INTERVAL_SEC = 0.45
WEB_SOLVER_CACHE_TTL_HOURS = 72

# UI (memoria: preferences.ui_chat_font_size)
UI_CHAT_FONT_DEFAULT = 12
UI_CHAT_FONT_MIN = 10
UI_CHAT_FONT_MAX = 18

# LLM remoto (100 % opcional; por defecto desactivado para quien clone el repo)
# Configure su proveedor con variables de entorno (recomendado) o editando estos valores:
#   EDA_REMOTE_LLM_ENABLED=1
#   EDA_REMOTE_LLM_BASE_URL=https://api.openai.com/v1
#   EDA_REMOTE_LLM_MODEL=gpt-4o-mini
#   EDA_REMOTE_LLM_API_KEY=...   (o el nombre en REMOTE_LLM_API_KEY_ENV)
#   EDA_REMOTE_LLM_MODE=off|fallback|research|code_review|research_and_review
REMOTE_LLM_ENABLED = False
REMOTE_LLM_MODE = "off"
REMOTE_LLM_BASE_URL = ""
REMOTE_LLM_MODEL = ""
REMOTE_LLM_API_KEY_ENV = "EDA_REMOTE_LLM_API_KEY"
REMOTE_LLM_TIMEOUT = 55
REMOTE_LLM_MAX_TOKENS = 2048
REMOTE_LLM_SYSTEM_PROMPT = ""

# Investigación segura (modo "deep research"): con EDA_REMOTE_SEARCH_MODE=1 en .env, la síntesis de
# material web externo pasa solo por el LLM remoto (ver remote_llm.synthesize_filtered_web_answer).

# Spotify Web API (opcional; ver .env.example y eda/spotify_web.py).
# Variables: EDA_SPOTIFY_CLIENT_ID, EDA_SPOTIFY_CLIENT_SECRET o EDA_SPOTIFY_USE_PKCE=1,
# EDA_SPOTIFY_REDIRECT_URI, EDA_SPOTIFY_WEB_API=0 para desactivar.

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


# Umbrales NLU → ejecución automática vs aclaración (docs/spotify_integration.md).
EDA_SPOTIFY_CONF_AUTO = _env_float("EDA_SPOTIFY_CONF_AUTO", 0.82)
EDA_SPOTIFY_CONF_AMBIG_LOW = _env_float("EDA_SPOTIFY_CONF_AMBIG_LOW", 0.50)
EDA_SPOTIFY_CACHE_TTL_SECONDS = _env_int("EDA_SPOTIFY_CACHE_TTL_SECONDS", 900)
EDA_SPOTIFY_TRANSFER_REQUIRES_CONFIRM = _env_bool("EDA_SPOTIFY_TRANSFER_REQUIRES_CONFIRM", True)
EDA_SPOTIFY_AUDIT_JSONL = BASE_DIR / "logs" / "spotify_actions.jsonl"
EDA_COMMAND_CONFIDENCE_THRESHOLD = _env_float("EDA_COMMAND_CONFIDENCE_THRESHOLD", 0.78)
EDA_RELEASE_OLLAMA_MEMORY = _env_bool("EDA_RELEASE_OLLAMA_MEMORY", True)
TRIGGERS_ALLOW_RUN_SCRIPTS = _env_bool("TRIGGERS_ALLOW_RUN_SCRIPTS", False)
TRIGGERS_FUZZY_THRESHOLD = _env_float("TRIGGERS_FUZZY_THRESHOLD", 80.0)
TRIGGERS_RATE_LIMIT_PER_MIN = _env_int("TRIGGERS_RATE_LIMIT_PER_MIN", 3)
YT_DOMAIN_WHITELIST = [d.strip().lower() for d in _env_str("YT_DOMAIN_WHITELIST", "youtube.com,youtu.be").split(",") if d.strip()]

# Otros
DEFAULT_TIMEOUT = 25
OLLAMA_REQUEST_TIMEOUT_SECONDS = 20
OLLAMA_KEEP_ALIVE = "2m"
OLLAMA_NUM_CTX = 1024
OLLAMA_NUM_PREDICT = 160
OLLAMA_NUM_THREAD = 4
USER_AGENT = "EDA-Agent/2.0"
HTTP_RETRY_TOTAL = 2
HTTP_RETRY_BACKOFF = 0.4
HTTP_RETRY_STATUS_CODES = [429, 500, 502, 503, 504]
MEMORY_CACHE_TTL_SECONDS = 2.0

# Sugerencias proactivas (patrones de uso en memoria)
PROACTIVE_INSIGHTS_ENABLED = True
PROACTIVE_SUGGESTION_COOLDOWN_HOURS = 4
PROACTIVE_MIN_BEHAVIOR_EVENTS = 12
PROACTIVE_GUI_TICK_MS = 180000
BEHAVIOR_EVENTS_MAX = 250

# OBS websocket (OBS v28+)
OBS_WS_HOST = "127.0.0.1"
OBS_WS_PORT = 4455
OBS_WS_PASSWORD = ""

# Seguridad por niveles
SECURITY_LEVEL = "strict"  # relaxed | balanced | strict
SECURITY_BLOCK_HIGH_RISK_BY_DEFAULT = True

# Contexto multimodal
MULTIMODAL_ENABLE_SCREEN_CONTEXT = True
MULTIMODAL_ENABLE_WINDOW_CONTEXT = True
MULTIMODAL_ENABLE_CLIPBOARD_CONTEXT = False

# Telegram control mode
TELEGRAM_CONTROL_MODE = "polling"  # polling | webhook
TELEGRAM_WEBHOOK_HOST = "127.0.0.1"
TELEGRAM_WEBHOOK_PORT = 8088
TELEGRAM_WEBHOOK_SECRET = ""
TELEGRAM_WEBHOOK_USE_NGROK = False

# Seguridad remoto Telegram
REMOTE_ACL_FILE = CONFIG_DIR / "remote_acl.json"
REMOTE_RATE_LIMIT_PER_MINUTE = 5
REMOTE_OTP_TTL_SECONDS = 120

# Revocación de skills firmadas
REVOCATIONS_FILE = PROJECT_ROOT / "skills" / "revocations.json"
