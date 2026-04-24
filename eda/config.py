"""Configuración central de E.D.A."""

from pathlib import Path

# Rutas base (raíz del repo: carpeta padre del paquete eda/)
BASE_DIR = Path(__file__).resolve().parent.parent
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

# Otros
DEFAULT_TIMEOUT = 25
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
