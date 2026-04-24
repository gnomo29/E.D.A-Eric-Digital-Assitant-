"""Cliente opcional para LLM remoto (API compatible con OpenAI /chat/completions).

Todo está desactivado por defecto. Cada quien configura su propio proveedor vía
variables de entorno o constantes en eda.config — no hay API keys en el repositorio.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

from . import config
from .logger import get_logger

log = get_logger("remote_llm")

_HTTP_SESSION: requests.Session | None = None

ALLOWED_MODES = frozenset({"off", "fallback", "research", "code_review", "research_and_review"})


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def remote_llm_effective_enabled() -> bool:
    if os.environ.get("EDA_REMOTE_LLM_ENABLED") is not None:
        return _env_bool("EDA_REMOTE_LLM_ENABLED", False)
    return bool(getattr(config, "REMOTE_LLM_ENABLED", False))


def remote_llm_mode() -> str:
    raw = (os.environ.get("EDA_REMOTE_LLM_MODE") or getattr(config, "REMOTE_LLM_MODE", "off") or "off").strip().lower()
    return raw if raw in ALLOWED_MODES else "off"


def remote_llm_base_url() -> str:
    return (os.environ.get("EDA_REMOTE_LLM_BASE_URL") or getattr(config, "REMOTE_LLM_BASE_URL", "") or "").strip().rstrip(
        "/"
    )


def remote_llm_model() -> str:
    return (os.environ.get("EDA_REMOTE_LLM_MODEL") or getattr(config, "REMOTE_LLM_MODEL", "") or "").strip()


def remote_llm_api_key() -> str:
    env_name = str(getattr(config, "REMOTE_LLM_API_KEY_ENV", "EDA_REMOTE_LLM_API_KEY"))
    return (os.environ.get(env_name) or os.environ.get("EDA_REMOTE_LLM_API_KEY") or "").strip()


def is_remote_fully_configured() -> bool:
    if not remote_llm_effective_enabled():
        return False
    return bool(remote_llm_base_url() and remote_llm_model() and remote_llm_api_key())


def _chat_completions_url(base: str) -> str:
    b = base.rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    return f"{b}/chat/completions"


def chat_completion(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.35,
    max_tokens: int | None = None,
) -> str:
    """POST a /chat/completions. Devuelve texto vacío si no está configurado o falla."""
    if not is_remote_fully_configured():
        return ""

    base = remote_llm_base_url()
    url = _chat_completions_url(base)
    key = remote_llm_api_key()
    model = remote_llm_model()
    mt = max_tokens if max_tokens is not None else int(getattr(config, "REMOTE_LLM_MAX_TOKENS", 2048))
    timeout = float(getattr(config, "REMOTE_LLM_TIMEOUT", 55))

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(mt),
    }

    global _HTTP_SESSION
    try:
        if _HTTP_SESSION is None:
            _HTTP_SESSION = requests.Session()
        r = _HTTP_SESSION.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = (choices[0].get("message") or {}).get("content") or ""
        return str(msg).strip()
    except Exception as exc:
        log.warning("[REMOTE_LLM] Fallo la llamada: %s", exc)
        return ""


def try_completion_single_prompt(full_prompt: str, *, purpose: str = "ask") -> str:
    """Un único bloque usuario (prompt ya armado estilo Ollama)."""
    system = (getattr(config, "REMOTE_LLM_SYSTEM_PROMPT", "") or getattr(config, "APP_PERSONALITY", "")).strip()
    messages = [
        {"role": "system", "content": system[:4000]},
        {"role": "user", "content": (full_prompt or "")[:120_000]},
    ]
    out = chat_completion(messages, temperature=0.35)
    if out:
        log.info("[REMOTE_LLM] ok purpose=%s chars=%d", purpose, len(out))
    return out


def use_remote_for_ask_fallback() -> bool:
    m = remote_llm_mode()
    return m in ("fallback", "research_and_review")


def use_remote_for_research_synthesis() -> bool:
    m = remote_llm_mode()
    return m in ("research", "research_and_review")


def use_remote_for_code_review() -> bool:
    m = remote_llm_mode()
    return m in ("code_review", "research_and_review")


def review_python_code(task: str, code: str) -> str:
    """Revisión de seguridad/estilo (texto); no modifica el código automáticamente."""
    system = (
        "Eres un revisor de código Python conservador. Responde en español, en viñetas cortas. "
        "Señala riesgos de seguridad, imports peligrosos, I/O insegura, y sugerencias menores. "
        "No reescribas el código completo."
    )
    user = f"Tarea original (resumen):\n{task[:1500]}\n\nCódigo a revisar:\n```python\n{code[:8000]}\n```"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return chat_completion(messages, temperature=0.2, max_tokens=min(2500, int(getattr(config, "REMOTE_LLM_MAX_TOKENS", 2048))))


def health_status() -> str:
    if not remote_llm_effective_enabled():
        return "disabled"
    if not remote_llm_base_url().strip() or not remote_llm_model().strip():
        return "incomplete_config"
    if not remote_llm_api_key():
        return "missing_api_key"
    return "configured"
