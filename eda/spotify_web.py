"""Spotify Web API opcional (spotipy). Sin credenciales no hace nada; si falla, la GUI usa fallback desktop."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Tuple

from . import config
from .logger import get_logger

log = get_logger("spotify_web")

try:
    import spotipy
    from spotipy.exceptions import SpotifyException
    from spotipy.oauth2 import SpotifyOAuth, SpotifyPKCE
except ImportError:  # pragma: no cover - entorno mínimo sin spotipy
    spotipy = None  # type: ignore[assignment]
    SpotifyException = type(None)  # type: ignore[misc, assignment]
    SpotifyOAuth = None  # type: ignore[misc, assignment]
    SpotifyPKCE = None  # type: ignore[misc, assignment]

_SPOTIPY_AVAILABLE = spotipy is not None and SpotifyPKCE is not None

# Scopes mínimos para buscar y mandar reproducción al dispositivo activo.
_SPOTIFY_SCOPES = "user-read-playback-state user-modify-playback-state"


def is_spotipy_installed() -> bool:
    return _SPOTIPY_AVAILABLE


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def web_api_env_enabled() -> bool:
    """Desactivar API explícitamente con EDA_SPOTIFY_WEB_API=0."""
    raw = os.environ.get("EDA_SPOTIFY_WEB_API")
    if raw is None:
        return True
    return _env_bool("EDA_SPOTIFY_WEB_API", True)


def client_id() -> str:
    return (os.environ.get("EDA_SPOTIFY_CLIENT_ID") or "").strip()


def client_secret() -> str:
    return (os.environ.get("EDA_SPOTIFY_CLIENT_SECRET") or "").strip()


def redirect_uri() -> str:
    return (os.environ.get("EDA_SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8888/callback").strip()


def use_pkce() -> bool:
    """
    PKCE sin client secret (recomendado para apps públicas / .env sin secret).
    Forzar con EDA_SPOTIFY_USE_PKCE=1 aunque exista secret.
    """
    if _env_bool("EDA_SPOTIFY_USE_PKCE", False):
        return True
    return not bool(client_secret())


def token_cache_path() -> Path:
    base = config.BASE_DIR / ".cache"
    base.mkdir(parents=True, exist_ok=True)
    return base / "spotify_token_cache.json"


def is_web_api_configured() -> bool:
    if not _SPOTIPY_AVAILABLE or not web_api_env_enabled():
        return False
    if not client_id():
        return False
    if use_pkce():
        return True
    return bool(client_secret())


def describe_integration_status() -> str:
    if not _SPOTIPY_AVAILABLE:
        return "missing_spotipy"
    if not web_api_env_enabled():
        return "disabled_by_env"
    if not client_id():
        return "not_configured"
    if not use_pkce() and not client_secret():
        return "needs_client_secret_or_pkce"
    cache = token_cache_path()
    if cache.is_file() and cache.stat().st_size > 8:
        return "configured_with_token_cache"
    return "configured_needs_login"


def _build_auth_manager() -> Any | None:
    if not is_web_api_configured():
        return None
    cache = str(token_cache_path())
    cid = client_id()
    red = redirect_uri()
    if use_pkce():
        return SpotifyPKCE(
            client_id=cid,
            redirect_uri=red,
            scope=_SPOTIFY_SCOPES,
            cache_path=cache,
            open_browser=True,
        )
    return SpotifyOAuth(
        client_id=cid,
        client_secret=client_secret(),
        redirect_uri=red,
        scope=_SPOTIFY_SCOPES,
        cache_path=cache,
        open_browser=True,
    )


def get_spotify_client() -> Any | None:
    if not _SPOTIPY_AVAILABLE:
        return None
    try:
        auth = _build_auth_manager()
        if auth is None:
            return None
        return spotipy.Spotify(auth_manager=auth)
    except Exception as exc:
        log.error("[SPOTIFY_WEB] No se pudo crear el cliente: %s", exc)
        return None


def login_script_path() -> Path:
    return config.BASE_DIR / "scripts" / "spotify_login.py"


def auto_login_on_auth_fail_enabled() -> bool:
    """EDA_SPOTIFY_AUTO_LOGIN=0 desactiva ejecutar spotify_login.py al fallar la sesión."""
    raw = os.environ.get("EDA_SPOTIFY_AUTO_LOGIN")
    if raw is None:
        return True
    return _env_bool("EDA_SPOTIFY_AUTO_LOGIN", True)


def run_interactive_spotify_login() -> bool:
    """
    Ejecuta `scripts/spotify_login.py` con el mismo Python (navegador + OAuth).
    Bloquea hasta que el script termine (típicamente tras completar el login en el navegador).
    """
    script = login_script_path()
    if not script.is_file():
        log.error("[SPOTIFY_WEB] No existe el script: %s", script)
        return False
    log.info("[SPOTIFY_WEB] Ejecutando login interactivo: %s", script)
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(config.BASE_DIR),
            check=False,
            timeout=600,
        )
        ok = proc.returncode == 0
        if not ok:
            log.warning("[SPOTIFY_WEB] spotify_login.py terminó con código %s", proc.returncode)
        return ok
    except subprocess.TimeoutExpired:
        log.error("[SPOTIFY_WEB] Timeout esperando spotify_login.py (10 min)")
        return False
    except Exception as exc:
        log.error("[SPOTIFY_WEB] Error ejecutando spotify_login.py: %s", exc)
        return False


def _is_auth_or_session_error(http_status: int | None, message: str) -> bool:
    """401 / token revocado / invalid_grant → conviene re-ejecutar OAuth interactivo."""
    m = (message or "").lower()
    if http_status == 401:
        return True
    if "invalid_grant" in m or "token expired" in m or "expired token" in m:
        return True
    if "invalid_client" in m or "unauthorized" in m:
        return True
    if http_status == 400 and ("invalid" in m and "token" in m):
        return True
    return False


def warmup_oauth() -> bool:
    """
    Fuerza login OAuth (abre navegador la primera vez). Ejecutar desde consola:
    `python scripts/spotify_login.py`
    """
    sp = get_spotify_client()
    if not sp:
        log.warning("[SPOTIFY_WEB] warmup: cliente no disponible (¿EDA_SPOTIFY_CLIENT_ID?)")
        return False
    try:
        user = sp.current_user()
        name = (user or {}).get("display_name") or (user or {}).get("id") or "usuario"
        log.info("[SPOTIFY_WEB] Sesión OK: %s", name)
        return True
    except Exception as exc:
        log.error("[SPOTIFY_WEB] warmup falló: %s", exc)
        return False


def _pick_device_id(sp: Any) -> str | None:
    try:
        data = sp.devices() or {}
    except Exception as exc:
        log.debug("[SPOTIFY_WEB] devices: %s", exc)
        return None
    devices = data.get("devices") or []
    for d in devices:
        if d.get("is_active") and d.get("id"):
            return str(d["id"])
    for d in devices:
        if (d.get("type") or "").lower() == "computer" and d.get("id"):
            return str(d["id"])
    if devices and devices[0].get("id"):
        return str(devices[0]["id"])
    return None


def _first_track_uri(sp: Any, query: str) -> tuple[str | None, bool]:
    """
    Retorna (uri | None, necesita_reauth).
    necesita_reauth es True si falló la búsqueda por sesión/token inválido.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return None, False
    try:
        results = sp.search(q=q, type="track", limit=8)
    except Exception as exc:
        log.warning("[SPOTIFY_WEB] search falló: %s", exc)
        if _SPOTIPY_AVAILABLE and isinstance(exc, SpotifyException):
            code = getattr(exc, "http_status", None)
            if _is_auth_or_session_error(code, str(exc)):
                return None, True
        return None, False
    items = (((results or {}).get("tracks") or {}).get("items")) or []
    if not items:
        return None, False
    uri = items[0].get("uri")
    return (str(uri) if uri else None), False


def _attempt_play(query: str) -> Tuple[str, str, bool]:
    """
    Un intento de búsqueda + start_playback.
    Retorna (status, detail, needs_reauth).
    """
    if not _SPOTIPY_AVAILABLE:
        return "skip", "spotipy_missing", False
    if not is_web_api_configured():
        return "skip", "not_configured", False

    sp = get_spotify_client()
    if not sp:
        return "skip", "no_client", False

    track_uri, search_reauth = _first_track_uri(sp, query)
    if search_reauth:
        return "fail", "auth_error_search", True
    if not track_uri:
        return "fail", "no_tracks_found", False

    device_id = _pick_device_id(sp)
    kwargs: dict[str, Any] = {"uris": [track_uri]}
    if device_id:
        kwargs["device_id"] = device_id

    try:
        sp.start_playback(**kwargs)
    except Exception as exc:
        if _SPOTIPY_AVAILABLE and isinstance(exc, SpotifyException):
            code = getattr(exc, "http_status", None)
            msg = str(exc)
            log.warning("[SPOTIFY_WEB] start_playback: http=%s %s", code, msg)
            if _is_auth_or_session_error(code, msg):
                return "fail", "auth_error_playback", True
            if code == 404:
                return "fail", "no_active_device", False
            if code == 403:
                return "fail", "forbidden_premium_or_scope", False
            return "fail", f"api_error:{code or msg[:120]}", False
        log.warning("[SPOTIFY_WEB] start_playback inesperado: %s", exc)
        if _is_auth_or_session_error(None, str(exc)):
            return "fail", "auth_error_playback", True
        return "fail", f"api_error:{exc.__class__.__name__}", False

    name = ""
    try:
        tid = track_uri.rsplit(":", 1)[-1]
        t = sp.track(tid)
        if isinstance(t, dict):
            name = (t.get("name") or "").strip()
    except Exception:
        pass
    detail = name or track_uri
    return "ok", detail, False


def try_play_via_web_api(query: str) -> Tuple[str, str]:
    """
    Intenta reproducir vía Web API.

    Si no hay token en caché, o si falla por sesión/token (401, invalid_grant, etc.),
    ejecuta `scripts/spotify_login.py` (mismo intérprete que E.D.A.) y reintenta una vez.

    Desactivar todo el comportamiento automático de login: EDA_SPOTIFY_AUTO_LOGIN=0

    Returns
    -------
    ("ok", detail)
        Reproducción solicitada correctamente (detail puede ser URI o nombre).
    ("skip", reason)
        No aplica (sin spotipy / sin config / deshabilitado).
    ("fail", reason)
        Configurado pero error recuperable; la GUI puede usar fallback desktop.
    """
    if not _SPOTIPY_AVAILABLE:
        return "skip", "spotipy_missing"
    if not is_web_api_configured():
        return "skip", "not_configured"

    if auto_login_on_auth_fail_enabled():
        cache = token_cache_path()
        try:
            cache_empty = not cache.is_file() or cache.stat().st_size < 32
        except OSError:
            cache_empty = True
        if cache_empty:
            log.info("[SPOTIFY_WEB] Caché de token ausente o vacío; ejecutando spotify_login.py ...")
            run_interactive_spotify_login()

    status, detail, needs_reauth = _attempt_play(query)
    if status == "ok" or not needs_reauth or not auto_login_on_auth_fail_enabled():
        return status, detail

    log.info("[SPOTIFY_WEB] Fallo de autenticación/sesión; lanzando spotify_login.py ...")
    if not run_interactive_spotify_login():
        return "fail", "spotify_login_failed"

    status2, detail2, needs_reauth2 = _attempt_play(query)
    if needs_reauth2:
        log.warning("[SPOTIFY_WEB] Sigue fallando la sesión tras login interactivo.")
    return status2, detail2
