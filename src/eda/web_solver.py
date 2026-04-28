"""Resolución técnica avanzada con búsqueda, scraping, síntesis y AUTO_LEARN."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import re
import subprocess
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from . import config
from .audit_log import audit_event
from .core import EDACore
from . import remote_llm
from . import web_execution_gate
from .logger import get_logger
from .memory import MemoryManager
from .utils import build_http_session, now_str
from .web_search import WebSearch

log = get_logger("web_solver")

try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None


class WebSolver:
    """Módulo crítico de investigación y propuesta de soluciones."""

    # Imports permitidos en funciones auto-aprendidas (sandbox ligero vía AST).
    SKILL_IMPORT_ALLOWED = frozenset(
        {
            "eda",
            "json",
            "re",
            "typing",
            "datetime",
            "pathlib",
            "collections",
            "math",
            "itertools",
            "functools",
            "unicodedata",
            "time",
            "uuid",
            "hashlib",
            "enum",
            "dataclasses",
        }
    )

    FORBIDDEN_CODE_MARKERS = (
        "shutil.rmtree",
        "os.remove(",
        "os.rmdir(",
        "winreg",
        "reg delete",
        "format c:",
        "powershell -command remove-item",
        "subprocess.run(['del'",
        "subprocess.run([\"del\"",
        "requests.get('http://",
        "requests.get(\"http://",
    )

    def __init__(self, core: EDACore | None = None, memory: MemoryManager | None = None) -> None:
        self.core = core or EDACore()
        self.memory = memory or MemoryManager()
        self.web_search = WebSearch()
        self.headers = {"User-Agent": config.USER_AGENT}
        self.http = build_http_session()
        self._scrape_times: deque[float] = deque(maxlen=64)
        self._last_scrape_mono: float = 0.0
        self.sources_priority = [
            "site:stackoverflow.com",
            "site:github.com",
            "site:forum.arduino.cc",
            "site:learn.microsoft.com",
            "site:docs.python.org",
        ]

    def _cache_key(self, question: str) -> str:
        return hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()

    def _is_cache_valid(self, payload: Dict[str, str]) -> bool:
        created_at = payload.get("created_at")
        if not created_at:
            return False
        try:
            ts = datetime.fromisoformat(created_at)
            ttl = timedelta(hours=config.WEB_SOLVER_CACHE_TTL_HOURS)
            return datetime.now() - ts <= ttl
        except Exception:
            return False

    def detect_problem_type(self, question: str) -> str:
        """Detecta tipo de consulta para priorizar fuentes y formato de salida."""
        q = question.lower()
        if any(k in q for k in ["arduino", "sensor", "led", "millis", "sketch", ".ino"]):
            return "arduino"
        if any(k in q for k in ["windows", "powershell", "cmd", "registro", "driver"]):
            return "windows"
        if any(k in q for k in ["python", "java", "javascript", "error", "bug", "api", "sql"]):
            return "programming"
        return "general"

    def intelligent_search(self, question: str, max_results: int = config.WEB_SOLVER_MAX_RESULTS) -> List[Dict[str, str]]:
        """Busca resultados relevantes en múltiples fuentes técnicas."""
        problem_type = self.detect_problem_type(question)
        extra = ""
        if problem_type == "arduino":
            extra = "site:arduino.cc OR site:forum.arduino.cc OR site:stackoverflow.com"
        elif problem_type == "windows":
            extra = "site:learn.microsoft.com OR site:superuser.com"
        elif problem_type == "programming":
            extra = "site:stackoverflow.com OR site:github.com"

        query = f"{question} {extra}"

        if DDGS is not None:
            try:
                with DDGS() as ddgs:
                    data = list(ddgs.text(query, max_results=max_results))
                return [
                    {
                        "title": item.get("title", "Sin título"),
                        "url": item.get("href", ""),
                        "snippet": item.get("body", ""),
                    }
                    for item in data
                ]
            except Exception as exc:
                log.warning("DDGS no disponible en intelligent_search: %s", exc)

        return self.web_search.search(query, max_results=max_results)

    def _scrape_rate_allow(self) -> bool:
        """Limita ráfagas de scraping (HTTP) para no martillar sitios."""
        now = time.monotonic()
        min_gap = float(getattr(config, "WEB_SOLVER_SCRAPE_MIN_INTERVAL_SEC", 0.45))
        if self._last_scrape_mono and (now - self._last_scrape_mono) < min_gap:
            log.debug("[SCRAPE] throttled (interval)")
            return False
        window = 60.0
        max_per = max(1, int(getattr(config, "WEB_SOLVER_SCRAPE_MAX_PER_MINUTE", 14)))
        while self._scrape_times and (now - self._scrape_times[0]) > window:
            self._scrape_times.popleft()
        if len(self._scrape_times) >= max_per:
            log.warning("[SCRAPE] límite por minuto alcanzado (%s)", max_per)
            return False
        self._scrape_times.append(now)
        self._last_scrape_mono = now
        return True

    def scrape_page(self, url: str) -> str:
        """Extrae texto principal de una página web."""
        if not url.startswith("http"):
            return ""
        if not self._scrape_rate_allow():
            return ""
        try:
            response = self.http.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for bad in soup(["script", "style", "noscript", "header", "footer", "svg"]):
                bad.extract()
            text = " ".join(soup.get_text(separator=" ").split())
            out = text[: config.WEB_SOLVER_SCRAPE_LIMIT]
            audit_event("web_scrape", url=url[:500], chars=len(out))
            return out
        except Exception as exc:
            log.warning("No se pudo scrapear %s: %s", url, exc)
            audit_event("web_scrape_error", url=url[:500], error=str(exc)[:200])
            return ""

    def _validate_skill_imports(self, code: str) -> bool:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = (alias.name or "").split(".")[0]
                    if root and root not in self.SKILL_IMPORT_ALLOWED:
                        log.warning("[AUTO_LEARN] import no permitido: %s", root)
                        return False
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                root = mod.split(".")[0] if mod else ""
                if root and root not in self.SKILL_IMPORT_ALLOWED:
                    log.warning("[AUTO_LEARN] import from no permitido: %s", root)
                    return False
        return True

    def _extract_code_block(self, text: str) -> str:
        match = re.search(r"```[a-zA-Z0-9_]*\n([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _extract_code_candidates(self, text: str) -> List[str]:
        blocks = re.findall(r"```(?:python|py)?\n([\s\S]*?)```", text or "", flags=re.IGNORECASE)
        candidates = [b.strip() for b in blocks if b.strip()]
        if not candidates:
            one_liners = re.findall(r"def\s+[a-zA-Z_][a-zA-Z0-9_]*\([\s\S]{0,500}", text or "")
            candidates.extend(one_liners[:2])
        return candidates

    def _default_template(self, problem_type: str) -> str:
        if problem_type == "arduino":
            return (
                "// Blink no bloqueante con millis()\n"
                "const int LED_PIN = 13;\n"
                "unsigned long previousMillis = 0;\n"
                "const unsigned long interval = 500;\n"
                "bool ledState = false;\n\n"
                "void setup() {\n"
                "  pinMode(LED_PIN, OUTPUT);\n"
                "}\n\n"
                "void loop() {\n"
                "  const unsigned long currentMillis = millis();\n"
                "  if (currentMillis - previousMillis >= interval) {\n"
                "    previousMillis = currentMillis;\n"
                "    ledState = !ledState;\n"
                "    digitalWrite(LED_PIN, ledState);\n"
                "  }\n"
                "}\n"
            )
        return (
            "def main() -> None:\n"
            "    \"\"\"Plantilla base segura.\"\"\"\n"
            "    print(\"Implementa aquí la solución\")\n\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n"
        )

    @staticmethod
    def _sanitize_for_safe_code_literal(text: str) -> str:
        """Evita falsos positivos en _is_safe_python_code por texto citado de la web."""
        t = text or ""
        for bad in (
            "winreg",
            "shutil.rmtree",
            "os.remove(",
            "os.rmdir(",
            "format c:",
            "powershell -command remove-item",
        ):
            t = t.replace(bad, "[omitido]")
        return t

    def _build_capability_template(self, task_text: str, function_name: str) -> str:
        """Plantillas funcionales para habilidades comunes solicitadas por el usuario."""
        normalized = (task_text or "").lower()

        if "bluetooth" in normalized:
            return (
                f"def {function_name}(command_text: str = \"\") -> dict:\n"
                "    \"\"\"Escanea dispositivos Bluetooth cercanos.\"\"\"\n"
                "    try:\n"
                "        from eda.bluetooth_manager import BluetoothManager\n"
                "        bt = BluetoothManager()\n"
                "        devices = bt.scan_devices(timeout=6)\n"
                "        if not devices:\n"
                "            return {\n"
                "                'status': 'ok',\n"
                "                'message': 'No detecté dispositivos Bluetooth en este momento.',\n"
                "            }\n"
                "        names = [d.get('name', 'Desconocido') for d in devices[:5]]\n"
                "        joined = ', '.join(names)\n"
                "        return {\n"
                "            'status': 'ok',\n"
                "            'message': f'Detecté dispositivos Bluetooth: {joined}.',\n"
                "        }\n"
                "    except Exception as exc:\n"
                "        return {'status': 'error', 'message': f'Error Bluetooth: {exc}'}\n"
            )

        if "camara" in normalized or "cámara" in normalized:
            return (
                f"def {function_name}(command_text: str = \"\") -> dict:\n"
                "    \"\"\"Abre la cámara del sistema (Windows).\"\"\"\n"
                "    try:\n"
                "        import os\n"
                "        import subprocess\n"
                "        if os.name == 'nt':\n"
                "            subprocess.Popen('start microsoft.windows.camera:', shell=True)\n"
                "            return {'status': 'ok', 'message': 'Abriendo la cámara del sistema.'}\n"
                "        return {'status': 'error', 'message': 'Apertura de cámara no implementada para este sistema.'}\n"
                "    except Exception as exc:\n"
                "        return {'status': 'error', 'message': f'No pude abrir la cámara: {exc}'}\n"
            )

        if "usb" in normalized:
            return (
                f"def {function_name}(command_text: str = \"\") -> dict:\n"
                "    \"\"\"Lista dispositivos USB conectados usando ActionController.\"\"\"\n"
                "    try:\n"
                "        from eda.actions import ActionController\n"
                "        ac = ActionController()\n"
                "        result = ac.list_usb_devices()\n"
                "        if result.get('status') != 'ok':\n"
                "            return {'status': 'error', 'message': result.get('message', 'Error USB')}\n"
                "        devices = result.get('devices', [])\n"
                "        if not devices:\n"
                "            return {'status': 'ok', 'message': 'No se detectaron USB conectados.'}\n"
                "        preview = ', '.join(str(d) for d in devices[:6])\n"
                "        return {'status': 'ok', 'message': f'USB detectados: {preview}'}\n"
                "    except Exception as exc:\n"
                "        return {'status': 'error', 'message': f'No pude listar USB: {exc}'}\n"
            )

        return ""

    def _is_placeholder_autolearn(self, code: str) -> bool:
        """Detecta código genérico sin implementación real."""
        normalized = (code or "").lower()
        placeholder_markers = (
            "acción aprendida ejecutada para",
            "accion aprendida ejecutada para",
            "implementa aquí la solución",
        )
        return any(marker in normalized for marker in placeholder_markers)

    def _build_function_name(self, task_text: str) -> str:
        words = re.findall(r"[a-zA-Z0-9áéíóúñ]+", (task_text or "").lower())
        base = "_".join(words[:4]) or "new_skill"
        base = re.sub(r"[^a-z0-9_]", "", base)
        if not base:
            base = "new_skill"
        if base[0].isdigit():
            base = f"skill_{base}"
        return f"learned_{base}"

    def _validate_python(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError as exc:
            log.warning("[CODE_GEN] AST inválido: %s", exc)
            return False

    def _is_safe_python_code(self, code: str) -> bool:
        normalized = (code or "").lower()
        return not any(marker in normalized for marker in self.FORBIDDEN_CODE_MARKERS)

    def _identify_libraries(self, code: str) -> List[str]:
        libs = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        libs.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        libs.add(node.module.split(".")[0])
        except Exception:
            pass
        return sorted(libs)

    def choose_target_module(self, task_text: str, intent: str = "") -> str:
        combined = f"{intent} {task_text}".lower()
        if intent in {"open_app", "close_app", "volume", "brightness"}:
            return "eda/actions.py"
        if any(k in combined for k in ["abrir", "cerrar", "sistema", "app", "volumen", "brillo", "archivo"]):
            return "eda/actions.py"
        if intent == "question":
            return "eda/core.py"
        return "eda/skills_auto.py"

    def search_learning_resources(self, task_text: str, max_results: int = 3) -> List[Dict[str, str]]:
        """
        Reúne enlaces/snippets para auto-aprendizaje.
        Prioriza DuckDuckGo / intelligent_search (más estable que el HTML de Google).
        """
        task = (task_text or "").strip()
        resources: List[Dict[str, str]] = []
        seen_urls: set[str] = set()

        def add_items(items: List[Dict[str, str]]) -> None:
            for item in items:
                url = (item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                resources.append(item)

        queries = [
            f"{task} python ejemplo español",
            f"{task} tutorial python",
            f"how to {task} in python",
            f"{task} site:stackoverflow.com",
        ]
        for query in queries:
            if len(resources) >= 8:
                break
            try:
                add_items(self.intelligent_search(query, max_results=max_results))
            except Exception as exc:
                log.warning("[AUTO_LEARN] intelligent_search falló (%s): %s", query[:60], exc)
            try:
                add_items(self.web_search.search(query, max_results=max_results))
            except Exception as exc:
                log.warning("[AUTO_LEARN] web_search.search falló (%s): %s", query[:60], exc)
            try:
                add_items(self.web_search.search_google_snippets(query, max_results=max_results))
            except Exception as exc:
                log.debug("[AUTO_LEARN] google snippets: %s", exc)

        return resources[:8]

    def _format_web_hints(self, task: str, resources: List[Dict[str, str]]) -> str:
        parts: List[str] = []
        for i, item in enumerate(resources[:6]):
            title = (item.get("title") or "").strip()[:220]
            snip = (item.get("snippet") or "").strip()[:450]
            url = (item.get("url") or "").strip()
            block = "\n".join(x for x in (f"{i + 1}. {title}".strip(), snip, url) if x)
            if block.strip():
                parts.append(block)
        text = "\n\n".join(parts).strip()
        if not text:
            return ""
        intro = f"Pistas reunidas en la web para: {task.strip()[:200]}\n\n"
        return (intro + text)[:4200]

    def _build_snippet_fallback_skill(self, function_name: str, task: str, resources: List[Dict[str, str]]) -> str:
        """Función Python real que solo devuelve texto (sin acciones destructivas)."""
        hints = self._format_web_hints(task, resources)
        if not hints:
            return ""
        msg = self._sanitize_for_safe_code_literal(hints[:4500])
        safe_repr = repr(msg)
        return (
            f"def {function_name}(command_text: str = \"\") -> dict:\n"
            '    """Resumen de fuentes web (modo seguro; no ejecuta pasos del usuario)."""\n'
            f"    return {{'status': 'ok', 'message': {safe_repr}}}\n"
        )

    def _build_minimal_guidance_skill(self, function_name: str, task: str) -> str:
        """Último recurso cuando no hay resultados de búsqueda ni código LLM válido."""
        short = (task or "").replace('"', "'").strip()[:500]
        tip = (
            "No encontré fuentes web fiables automáticamente. "
            "Probá reformular con pasos concretos, o enseñámelo con una regla del tipo "
            "«Quiero que cada vez que diga … hagas …». "
            f"Tarea registrada: {short}"
        )
        return (
            f"def {function_name}(command_text: str = \"\") -> dict:\n"
            '    """Guía mínima cuando el auto-aprendizaje no obtuvo contexto externo."""\n'
            f"    return {{'status': 'ok', 'message': {repr(tip)}}}\n"
        )

    def generate_autolearn_payload(self, task_text: str, intent: str = "", planner_notes: str = "") -> Dict[str, Any]:
        """Construye propuesta de código segura para AUTO_LEARN."""
        clean_task = (task_text or "").strip()
        if len(clean_task) < 3:
            return {"status": "error", "message": "Tarea demasiado corta para auto-aprendizaje."}

        target_module = self.choose_target_module(clean_task, intent=intent)
        function_name = self._build_function_name(clean_task)

        # Atajo funcional para capacidades comunes solicitadas frecuentemente.
        capability_template = self._build_capability_template(clean_task, function_name)
        if capability_template:
            libraries = self._identify_libraries(capability_template)
            review_notes = ""
            if remote_llm.use_remote_for_code_review() and remote_llm.is_remote_fully_configured():
                review_notes = remote_llm.review_python_code(clean_task, capability_template)
                if review_notes:
                    audit_event("remote_llm_code_review", task=clean_task[:200], chars=len(review_notes))
            return {
                "status": "ok",
                "task": clean_task,
                "module": target_module,
                "function": function_name,
                "code": capability_template,
                "libraries": libraries,
                "sources": [],
                "review_notes": review_notes[:4000] if review_notes else "",
            }

        log.info("[AUTO_LEARN] Investigando tarea: %s", clean_task)
        resources = self.search_learning_resources(clean_task)

        context_chunks = []
        for item in resources[:3]:
            url = item.get("url", "")
            snippet = item.get("snippet", "")
            text = f"Snippet: {snippet}"
            page_code = ""
            if url:
                page_text = self.scrape_page(url)
                code_candidates = self._extract_code_candidates(page_text)
                if code_candidates:
                    page_code = code_candidates[0][:1200]
            context_chunks.append(f"{text}\nCódigo encontrado: {page_code}")

        joined_context = "\n\n".join(context_chunks)[:5000]
        notes = (planner_notes or "").strip()
        if notes:
            joined_context = (notes + "\n\n" + joined_context).strip()[:5000]
        ctx_note = (
            "El contexto de búsqueda puede estar vacío; aun así genera una función mínima y segura "
            "que explique qué información falta o devuelva pasos genéricos sin ejecutar comandos peligrosos."
            if len(joined_context.strip()) < 40
            else "Usa el contexto para implementar o acotar la solución."
        )
        prompt = (
            "Genera SOLO código Python válido dentro de un único bloque ```python. "
            "Debe ser una función completa y segura para E.D.A., sin borrar archivos, sin tocar registro de Windows, "
            "sin descargar ejecutables y sin pedir datos sensibles. "
            f"Nombre obligatorio de función: {function_name}. "
            "Firma obligatoria: def " + function_name + "(command_text: str = \"\") -> dict: \n"
            "Debe retornar {'status': 'ok|error', 'message': '...'} y manejar excepciones. "
            "Usa comentarios breves en español.\n\n"
            f"Tarea: {clean_task}\n\n"
            f"{ctx_note}\n\n"
            f"Contexto de referencia:\n{joined_context}"
        )

        def _pick_safe_fallback() -> str:
            fb = self._build_snippet_fallback_skill(function_name, clean_task, resources)
            return fb if fb.strip() else self._build_minimal_guidance_skill(function_name, clean_task)

        log.info("[CODE_GEN] Generando función %s para tarea '%s'", function_name, clean_task)
        generated_code = ""
        if remote_llm.remote_deep_research_pipeline_available():
            llm_answer = remote_llm.try_completion_single_prompt(prompt, purpose="autolearn_codegen_secure")
            generated_code = self._extract_code_block(llm_answer)
            if generated_code.strip():
                web_execution_gate.arm_after_external_research()
        elif self.core.is_ollama_alive():
            llm_answer = self.core.ask(prompt)
            generated_code = self._extract_code_block(llm_answer)
        else:
            log.warning("[CODE_GEN] Ollama no disponible; se usará resumen por fuentes web.")

        if (not generated_code.strip()) or (not generated_code.startswith("def ")) or (
            function_name not in generated_code
        ):
            generated_code = _pick_safe_fallback()

        if self._is_placeholder_autolearn(generated_code):
            generated_code = _pick_safe_fallback()

        if self._is_placeholder_autolearn(generated_code):
            return {
                "status": "error",
                "message": "No pude reunir contexto útil ni generar una propuesta segura; reformulá la tarea o revisá internet/Ollama.",
            }

        if not self._is_safe_python_code(generated_code):
            generated_code = _pick_safe_fallback()
            if not self._is_safe_python_code(generated_code):
                return {"status": "error", "message": "Código generado rechazado por política de seguridad."}

        if not self._validate_skill_imports(generated_code):
            generated_code = _pick_safe_fallback()
            if not self._validate_skill_imports(generated_code):
                return {"status": "error", "message": "Imports no permitidos en el código generado."}

        if not self._validate_python(generated_code):
            generated_code = _pick_safe_fallback()
            if not self._validate_python(generated_code):
                return {"status": "error", "message": "No se pudo generar código sintácticamente válido."}

        libraries = self._identify_libraries(generated_code)

        review_notes = ""
        if remote_llm.use_remote_for_code_review() and remote_llm.is_remote_fully_configured():
            review_notes = remote_llm.review_python_code(clean_task, generated_code)
            if review_notes:
                audit_event("remote_llm_code_review", task=clean_task[:200], chars=len(review_notes))

        return {
            "status": "ok",
            "task": clean_task,
            "module": target_module,
            "function": function_name,
            "code": generated_code,
            "libraries": libraries,
            "sources": [item.get("url", "") for item in resources if item.get("url")],
            "review_notes": review_notes[:4000] if review_notes else "",
        }

    def execute_generated_function(self, module_path: Path, function_name: str, command_text: str) -> Dict[str, str]:
        """Carga dinámicamente el módulo y ejecuta la función aprendida."""
        if not module_path.exists():
            return {"status": "error", "message": f"Módulo no encontrado: {module_path}"}

        try:
            spec = importlib.util.spec_from_file_location("eda_dynamic_skill", module_path)
            if spec is None or spec.loader is None:
                return {"status": "error", "message": "No pude cargar el módulo dinámico."}

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            fn = getattr(module, function_name, None)
            if fn is None:
                return {"status": "error", "message": f"Función {function_name} no encontrada."}

            signature = inspect.signature(fn)
            if len(signature.parameters) == 0:
                out = fn()
            else:
                out = fn(command_text)

            if isinstance(out, dict):
                return {
                    "status": str(out.get("status", "ok")),
                    "message": str(out.get("message", "Función ejecutada.")),
                }
            return {"status": "ok", "message": str(out)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def generate_code(self, question: str, language: str = "python") -> str:
        """Genera código completo especializado según lenguaje."""
        problem_type = self.detect_problem_type(question)
        lang = language.lower()
        if problem_type == "arduino":
            lang = "arduino"

        prompt = (
            "Genera SOLAMENTE código funcional y completo, sin texto adicional. "
            "Incluye manejo de errores y comentarios breves en español cuando aplique.\n"
            f"Lenguaje objetivo: {lang}.\n"
            f"Requerimiento: {question}"
        )
        answer = self.core.ask(prompt)
        code = self._extract_code_block(answer)
        if "modo degradado" in answer.lower() or "no tengo conexión" in answer.lower() or len(code) < 20:
            return self._default_template(problem_type)
        return code

    def save_generated_code(self, question: str, code: str, preferred_ext: str = "") -> Path:
        """Guarda código generado en la carpeta solutions/."""
        problem_type = self.detect_problem_type(question)
        ext = preferred_ext.strip().lower()
        if not ext:
            ext = ".ino" if problem_type == "arduino" else ".py"
        if not ext.startswith("."):
            ext = f".{ext}"

        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", question.lower())[:40].strip("_") or "solution"
        file_path = config.SOLUTIONS_DIR / f"{now_str()}_{safe_name}{ext}"
        file_path.write_text(code, encoding="utf-8")
        return file_path

    def synthesize_solution(self, question: str, extracted_context: str) -> str:
        """Sintetiza una solución con contexto web (prioriza LLM remoto cuando EDA_REMOTE_SEARCH_MODE)."""
        q = (question or "").strip()
        ctx = (extracted_context or "").strip()

        if remote_llm.remote_deep_research_pipeline_available():
            filtered = remote_llm.synthesize_filtered_web_answer(q, ctx[:120000])
            if filtered.strip():
                web_execution_gate.arm_after_external_research()
                return filtered
            return (
                "No obtuve síntesis segura desde el modelo remoto. Verificá "
                "EDA_REMOTE_LLM_* en .env y límites del proveedor."
            )

        prompt = (
            "Analiza la consulta técnica y el contexto web. "
            "Entrega en español: diagnóstico, pasos concretos y validación final."
            "Si aplica, incluye un bloque de código.\n\n"
            f"Consulta: {q}\n\n"
            f"Contexto web resumido: {ctx[:5000]}"
        )
        if remote_llm.use_remote_for_research_synthesis() and remote_llm.is_remote_fully_configured():
            system = (getattr(config, "REMOTE_LLM_SYSTEM_PROMPT", "") or config.APP_PERSONALITY).strip()
            messages = [
                {"role": "system", "content": system[:4000]},
                {"role": "user", "content": prompt[:120000]},
            ]
            remote_answer = remote_llm.chat_completion(messages, temperature=0.35)
            if remote_answer.strip():
                web_execution_gate.arm_after_external_research()
                return remote_answer

        answer = self.core.ask(prompt)
        if "modo degradado" in answer.lower() or "no tengo conexión" in answer.lower():
            return "No tengo LLM disponible. Entrego plan base y código generado automáticamente."
        return answer

    def solve(self, question: str, auto_save_code: bool = True) -> Dict[str, Any]:
        """Pipeline completo: cache -> búsqueda -> scraping -> síntesis -> código -> cache."""
        started_at = time.perf_counter()
        key = self._cache_key(question)
        cached = self.memory.get_cached_solution(key)
        if cached and self._is_cache_valid(cached):
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            log.info("[WEB_SOLVER] source=cache elapsed_ms=%.1f", elapsed_ms)
            return {
                "status": "ok",
                "source": "cache",
                "answer": cached.get("answer", ""),
                "saved_code": cached.get("saved_code", ""),
                "sources_used": cached.get("sources_used", []),
            }

        results = self.intelligent_search(question)
        context_chunks: List[str] = []
        sources_used: List[str] = []
        for item in results[:4]:
            url = item.get("url", "")
            if not url:
                continue
            page_text = self.scrape_page(url)
            if page_text:
                context_chunks.append(f"Fuente: {url}\n{page_text[:2200]}")
                sources_used.append(url)

        context = "\n\n".join(context_chunks)
        answer = self.synthesize_solution(question, context)

        saved_code = ""
        problem_type = self.detect_problem_type(question)
        should_generate = problem_type in {"arduino", "programming", "windows"}
        if auto_save_code and should_generate:
            code = self.generate_code(question, language="arduino" if problem_type == "arduino" else "python")
            file_path = self.save_generated_code(question, code, preferred_ext=".ino" if problem_type == "arduino" else ".py")
            saved_code = str(file_path)
            answer = (
                f"{answer}\n\n"
                f"Archivo generado automáticamente: {saved_code}\n"
                "Puede abrirlo y ejecutarlo/ajustarlo según su entorno, señor."
            )

        payload = {
            "question": question,
            "answer": answer,
            "results": results[:6],
            "saved_code": saved_code,
            "sources_used": sources_used[:4],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.memory.cache_solution(key, payload)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        log.info("[WEB_SOLVER] source=web+llm elapsed_ms=%.1f", elapsed_ms)
        return {
            "status": "ok",
            "source": "web+llm",
            "answer": answer,
            "saved_code": saved_code,
            "sources_used": sources_used[:4],
        }
