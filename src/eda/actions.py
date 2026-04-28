"""Acciones del sistema y aplicaciones con confirmaciones."""

from __future__ import annotations

import getpass
import glob
import os
import re
import shutil
import subprocess
import time
import webbrowser
import signal
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, unquote
from urllib.request import Request, urlopen

from . import config
from .logger import get_logger
from .utils import detect_platform
from .utils.security import sanitize_app_target, sanitize_user_input
from .undo_manager import UndoManager
from .audit_log import audit_event

log = get_logger("actions")

try:
    import pygetwindow as gw
except Exception:
    gw = None

try:
    import psutil
except Exception:
    psutil = None

if os.name == "nt":
    try:
        import win32con
        import win32gui
        import win32process
    except Exception:
        win32con = None
        win32gui = None
        win32process = None

try:
    import screen_brightness_control as sbc
except Exception:
    sbc = None

try:
    if os.name == "nt":
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    else:
        AudioUtilities = None
except Exception:
    AudioUtilities = None


def _win_keybd_volume_pulse(vk: int, presses: int) -> None:
    """Pulsa teclas de volumen del sistema (Windows). ~2 %% por paso en muchos equipos."""
    if os.name != "nt" or presses <= 0:
        return
    try:
        import ctypes

        for _ in range(presses):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    except Exception as exc:
        log.debug("keybd volumen no disponible: %s", exc)


class ActionController:
    """Ejecutor de acciones de sistema con protección."""

    APP_ALIASES = {
        "steam": "steam",
        "chrome": "chrome",
        "google": "chrome",
        "firefox": "firefox",
        "notepad": "notepad",
        "bloc": "notepad",
        "bloque de notas": "notepad",
        "explorador": "explorer",
        "explorer": "explorer",
        "spotify": "spotify",
        "vscode": "code",
        "code": "code",
        "cmd": "cmd",
        "terminal": "cmd",
        "discord": "discord",
        "whatsapp": "whatsapp",
        "calculadora": "calc",
        "calc": "calc",
        "paint": "mspaint",
        "edge": "msedge",
        "word": "winword",
        "excel": "excel",
        "blender": "blender",
        "cursor": "cursor",
    }

    WEB_APP_URLS = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "twitter": "https://x.com",
        "x": "https://x.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "linkedin": "https://www.linkedin.com",
        "reddit": "https://www.reddit.com",
        "wikipedia": "https://www.wikipedia.org",
        "twitch": "https://www.twitch.tv",
        "netflix": "https://www.netflix.com",
    }
    LOCAL_FILE_EXTENSIONS = {
        ".txt",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".csv",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".ini",
        ".log",
        ".md",
        ".py",
        ".js",
        ".ts",
        ".zip",
        ".rar",
        ".7z",
    }
    
    # Rutas comunes de aplicaciones en Windows
    WINDOWS_APP_PATHS = {
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "firefox": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
        "steam": [
            r"C:\Program Files\Steam\steam.exe",
            r"C:\Program Files (x86)\Steam\steam.exe",
        ],
        "spotify": [
            r"C:\Users\{user}\AppData\Roaming\Spotify\Spotify.exe",
        ],
        "discord": [
            r"C:\Users\{user}\AppData\Local\Discord\app-*\Discord.exe",
        ],
        "vscode": [
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Users\{user}\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        ],
        "code": [
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Users\{user}\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        ],
        "blender": [
            r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
        ],
        "cursor": [
            r"C:\Users\{user}\AppData\Local\Programs\cursor\Cursor.exe",
        ],
    }

    YOUTUBE_COMMAND_REGEX = re.compile(
        r"\b(?:busca|buscar|búscame|buscame|pon|ponme)\s+(.+?)\s+en\s+youtube\b",
        flags=re.IGNORECASE,
    )
    FORBIDDEN_DISPLAY_COMMANDS = (
        "xrandr",
        "nircmd",
        "setdisplayconfig",
        "changedisplaysettings",
        "displayswitch",
        "monitor",
        "refresh rate",
        "resolucion",
        "resolución",
        "gpu",
    )
    SPOTIFY_COMMAND_REGEX = re.compile(
        r"\b(?:reproduce|pon|ponme|busca|buscar|búscame|buscame)\s+(.+?)\s+en\s+spotify\b",
        flags=re.IGNORECASE,
    )
    SPOTIFY_PLAY_FALLBACK_REGEX = re.compile(
        r"^\s*(?:reproduce|reproducir|reproduzca|reprodusca|pon|ponme)\s+(.+?)\s*$",
        flags=re.IGNORECASE,
    )
    STEAM_COMMAND_REGEX = re.compile(
        r"\b(?:busca|buscar|búscame|buscame)\s+(.+?)\s+en\s+steam\b",
        flags=re.IGNORECASE,
    )
    FILE_ORGANIZER_BUCKETS = {
        "Imagenes": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"},
        "Documentos": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".csv", ".xls", ".xlsx", ".ppt", ".pptx"},
        "Musica": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"},
        "Ejecutables": {".exe", ".msi", ".bat", ".cmd", ".ps1", ".appimage", ".sh"},
    }

    def __init__(self, confirm_callback: Callable[[str], bool] | None = None) -> None:
        self.confirm_callback = confirm_callback
        self.platform = detect_platform()
        self.undo_manager = UndoManager()
        # Caché simple para reducir búsquedas costosas repetidas.
        self._app_path_cache: Dict[str, str] = {}
        self._start_app_id_cache: Dict[str, str] = {}

    def _confirm(self, message: str) -> bool:
        if not config.REQUIRE_CONFIRMATION_CRITICAL:
            return True
        if self.confirm_callback:
            return self.confirm_callback(message)
        return False

    def _normalize_app(self, app_name: str) -> str:
        """Normaliza nombre de app, tolerando frases largas y puntuación."""
        raw = (app_name or "").strip()
        cleaned = re.sub(r'[¿?¡!.,;:"\'()\[\]]', " ", raw.lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return raw.strip()

        # Coincidencia exacta primero.
        if cleaned in self.APP_ALIASES:
            return self.APP_ALIASES[cleaned]

        # Si la frase menciona una app conocida, priorizar esa entidad.
        tokens = re.findall(r"[a-z0-9áéíóúñ._-]+", cleaned)
        for token in tokens:
            if token in self.APP_ALIASES:
                return self.APP_ALIASES[token]

        # Caso común: "... en word" / "... en steam".
        trailing_match = re.search(r"\ben\s+([a-z0-9áéíóúñ._-]+)\b", cleaned)
        if trailing_match:
            candidate = trailing_match.group(1)
            if candidate in self.APP_ALIASES:
                return self.APP_ALIASES[candidate]
            return candidate

        stopwords = {
            "un",
            "una",
            "el",
            "la",
            "los",
            "las",
            "de",
            "del",
            "en",
            "por",
            "favor",
            "hoja",
            "documento",
            "blanco",
        }
        filtered = [t for t in tokens if t not in stopwords]
        if filtered:
            candidate = filtered[0]
            return self.APP_ALIASES.get(candidate, candidate)

        return raw.strip()

    @staticmethod
    def _looks_like_url_target(target: str) -> bool:
        low = (target or "").strip().lower()
        if not low:
            return False
        if any(sep in low for sep in ("\\", "/")) and not low.startswith(("http://", "https://")):
            return False
        if ":" in low and not low.startswith(("http://", "https://")):
            # Permitir localhost:puerto e IP:puerto, pero evitar rutas de Windows tipo C:\...
            if not (re.match(r"^localhost:\d{1,5}$", low) or re.match(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{1,5}$", low)):
                if re.match(r"^[a-z]:", low):
                    return False
        if not low.startswith(("http://", "https://")):
            for ext in ActionController.LOCAL_FILE_EXTENSIONS:
                if low.endswith(ext):
                    return False
        if low.startswith(("http://", "https://", "www.")):
            return True
        if re.match(r"^localhost(?::\d{1,5})?$", low):
            return True
        if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?$", low):
            return True
        return bool(re.match(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::\d{1,5})?$", low))

    def _resolve_web_target_url(self, target: str) -> str:
        cleaned = (target or "").strip()
        lowered = cleaned.lower()
        if lowered in self.WEB_APP_URLS:
            return self.WEB_APP_URLS[lowered]
        if self._looks_like_url_target(cleaned):
            if lowered.startswith(("http://", "https://")):
                return cleaned
            if lowered.startswith("www."):
                return f"https://{cleaned}"
            if lowered.startswith("localhost") or re.match(r"^\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?$", lowered):
                return f"http://{cleaned}"
            return f"https://{cleaned}"
        return ""

    @classmethod
    def _contains_forbidden_display_command(cls, text: str) -> bool:
        low = (text or "").strip().lower()
        if not low:
            return False
        return any(token in low for token in cls.FORBIDDEN_DISPLAY_COMMANDS)

    def activate_app_window(self, app_name: str) -> Dict[str, str]:
        """Intenta activar una ventana existente de la aplicación indicada."""
        if gw is None:
            return {"status": "error", "message": "pygetwindow no disponible"}

        normalized = self._normalize_app(app_name).lower()
        aliases = {normalized}
        for key, value in self.APP_ALIASES.items():
            if value == normalized:
                aliases.add(key)

        try:
            for window in gw.getAllWindows():
                title = (window.title or "").strip()
                lower_title = title.lower()
                if not title:
                    continue
                if any(alias and alias in lower_title for alias in aliases):
                    if window.isMinimized:
                        window.restore()
                    window.activate()
                    return {"status": "ok", "message": f"Ventana activada: {title}"}
        except Exception as exc:
            log.error("Error activando ventana de '%s': %s", app_name, exc)
            return {"status": "error", "message": str(exc)}

        return {"status": "error", "message": f"No encontré ventana activa para {normalized}"}

    def _find_app_path(self, app_name: str) -> str | None:
        """Busca la ruta de una aplicación en Windows con estrategia escalonada y límite de tiempo."""
        if not self.platform.startswith("win"):
            return None

        started_at = time.monotonic()
        timeout_seconds = 5.0
        max_depth = 3
        normalized = app_name.strip().lower().removesuffix(".exe")
        username = os.environ.get("USERNAME") or getpass.getuser() or ""

        cached = self._app_path_cache.get(normalized)
        if cached and os.path.isfile(cached):
            return cached

        def time_left() -> float:
            return timeout_seconds - (time.monotonic() - started_at)

        def timed_out() -> bool:
            return time_left() <= 0

        def exists_file(path: str) -> bool:
            return os.path.isfile(path)

        log.info("[APP_SEARCH] Iniciando búsqueda de '%s' (timeout=%.1fs)", normalized, timeout_seconds)

        # 1) Rutas conocidas (rápido y directo)
        known_paths = self.WINDOWS_APP_PATHS.get(normalized, [])
        if known_paths:
            log.debug("[APP_SEARCH] Revisando %d rutas conocidas para '%s'", len(known_paths), normalized)
            for path_template in known_paths:
                if timed_out():
                    log.warning("[APP_SEARCH] Timeout durante rutas conocidas para '%s'", normalized)
                    return None

                resolved = path_template.replace("{user}", username)
                if "*" in resolved:
                    matches = glob.glob(resolved)
                    if matches:
                        selected = matches[0]
                        log.info("[APP_SEARCH] Encontrado en ruta conocida con glob: %s", selected)
                        self._app_path_cache[normalized] = selected
                        return selected
                elif exists_file(resolved):
                    log.info("[APP_SEARCH] Encontrado en ruta conocida: %s", resolved)
                    self._app_path_cache[normalized] = resolved
                    return resolved

        # 2) Búsqueda automática en ubicaciones comunes de Windows (máx. 2-3 niveles)
        roots = [
            r"C:\Program Files",
            r"C:\Program Files (x86)",
            rf"C:\Users\{username}\AppData\Local",
            rf"C:\Users\{username}\AppData\Roaming",
            rf"C:\Users\{username}\AppData\Local\Programs",
        ]
        candidate_patterns = [f"{normalized}.exe", f"*{normalized}*.exe"]

        log.debug("[APP_SEARCH] Búsqueda automática en %d raíces comunes", len(roots))
        for root in roots:
            if timed_out():
                log.warning("[APP_SEARCH] Timeout antes de completar búsqueda por raíces para '%s'", normalized)
                return None

            if not os.path.isdir(root):
                log.debug("[APP_SEARCH] Raíz no disponible: %s", root)
                continue

            log.debug("[APP_SEARCH] Explorando raíz: %s", root)
            for depth in range(0, max_depth + 1):
                if timed_out():
                    log.warning("[APP_SEARCH] Timeout en búsqueda recursiva para '%s'", normalized)
                    return None

                wildcards = ["*"] * depth
                for exe_pattern in candidate_patterns:
                    pattern = os.path.join(root, *wildcards, exe_pattern)
                    matches = glob.glob(pattern)
                    if matches:
                        # Prioriza coincidencia exacta por nombre de ejecutable
                        exact = [m for m in matches if os.path.basename(m).lower() == f"{normalized}.exe"]
                        selected = exact[0] if exact else matches[0]
                        if exists_file(selected):
                            log.info(
                                "[APP_SEARCH] Encontrado en búsqueda automática (root=%s, depth=%d): %s",
                                root,
                                depth,
                                selected,
                            )
                            self._app_path_cache[normalized] = selected
                            return selected

        # 3) Último recurso: comando where de Windows
        remaining = time_left()
        if remaining <= 0:
            log.warning("[APP_SEARCH] Timeout agotado antes de ejecutar 'where' para '%s'", normalized)
            return None

        where_candidates = [f"{normalized}.exe", normalized]
        for where_target in where_candidates:
            if timed_out():
                log.warning("[APP_SEARCH] Timeout durante fallback 'where' para '%s'", normalized)
                return None

            try:
                log.debug("[APP_SEARCH] Ejecutando fallback: where %s", where_target)
                result = subprocess.run(
                    ["where", where_target],
                    capture_output=True,
                    text=True,
                    timeout=max(0.2, time_left()),
                    check=False,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        candidate = line.strip()
                        if exists_file(candidate):
                            log.info("[APP_SEARCH] Encontrado con 'where': %s", candidate)
                            self._app_path_cache[normalized] = candidate
                            return candidate
            except Exception as exc:
                log.debug("[APP_SEARCH] Falló 'where %s': %s", where_target, exc)

        log.warning("[APP_SEARCH] No se encontró ruta para '%s' en %.2fs", normalized, time.monotonic() - started_at)
        return None

    def _find_start_menu_app_id(self, app_name: str) -> str | None:
        """Intenta encontrar AppID de Windows Start Menu (UWP/Store apps)."""
        if not self.platform.startswith("win"):
            return None
        normalized = (app_name or "").strip().lower()
        if not normalized:
            return None
        cached = self._start_app_id_cache.get(normalized)
        if cached:
            return cached
        try:
            ps_cmd = (
                "$n='" + normalized.replace("'", "''") + "'; "
                "Get-StartApps | Where-Object { $_.Name -like \"*$n*\" -or $_.AppID -like \"*$n*\" } | "
                "Select-Object -First 1 -ExpandProperty AppID"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
            )
            app_id = (result.stdout or "").strip().splitlines()
            if app_id:
                selected = app_id[0].strip()
                self._start_app_id_cache[normalized] = selected
                return selected
        except Exception as exc:
            log.debug("[APP_SEARCH] No pude resolver AppID de Start Menu para '%s': %s", app_name, exc)
        return None
    
    def open_app(self, app_name: str) -> Dict[str, str]:
        """Intenta abrir una aplicación por nombre."""
        validation = sanitize_app_target(app_name)
        if not validation.allowed:
            return {"status": "error", "message": f"Bloqueado por seguridad: {validation.reason}"}
        app_name = validation.sanitized
        raw_target = (app_name or "").strip()
        normalized = self._normalize_app(app_name)
        log.info("[CMD_PARSE] open_app raw='%s' normalized='%s'", app_name, normalized)

        web_url = self._resolve_web_target_url(raw_target) or self._resolve_web_target_url(normalized)
        if web_url:
            log.info("[ACTIONS] %s detectado como sitio web. Abriendo en navegador...", raw_target or normalized)
            web_result = self.open_website(web_url)
            if web_result.get("status") == "ok":
                return {"status": "ok", "message": f"Abriendo {normalized} en navegador."}
            return {"status": "error", "message": f"No pude abrir {normalized} en navegador."}

        try:
            if self.platform.startswith("win"):
                # Aplicaciones del sistema de Windows (no necesitan ruta completa)
                system_apps = ["notepad", "calc", "mspaint", "explorer", "cmd", "msedge"]
                
                if normalized in system_apps:
                    # Usar start para aplicaciones del sistema
                    subprocess.Popen(f"start {normalized}", shell=True)
                    return {"status": "ok", "message": f"Abriendo {normalized}."}

                # 1) Buscar ruta completa para aplicaciones conocidas/no conocidas
                app_path = self._find_app_path(normalized)
                if app_path:
                    subprocess.Popen([app_path], shell=False)
                    return {"status": "ok", "message": f"Abriendo {normalized}."}

                # 2) Probar ejecutable en PATH
                for candidate in (normalized, f"{normalized}.exe"):
                    resolved = shutil.which(candidate)
                    if resolved:
                        subprocess.Popen([resolved], shell=False)
                        return {"status": "ok", "message": f"Abriendo {normalized}."}

                # 3) Probar Start Menu/UWP por AppID
                app_id = self._find_start_menu_app_id(normalized)
                if app_id:
                    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], shell=False)
                    return {"status": "ok", "message": f"Abriendo {normalized}."}

                # 4) Fallback web inteligente para entradas tipo sitio.
                web_url = self._resolve_web_target_url(normalized)
                if web_url:
                    log.info("[ACTIONS] Fallback web para '%s': %s", normalized, web_url)
                    web_result = self.open_website(web_url)
                    if web_result.get("status") == "ok":
                        return {"status": "ok", "message": f"Abriendo {normalized} en navegador."}
                    return {"status": "error", "message": f"No pude abrir {normalized} ni como app ni como web."}

                return {"status": "error", "message": f"No encontré aplicación instalada para '{normalized}'."}
                    
            elif self.platform == "darwin":
                subprocess.Popen(["open", "-a", normalized])
                return {"status": "ok", "message": f"Abriendo {normalized}."}
            else:
                subprocess.Popen([normalized])
                return {"status": "ok", "message": f"Abriendo {normalized}."}
                
        except Exception as exc:
            log.error(f"Error abriendo {normalized}: {exc}")
            web_url = self._resolve_web_target_url(normalized)
            if web_url:
                log.info("[ACTIONS] Error local; intentando abrir '%s' como web.", normalized)
                web_result = self.open_website(web_url)
                if web_result.get("status") == "ok":
                    return {
                        "status": "ok",
                        "message": f"No encontré app local para {normalized}. Lo abrí como sitio web.",
                    }
            return {"status": "error", "message": f"No pude abrir {normalized}: {exc}"}

    def close_app(self, process_name: str) -> Dict[str, str]:
        """Cierra procesos por nombre (graceful por defecto)."""
        return self.close_app_robust(process_name, force=False)

    def close_app_robust(self, process_name: str, force: bool = False) -> Dict[str, str]:
        """
        Cierre robusto con verificación post-acción.
        - graceful: WM_CLOSE/terminate/SIGTERM
        - force: taskkill /F / SIGKILL
        """
        if psutil is None:
            return {"status": "error", "message": "psutil no disponible para cierre fiable de procesos."}
        normalized = self._normalize_app(process_name).strip().lower().removesuffix(".exe")
        if not normalized:
            return {"status": "error", "message": "Necesito el nombre de la aplicación a cerrar."}
        candidates = self._find_processes_by_app_name(normalized)
        if not candidates:
            return {"status": "error", "message": f"No encontré procesos activos para '{normalized}'."}
        attempts = 0
        methods_used: List[str] = []
        pids = [p.pid for p in candidates]
        for _ in range(2):
            attempts += 1
            for proc in list(candidates):
                method = self._close_single_process(proc, normalized, force=force)
                methods_used.append(method)
            time.sleep(0.7)
            candidates = [p for p in candidates if p.is_running() and not self._is_zombie(p)]
            if not candidates:
                break
        # Último fallback forzado si no salió en modo graceful.
        if candidates and not force:
            for proc in list(candidates):
                method = self._close_single_process(proc, normalized, force=True)
                methods_used.append(method)
            time.sleep(0.7)
            candidates = [p for p in candidates if p.is_running() and not self._is_zombie(p)]
        ok = not candidates
        result_msg = (
            f"Cerré '{normalized}' correctamente (pids={pids})."
            if ok
            else f"No pude cerrar completamente '{normalized}'. PIDs aún activos: {[p.pid for p in candidates]}"
        )
        audit_event(
            "close_app",
            app=normalized,
            requested_force=bool(force),
            methods=",".join(methods_used[:12]),
            pids=pids,
            attempts=attempts,
            success=ok,
            remaining=[p.pid for p in candidates],
        )
        return {"status": "ok" if ok else "error", "message": result_msg}

    @staticmethod
    def _is_zombie(proc: "psutil.Process") -> bool:
        try:
            return proc.status() == psutil.STATUS_ZOMBIE
        except Exception:
            return False

    def _find_processes_by_app_name(self, app_name: str) -> List["psutil.Process"]:
        assert psutil is not None
        hits: List["psutil.Process"] = []
        current_pid = os.getpid()
        aliases = {app_name}
        for k, v in self.APP_ALIASES.items():
            if v == app_name:
                aliases.add(k.lower())
        aliases = {a.removesuffix(".exe") for a in aliases if a}
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                if int(proc.pid) == int(current_pid):
                    continue
                name = (proc.info.get("name") or "").lower().removesuffix(".exe")
                exe = os.path.basename((proc.info.get("exe") or "")).lower().removesuffix(".exe")
                cmdline = proc.info.get("cmdline") or []
                cmd_bins = {
                    os.path.basename(str(part)).lower().removesuffix(".exe")
                    for part in cmdline
                    if str(part).strip()
                }
                if any(alias and (alias == name or alias == exe or alias in cmd_bins) for alias in aliases):
                    hits.append(proc)
            except Exception:
                continue
        return hits

    def _close_single_process(self, proc: "psutil.Process", app_name: str, force: bool = False) -> str:
        assert psutil is not None
        if not proc.is_running():
            return "already_stopped"
        if self.platform.startswith("win"):
            if force:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/F"], check=False, capture_output=True)
                return "taskkill_force"
            # graceful Windows: WM_CLOSE a ventanas del PID; luego terminate.
            used_wm_close = False
            if win32gui is not None and win32process is not None and win32con is not None:
                def _enum_handler(hwnd: int, _param: object) -> None:
                    nonlocal used_wm_close
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        if pid == proc.pid and win32gui.IsWindowVisible(hwnd):
                            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                            used_wm_close = True
                    except Exception:
                        pass
                try:
                    win32gui.EnumWindows(_enum_handler, None)
                except Exception:
                    pass
            time.sleep(0.4)
            if proc.is_running():
                try:
                    proc.terminate()
                except Exception:
                    pass
            return "wm_close_then_terminate" if used_wm_close else "terminate"
        # Linux/macOS
        try:
            if force:
                proc.kill()
                return "sigkill"
            proc.send_signal(signal.SIGTERM)
            return "sigterm"
        except Exception:
            return "signal_failed"

    def shutdown(self, *, preconfirmed: bool = False) -> Dict[str, str]:
        """Apagado seguro del sistema (confirmado)."""
        if not preconfirmed and not self._confirm("¿Confirma apagar el equipo?"):
            return {"status": "cancel", "message": "Apagado cancelado."}

        try:
            if self.platform.startswith("win"):
                subprocess.Popen("shutdown /s /t 10", shell=True)
            else:
                subprocess.Popen(["shutdown", "-h", "+1"])
            return {"status": "ok", "message": "Apagado programado."}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def restart(self, *, preconfirmed: bool = False) -> Dict[str, str]:
        """Reinicio seguro del sistema (confirmado)."""
        if not preconfirmed and not self._confirm("¿Confirma reiniciar el equipo?"):
            return {"status": "cancel", "message": "Reinicio cancelado."}

        try:
            if self.platform.startswith("win"):
                subprocess.Popen("shutdown /r /t 10", shell=True)
            else:
                subprocess.Popen(["shutdown", "-r", "+1"])
            return {"status": "ok", "message": "Reinicio programado."}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def open_website(self, url: str) -> Dict[str, str]:
        """Abre una URL en navegador predeterminado."""
        validated = sanitize_user_input(url)
        if not validated.allowed:
            return {"status": "error", "message": f"Bloqueado por seguridad: {validated.reason}"}
        target = validated.sanitized
        try:
            webbrowser.open(target)
            return {"status": "ok", "message": f"Abriendo {target}"}
        except Exception as exc:
            log.error("Error abriendo sitio: %s", exc)
            return {"status": "error", "message": str(exc)}

    def parse_navigation_command(self, text: str) -> Tuple[str, str]:
        """Detecta comandos orientados a navegación en YouTube/Spotify/Steam."""
        normalized = (text or "").strip()
        if not normalized:
            return "", ""

        youtube_match = self.YOUTUBE_COMMAND_REGEX.search(normalized)
        if youtube_match:
            return "youtube_first", youtube_match.group(1).strip(" \t\n\r.,;:!?¡¿\"'")

        spotify_match = self.SPOTIFY_COMMAND_REGEX.search(normalized)
        if spotify_match:
            return "spotify_search", spotify_match.group(1).strip(" \t\n\r.,;:!?¡¿\"'")

        steam_match = self.STEAM_COMMAND_REGEX.search(normalized)
        if steam_match:
            return "steam_search", steam_match.group(1).strip(" \t\n\r.,;:!?¡¿\"'")

        return "", ""

    def extract_spotify_play_query(self, text: str) -> str:
        """
        Detecta intención de reproducir música aunque no diga "en spotify".
        Ej: "reproduce iron man 2 soundtrack"
        """
        normalized = (text or "").strip()
        if not normalized:
            return ""
        # Si menciona explícitamente otras plataformas, no forzamos Spotify.
        lowered = normalized.lower()
        if "youtube" in lowered or "steam" in lowered:
            return ""
        match = self.SPOTIFY_PLAY_FALLBACK_REGEX.search(normalized)
        if not match:
            return ""
        query = match.group(1).strip(" \t\n\r.,;:!?¡¿\"'")
        # Limpieza de palabras vacías comunes sin perder intención.
        query = re.sub(r"^canci\S*\s+de\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"^canci\S*\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"^(?:la|el|una|un)\s+canci.n\s+de\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"^(?:la|el|una|un)\s+canci.n\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"^(?:la|el|una|un)\s+(?:cancion|canción|tema|musica|música)\s+de\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"^(?:la|el|una|un)\s+(?:cancion|canción|tema|musica|música)\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\bcanci.n\b", " ", query, flags=re.IGNORECASE)
        query = re.sub(r"\b(cancion|canción|tema|musica|música)\b", " ", query, flags=re.IGNORECASE)
        query = re.sub(r"^de\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+", " ", query).strip()
        if len(query) < 2:
            return ""
        return query

    def _extract_first_youtube_video_url(self, query: str) -> str:
        """Busca un primer video probable de YouTube usando DuckDuckGo HTML."""
        q = (query or "").strip()
        if len(q) < 2:
            return ""

        try:
            query_url = f"https://duckduckgo.com/html/?q={quote_plus(f'site:youtube.com/watch {q}')}"
            request = Request(
                query_url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urlopen(request, timeout=6) as response:
                html = response.read().decode("utf-8", errors="ignore")

            for encoded_url in re.findall(r"uddg=([^\"&]+)", html):
                decoded = unquote(encoded_url)
                if "youtube.com/watch" in decoded:
                    return decoded

            direct = re.search(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{6,}", html)
            if direct:
                return direct.group(0)
        except Exception as exc:
            log.warning("No pude obtener primer video de YouTube para '%s': %s", q, exc)

        return ""

    @staticmethod
    def _spotify_track_query_url(query: str) -> str:
        safe = quote_plus((query or "").strip())
        return f"https://open.spotify.com/search/{safe}/tracks"

    @staticmethod
    def _steam_search_url(query: str) -> str:
        safe = quote_plus((query or "").strip())
        return f"https://store.steampowered.com/search/?term={safe}"

    @staticmethod
    def _youtube_search_url(query: str) -> str:
        safe = quote_plus((query or "").strip())
        return f"https://www.youtube.com/results?search_query={safe}"

    def execute_navigation_command(self, text: str) -> Optional[Dict[str, str]]:
        """
        Ejecuta comandos de navegación web específicos.
        Retorna None si el texto no corresponde a estos comandos.
        """
        command, query = self.parse_navigation_command(text)
        if not command:
            return None
        if self._contains_forbidden_display_command(text):
            return {"status": "error", "message": "Bloqueado por seguridad: no se permiten cambios de video/GPU."}
        if len(query) < 2:
            return {"status": "ok", "message": "Necesito un término de búsqueda más específico, señor."}

        try:
            if command == "youtube_first":
                # Regla de oro: solo abrir búsqueda/URL segura en navegador; jamás tocar parámetros de hardware.
                target_url = self._youtube_search_url(query)
                webbrowser.open(target_url)
                return {"status": "ok", "message": f"Abrí YouTube con resultados para {query}."}

            if command == "spotify_search":
                url = self._spotify_track_query_url(query)
                webbrowser.open(url)
                return {"status": "ok", "message": f"Abriendo Spotify para reproducir o elegir música de {query}."}

            if command == "steam_search":
                url = self._steam_search_url(query)
                webbrowser.open(url)
                return {"status": "ok", "message": f"Abriendo Steam con resultados de juegos para {query}."}
        except Exception as exc:
            log.error("Error ejecutando comando de navegación '%s': %s", command, exc)
            return {"status": "error", "message": "No pude completar esa navegación en este momento."}

        return None

    def _set_volume_windows_keybd_approx(self, target_percent: int) -> Dict[str, str]:
        """Fallback si pycaw/comtypes falla: bajar y subir con teclas multimedia."""
        safe = max(0, min(100, int(target_percent)))
        VK_VOLUME_DOWN = 0xAE
        VK_VOLUME_UP = 0xAF
        _win_keybd_volume_pulse(VK_VOLUME_DOWN, 55)
        time.sleep(0.08)
        steps_up = max(0, min(55, int(round(safe / 2.0))))
        _win_keybd_volume_pulse(VK_VOLUME_UP, steps_up)
        return {
            "status": "ok",
            "message": (
                f"Volumen aproximado a ~{safe}% (teclas multimedia). "
                "Para ajuste exacto instale dependencias: pip install comtypes pycaw"
            ),
        }

    def set_volume(self, percent: int) -> Dict[str, str]:
        """Ajusta volumen del sistema (multiplataforma con fallback)."""
        safe_percent = max(0, min(100, int(percent)))
        try:
            if self.platform.startswith("win") and AudioUtilities is not None:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(safe_percent / 100, None)
                return {"status": "ok", "message": f"Volumen ajustado a {safe_percent}%"}

            if self.platform.startswith("win"):
                log.warning("Audio API no disponible; usando teclas de volumen")
                return self._set_volume_windows_keybd_approx(safe_percent)

            if self.platform == "linux":
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{safe_percent}%"], check=False)
                return {"status": "ok", "message": f"Volumen ajustado a {safe_percent}%"}

            return {"status": "error", "message": "Control de volumen no disponible en este entorno"}
        except Exception as exc:
            log.warning("set_volume pycaw falló (%s); intentando teclas", exc)
            if self.platform.startswith("win"):
                return self._set_volume_windows_keybd_approx(safe_percent)
            return {"status": "error", "message": str(exc)}

    def get_volume(self) -> Dict[str, str]:
        """Obtiene volumen maestro aproximado en porcentaje."""
        try:
            if self.platform.startswith("win") and AudioUtilities is not None:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                current = int(round(volume.GetMasterVolumeLevelScalar() * 100))
                muted = bool(volume.GetMute())
                return {"status": "ok", "volume": str(current), "muted": str(muted).lower()}
            return {"status": "error", "message": "Lectura de volumen no disponible en este entorno"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _adjust_volume_windows_keybd(self, delta: int) -> Dict[str, str]:
        """Sube/baja con teclas VK_VOLUME_UP/DOWN cuando no hay lectura de nivel."""
        d = int(delta)
        if d == 0:
            return {"status": "ok", "message": "Sin cambio de volumen."}
        vk = 0xAF if d > 0 else 0xAE
        steps = max(1, min(28, abs(d) // 2 + 1))
        _win_keybd_volume_pulse(vk, steps)
        return {"status": "ok", "message": f"Volumen ajustado en ~{steps} pasos ({'+' if d > 0 else '-'})."}

    def adjust_volume(self, delta: int) -> Dict[str, str]:
        """Sube/baja volumen relativo al valor actual."""
        current = self.get_volume()
        if current.get("status") != "ok":
            if self.platform.startswith("win"):
                return self._adjust_volume_windows_keybd(int(delta))
            return current
        try:
            current_value = int(current.get("volume", "0"))
        except ValueError:
            current_value = 0
        result = self.set_volume(current_value + int(delta))
        if result.get("status") == "ok":
            return result
        if self.platform.startswith("win"):
            return self._adjust_volume_windows_keybd(int(delta))
        return result

    def set_mute(self, muted: bool) -> Dict[str, str]:
        """Activa/desactiva mute del sistema."""
        try:
            if self.platform.startswith("win") and AudioUtilities is not None:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMute(1 if muted else 0, None)
                if muted:
                    return {"status": "ok", "message": "Audio silenciado."}
                return {"status": "ok", "message": "Audio reactivado."}
            if self.platform.startswith("win"):
                if muted:
                    _win_keybd_volume_pulse(0xAD, 1)
                    return {"status": "ok", "message": "Pulsé la tecla silenciar del sistema (alterna mute)."}
                return {
                    "status": "error",
                    "message": "Para desmutear con precisión hace falta la API de audio (pip install comtypes pycaw).",
                }
            return {"status": "error", "message": "Mute no disponible en este entorno"}
        except Exception as exc:
            if self.platform.startswith("win") and muted:
                try:
                    _win_keybd_volume_pulse(0xAD, 1)
                    return {"status": "ok", "message": "Pulsé silenciar (fallback tras error de API)."}
                except Exception:
                    pass
            return {"status": "error", "message": str(exc)}

    def set_brightness(self, percent: int) -> Dict[str, str]:
        """Ajusta brillo de pantalla usando screen-brightness-control."""
        safe_percent = max(10, min(100, int(percent)))
        if sbc is None:
            return {"status": "error", "message": "Módulo de brillo no disponible"}
        try:
            sbc.set_brightness(safe_percent)
            return {"status": "ok", "message": f"Brillo ajustado a {safe_percent}%"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def get_brightness(self) -> Dict[str, str]:
        """Obtiene brillo actual aproximado."""
        if sbc is None:
            return {"status": "error", "message": "Módulo de brillo no disponible"}
        try:
            values = sbc.get_brightness()
            if isinstance(values, list) and values:
                current = int(round(float(values[0])))
            else:
                current = int(round(float(values)))
            return {"status": "ok", "brightness": str(current)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def adjust_brightness(self, delta: int) -> Dict[str, str]:
        """Sube/baja brillo relativo al valor actual."""
        current = self.get_brightness()
        if current.get("status") != "ok":
            return current
        try:
            current_value = int(current.get("brightness", "50"))
        except ValueError:
            current_value = 50
        return self.set_brightness(current_value + int(delta))

    def list_windows(self) -> Dict[str, List[str] | str]:
        """Lista ventanas visibles del sistema."""
        if gw is None:
            return {"status": "error", "message": "pygetwindow no disponible", "windows": []}
        try:
            titles = [t.title for t in gw.getAllWindows() if t.title.strip()]
            return {"status": "ok", "message": f"{len(titles)} ventanas detectadas", "windows": titles}
        except Exception as exc:
            return {"status": "error", "message": str(exc), "windows": []}

    def plan_directory_organization(self, target_directory: str) -> Dict[str, object]:
        """Genera un plan de organización por extensiones sin mover archivos."""
        directory = os.path.abspath(os.path.expanduser(target_directory.strip() or "."))
        if not os.path.isdir(directory):
            return {"status": "error", "message": f"La carpeta no existe: {directory}"}

        moves: List[Dict[str, str]] = []
        skipped = 0
        for entry in os.scandir(directory):
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            bucket = self._resolve_organizer_bucket(ext)
            if not bucket:
                skipped += 1
                continue
            destination_dir = os.path.join(directory, bucket)
            destination_path = os.path.join(destination_dir, entry.name)
            if os.path.abspath(entry.path) == os.path.abspath(destination_path):
                continue
            moves.append(
                {
                    "source": entry.path,
                    "destination_dir": destination_dir,
                    "destination": destination_path,
                    "bucket": bucket,
                }
            )

        if not moves:
            if skipped > 0:
                return {
                    "status": "ok",
                    "message": (
                        "No encontré archivos con extensiones clasificables para mover. "
                        f"Archivos omitidos: {skipped}."
                    ),
                    "moves": [],
                    "target_directory": directory,
                }
            return {"status": "ok", "message": "No hay archivos para organizar en esa carpeta.", "moves": [], "target_directory": directory}

        summary_parts: List[str] = []
        by_bucket: Dict[str, int] = {}
        for move in moves:
            bucket = str(move["bucket"])
            by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
        for bucket_name, count in sorted(by_bucket.items()):
            summary_parts.append(f"{count} {bucket_name.lower()}")

        message = (
            f"Plan listo para {directory}: mover {len(moves)} archivos "
            f"({', '.join(summary_parts)})."
        )
        return {"status": "ok", "message": message, "moves": moves, "target_directory": directory}

    def apply_directory_organization_plan(self, plan: Dict[str, object]) -> Dict[str, object]:
        """Aplica un plan previamente generado por plan_directory_organization."""
        moves = plan.get("moves", [])
        if not isinstance(moves, list) or not moves:
            return {"status": "ok", "message": "No hay movimientos pendientes por aplicar.", "moved": 0}

        moved = 0
        failed: List[str] = []
        for move in moves:
            if not isinstance(move, dict):
                continue
            source = str(move.get("source", "")).strip()
            destination = str(move.get("destination", "")).strip()
            destination_dir = str(move.get("destination_dir", "")).strip()
            if not source or not destination or not destination_dir:
                continue
            try:
                os.makedirs(destination_dir, exist_ok=True)
                shutil.move(source, destination)
                self.undo_manager.record_move(source, destination)
                moved += 1
            except Exception as exc:
                failed.append(f"{os.path.basename(source)}: {exc}")

        if failed:
            return {
                "status": "partial" if moved else "error",
                "message": f"Moví {moved} archivo(s), pero hubo {len(failed)} error(es).",
                "moved": moved,
                "errors": failed,
            }
        return {"status": "ok", "message": f"Organización completada. Movidos: {moved} archivo(s).", "moved": moved}

    def _resolve_organizer_bucket(self, ext: str) -> Optional[str]:
        if not ext:
            return None
        lowered = ext.lower()
        for bucket, extensions in self.FILE_ORGANIZER_BUCKETS.items():
            if lowered in extensions:
                return bucket
        return None

    def undo_last_action(self) -> Dict[str, str]:
        return self.undo_manager.undo_last()

    def list_usb_devices(self) -> Dict[str, List[str] | str]:
        """Lista dispositivos USB conectados (mejor esfuerzo por plataforma)."""
        try:
            if self.platform.startswith("win"):
                ps_cmd = (
                    "Get-PnpDevice -PresentOnly | "
                    "Where-Object { $_.InstanceId -like 'USB*' -or $_.Class -eq 'USB' } | "
                    "Select-Object -ExpandProperty FriendlyName"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                dedup = []
                seen = set()
                for item in lines:
                    if item.lower() in seen:
                        continue
                    seen.add(item.lower())
                    dedup.append(item)
                if dedup:
                    return {"status": "ok", "message": f"{len(dedup)} dispositivos USB detectados", "devices": dedup}
                return {"status": "ok", "message": "No detecté dispositivos USB listables en este momento", "devices": []}

            # Linux/macOS fallback
            result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=8, check=False)
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            return {"status": "ok", "message": f"{len(lines)} dispositivos USB detectados", "devices": lines}
        except Exception as exc:
            return {"status": "error", "message": str(exc), "devices": []}

    def focus_window(self, title_contains: str) -> Dict[str, str]:
        """Intenta enfocar ventana por coincidencia parcial de título."""
        if gw is None:
            return {"status": "error", "message": "pygetwindow no disponible"}
        try:
            target = title_contains.lower().strip()
            for window in gw.getAllWindows():
                if target in window.title.lower():
                    window.activate()
                    return {"status": "ok", "message": f"Ventana enfocada: {window.title}"}
            return {"status": "error", "message": "No encontré una ventana coincidente"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
