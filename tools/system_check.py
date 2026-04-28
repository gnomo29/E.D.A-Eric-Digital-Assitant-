#!/usr/bin/env python3
"""Chequeo rápido del ecosistema: Groq, Spotify, Ollama y UI."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda.utils import load_env_dotfile

load_env_dotfile()

from eda import remote_llm, spotify_web  # noqa: E402

CHECK = "✅"
FAIL = "❌"


def _safe_get_json(url: str, timeout: float = 2.5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")


def check_groq() -> tuple[bool, str]:
    if not remote_llm.remote_search_mode_requested():
        return False, "modo remoto desactivado (EDA_REMOTE_SEARCH_MODE=0)"
    if not remote_llm.is_remote_fully_configured():
        return False, "Groq/LLM remoto no está totalmente configurado"
    try:
        ans = remote_llm.chat_completion(
            [
                {"role": "system", "content": "Responde breve."},
                {"role": "user", "content": "Responde solo: OK"},
            ],
            temperature=0.0,
            max_tokens=8,
        )
    except Exception as exc:
        return False, f"error llamando API remota: {exc}"
    if not ans:
        return False, "respuesta inválida del LLM remoto"
    return True, "API remota responde"


def check_spotify() -> tuple[bool, str]:
    if not spotify_web.is_web_api_configured():
        return False, "Spotify Web API no configurada"
    sp = spotify_web.get_spotify_client()
    if not sp:
        return False, "cliente Spotify no disponible"
    try:
        me = sp.current_user() or {}
    except Exception as exc:
        return False, f"fallo de autenticación/token: {exc}"
    user = me.get("display_name") or me.get("id") or "usuario"
    return True, f"autenticado como {user}"


def check_ollama() -> tuple[bool, str]:
    try:
        _safe_get_json("http://127.0.0.1:11434/api/version", timeout=2.0)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"Ollama no responde: {exc}"
    try:
        data = _safe_get_json("http://127.0.0.1:11434/api/tags", timeout=3.0)
    except Exception as exc:
        return False, f"no pude leer /api/tags: {exc}"
    names = [str((m or {}).get("name") or "") for m in (data.get("models") or [])]
    ok = any(n == "llama3.2:1b" or n.startswith("llama3.2:1b:") for n in names)
    if not ok:
        return False, "falta modelo llama3.2:1b (ejecuta: ollama pull llama3.2:1b)"
    return True, "modelo llama3.2:1b disponible"


def check_ui_init() -> tuple[bool, str]:
    try:
        import ui_main  # type: ignore

        ui_main.parse_args(["--no-gui"])
    except Exception as exc:
        return False, f"fallo import/init UI: {exc}"
    return True, "UI Obsidian inicializable"


def main() -> int:
    enc = (sys.stdout.encoding or "").lower()
    if "utf" not in enc:
        ok_mark, fail_mark = "[OK]", "[FAIL]"
    else:
        ok_mark, fail_mark = CHECK, FAIL
    checks = [
        ("Groq remoto", check_groq),
        ("Spotify auth", check_spotify),
        ("Ollama 1b", check_ollama),
        ("UI init", check_ui_init),
    ]
    failures = 0
    print("=== EDA System Check ===")
    for label, fn in checks:
        ok, detail = fn()
        print(f"{ok_mark if ok else fail_mark} {label}: {detail}")
        if not ok:
            failures += 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
