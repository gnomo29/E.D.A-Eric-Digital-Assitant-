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
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, unquote
from urllib.request import Request, urlopen

from . import config
from .logger import get_logger
from .utils import detect_platform

log = get_logger("actions")

try:
    import pygetwindow as gw
except Exception:
    gw = None

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

    def __init__(self, confirm_callback: Callable[[str], bool] | None = None) -> None:
        self.confirm_callback = confirm_callback
        self.platform = detect_platform()
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
        normalized = self._normalize_app(app_name)
        log.info("[CMD_PARSE] open_app raw='%s' normalized='%s'", app_name, normalized)

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

                # 4) Último recurso: start nativo de Windows
                subprocess.Popen(f"start {normalized}", shell=True)
                return {"status": "ok", "message": f"Intentando abrir {normalized}."}
                    
            elif self.platform == "darwin":
                subprocess.Popen(["open", "-a", normalized])
                return {"status": "ok", "message": f"Abriendo {normalized}."}
            else:
                subprocess.Popen([normalized])
                return {"status": "ok", "message": f"Abriendo {normalized}."}
                
        except Exception as exc:
            log.error(f"Error abriendo {normalized}: {exc}")
            return {"status": "error", "message": f"No pude abrir {normalized}: {exc}"}

    def close_app(self, process_name: str) -> Dict[str, str]:
        """Cierra procesos por nombre, con confirmación."""
        normalized = self._normalize_app(process_name)
        if not self._confirm(f"¿Confirma cerrar {normalized}?"):
            return {"status": "cancel", "message": "Operación cancelada."}

        try:
            if self.platform.startswith("win"):
                subprocess.run(f"taskkill /IM {normalized}.exe /F", shell=True, check=False)
                subprocess.run(f"taskkill /IM {normalized} /F", shell=True, check=False)
            else:
                subprocess.run(["pkill", "-f", normalized], check=False)
            return {"status": "ok", "message": f"Intenté cerrar {normalized}."}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def shutdown(self) -> Dict[str, str]:
        """Apagado seguro del sistema (confirmado)."""
        if not self._confirm("¿Confirma apagar el equipo?"):
            return {"status": "cancel", "message": "Apagado cancelado."}

        try:
            if self.platform.startswith("win"):
                subprocess.Popen("shutdown /s /t 10", shell=True)
            else:
                subprocess.Popen(["shutdown", "-h", "+1"])
            return {"status": "ok", "message": "Apagado programado."}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def restart(self) -> Dict[str, str]:
        """Reinicio seguro del sistema (confirmado)."""
        if not self._confirm("¿Confirma reiniciar el equipo?"):
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
        try:
            webbrowser.open(url)
            return {"status": "ok", "message": f"Abriendo {url}"}
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
        if len(query) < 2:
            return {"status": "ok", "message": "Necesito un término de búsqueda más específico, señor."}

        try:
            if command == "youtube_first":
                first_video_url = self._extract_first_youtube_video_url(query)
                target_url = first_video_url or self._youtube_search_url(query)
                webbrowser.open(target_url)
                if first_video_url:
                    return {"status": "ok", "message": f"Abriendo el primer video encontrado en YouTube sobre {query}."}
                return {
                    "status": "ok",
                    "message": (
                        f"No pude confirmar el primer video automáticamente, pero abrí YouTube con la búsqueda de {query}."
                    ),
                }

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
