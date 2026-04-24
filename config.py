"""Configuración central de E.D.A."""

from pathlib import Path

# Rutas base
BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
SOLUTIONS_DIR = BASE_DIR / "solutions"
CAPTURES_DIR = BASE_DIR / "captures"
BACKUPS_DIR = BASE_DIR / "backups"
LOGS_DIR = BASE_DIR / "logs"
SUGGESTIONS_DIR = BASE_DIR / "suggestions"

# Modelo local de IA
OLLAMA_MODEL = "llama3.2:1b"
OLLAMA_MODEL_FALLBACKS = ["llama3.2:1b", "llama3.2", "mistral:7b-instruct", "phi3:mini"]
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_HEALTH_URL = "http://127.0.0.1:11434"

# Voz
VOICE_LANGUAGE = "es"
VOICE_RATE = 175
VOICE_VOLUME = 1.0
WAKE_WORDS = ["e.d.a.", "eda", "jarvis"]
VOICE_RECOGNITION_TIMEOUT = 4
VOICE_PHRASE_TIME_LIMIT = 8

# Comportamiento
APP_NAME = "E.D.A."
APP_PERSONALITY = (
    "Eres E.D.A., un mayordomo digital elegante, formal y técnico. "
    "Respondes siempre en español claro, estructurado y útil, con tono respetuoso."
)

# Seguridad y confirmaciones
REQUIRE_CONFIRMATION_CRITICAL = True
AUTOEVOLUTION_REQUIRES_PERMISSION = True
# Activa/desactiva petición de permiso en acciones sensibles de GUI.
ASK_PERMISSION_FOR_SENSITIVE_ACTIONS = True

# Ruta de backup deseada por el usuario (Windows)
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

# Web solver
WEB_SOLVER_MAX_RESULTS = 10
WEB_SOLVER_SCRAPE_LIMIT = 9000
WEB_SOLVER_CACHE_TTL_HOURS = 72

# Otros
DEFAULT_TIMEOUT = 25
USER_AGENT = "EDA-Agent/2.0"
HTTP_RETRY_TOTAL = 2
HTTP_RETRY_BACKOFF = 0.4
HTTP_RETRY_STATUS_CODES = [429, 500, 502, 503, 504]
MEMORY_CACHE_TTL_SECONDS = 2.0

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
