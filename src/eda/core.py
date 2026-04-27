"""Núcleo conversacional con Ollama y fallbacks robustos."""

from __future__ import annotations

from datetime import datetime
import gc
import re
import time
from typing import Dict, List, Tuple
from urllib.parse import quote_plus
import webbrowser

import requests

from . import config
from .logger import get_logger
from . import remote_llm
from .memory import MemoryManager
from .utils import build_http_session, has_internet_connectivity
from .web_search import WebSearch

log = get_logger("core")


class EDACore:
    """Cliente principal para generar respuestas con Ollama."""

    def __init__(self, model: str | None = None, memory_manager: MemoryManager | None = None) -> None:
        self.model = model or config.OLLAMA_MODEL
        self.endpoint = config.OLLAMA_URL
        self.tags_endpoint = config.OLLAMA_TAGS_URL
        self.health_endpoint = config.OLLAMA_HEALTH_URL
        self.system_prompt = config.APP_PERSONALITY
        self.web_search = WebSearch()
        self.memory = memory_manager or MemoryManager()
        self.http = build_http_session()

    SEARCH_COMMAND_REGEX = re.compile(
        r"\b(busca|buscar|búscame|buscame|search|googlea|googleame)\b\s*(.*)",
        flags=re.IGNORECASE,
    )

    INVESTIGATE_COMMAND_REGEX = re.compile(
        r"^\s*(?:investiga(?:\s+sobre|\s+acerca\s+de|\s+la)?|investígame|investigame)\s+(.+)$",
        flags=re.IGNORECASE,
    )
    RESEARCH_LIKE_REGEX = re.compile(
        r"^\s*(?:que|qué|quien|quién|como|cómo|cuando|cuándo|donde|dónde|por que|por qué|explicame|explícame|defineme|defíneme)\b",
        flags=re.IGNORECASE,
    )

    # No confundir preguntas con órdenes: "¿abre chrome?" no debe forzar modo investigación.
    _COMMANDISH_START = re.compile(
        r"^\s*(?:abre|abrir|cierra|cerrar|reproduce|reproducir|pon|ponme|busca|buscar|búscame|buscame|"
        r"googlea|googleame|mutea|desmutea|silencia|silenciar|sube|baja|volumen|brillo|investiga|investigame|investígame|"
        r"recuerdame|recuérdame|recordatorio|entra|entrar|objetivo|planifica|planificar|evoluciona|autoevoluciona)\b",
        flags=re.IGNORECASE,
    )

    LOW_QUALITY_PHRASES = (
        "no sé",
        "no se",
        "no tengo información",
        "no tengo suficiente información",
        "no puedo responder",
        "no puedo ayudarte",
        "como modelo de lenguaje",
        "no tengo acceso a internet",
        "depende del contexto",
        "no puedo proporcionar",
    )

    INCAPABILITY_PHRASES = (
        "no puedo",
        "no sé cómo",
        "no se como",
        "no tengo esa funcionalidad",
        "no soy capaz",
        "no puedo hacerlo",
        "no puedo abrir",
    )

    AUTO_LEARN_EXCLUSIONS = (
        "no tengo conexión",
        "modo degradado",
        "ollama",
        "servicio",
    )

    def is_ollama_alive(self) -> bool:
        """Verifica si Ollama responde."""
        try:
            r = self.http.get(self.health_endpoint, timeout=3)
            return r.status_code < 500
        except Exception:
            return False

    def extract_web_search_query(self, message: str) -> str:
        """Extrae consulta de comandos de búsqueda tipo 'busca X'."""
        cleaned = (message or "").strip()
        if not cleaned:
            return ""

        match = self.SEARCH_COMMAND_REGEX.search(cleaned)
        if not match:
            return ""

        query = match.group(2).strip(" \t\n\r.,;:!?¡¿\"'")
        return query

    def extract_investigation_query(self, message: str) -> str:
        """Extrae tema de investigación para comandos tipo 'investiga X'."""
        cleaned = (message or "").strip()
        if not cleaned:
            return ""

        match = self.INVESTIGATE_COMMAND_REGEX.search(cleaned)
        if not match:
            return ""

        query = match.group(1).strip(" \t\n\r.,;:!?¡¿\"'")
        return query

    @staticmethod
    def _strip_web_prefix(answer: str) -> str:
        return re.sub(r"^Según mi búsqueda en línea,\s*", "", (answer or "").strip(), flags=re.IGNORECASE).strip()

    @staticmethod
    def _derive_knowledge_topic(query: str) -> str:
        normalized = re.sub(r"[^\w\sáéíóúñÁÉÍÓÚÑ]", " ", query.lower())
        normalized = re.sub(
            r"\b(investiga|investigame|investígame|sobre|acerca|de|la|el|los|las|quien|quienes|es|biografia|hablame|dime|que|por favor)\b",
            " ",
            normalized,
        )
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized or query.strip().lower()

    def _get_memory_answer(self, query: str) -> str:
        log.info("[MEMORY] Consultando knowledge base...")
        kb_hit = self.memory.search_knowledge(query)
        if kb_hit:
            log.info("[MEMORY] ✓ Encontrado en memoria: %s", kb_hit.get("topic", ""))
            answer = str(kb_hit.get("answer", "")).strip()
            return f"Según lo que aprendí anteriormente, {answer}"
        log.info("[MEMORY] ✗ No encontrado, buscando en línea...")
        return ""

    def _search_and_learn(self, query: str, max_results: int = 3, source: str = "web_search") -> str:
        if len(query) < 3:
            return "Según mi búsqueda en línea, necesito una pregunta más específica para ayudarte mejor."

        memory_answer = self._get_memory_answer(query)
        if memory_answer:
            return memory_answer

        results = self.web_search.search_google_snippets(query, max_results=max_results)
        if not results:
            return "Según mi búsqueda en línea, no encontré resultados útiles en este momento."

        base_answer = self.web_search.build_short_answer(query, results, max_sentences=3)
        compact = self._strip_web_prefix(base_answer)
        if not compact:
            return "Según mi búsqueda en línea, no encontré un resumen confiable por ahora."

        topic = self._derive_knowledge_topic(query)
        log.info("[MEMORY] ✓ Guardando nuevo conocimiento: %s", topic)
        self.memory.save_knowledge(topic=topic, question=query, answer=compact, source=source)
        return f"Según mi búsqueda en línea, {compact}"

    def force_research_answer(self, topic: str) -> str:
        """Realiza búsqueda web forzada en background y devuelve resumen hablado."""
        query = (topic or "").strip()
        if len(query) < 3:
            return "Según mi búsqueda en línea, necesito un tema más específico para ayudarte mejor."

        try:
            log.info("[RESEARCH] Investigando: %s", query)
            return self._search_and_learn(query, max_results=4, source="web_search")
        except Exception as exc:
            log.error("[RESEARCH] Error investigando '%s': %s", query, exc)
            return "Según mi búsqueda en línea, hubo un problema temporal al consultar la web."

    def is_research_like_query(self, message: str) -> bool:
        """Detecta preguntas de conocimiento general sin comando explícito."""
        cleaned = (message or "").strip()
        if len(cleaned) < 3:
            return False
        without_opening_punct = re.sub(r"^[¿?¡!]+", "", cleaned).strip()
        probe = without_opening_punct or cleaned
        if self._COMMANDISH_START.search(probe):
            return False
        if self.extract_investigation_query(cleaned):
            return True
        if cleaned.endswith("?"):
            return True
        return bool(self.RESEARCH_LIKE_REGEX.search(cleaned))

    def open_browser_for_research(self, query: str, max_pages: int = 2) -> List[str]:
        """
        Abre navegador para investigación:
        - búsqueda general en Google
        - hasta N fuentes sugeridas por snippets
        """
        q = (query or "").strip()
        if len(q) < 2:
            return []

        opened: List[str] = []
        search_url = f"https://www.google.com/search?q={quote_plus(q)}&hl=es"
        try:
            webbrowser.open(search_url)
            opened.append(search_url)
        except Exception as exc:
            log.warning("No pude abrir búsqueda base en navegador: %s", exc)

        try:
            results = self.web_search.search_google_snippets(q, max_results=max(1, max_pages * 2))
            added = 0
            for item in results:
                url = str(item.get("url", "")).strip()
                if not url or url in opened:
                    continue
                webbrowser.open(url)
                opened.append(url)
                added += 1
                if added >= max_pages:
                    break
        except Exception as exc:
            log.warning("No pude abrir fuentes de investigación: %s", exc)

        return opened

    def try_open_google_search(self, message: str) -> Tuple[bool, str]:
        """Abre una búsqueda en Google si el comando corresponde."""
        query = self.extract_web_search_query(message)

        if not query:
            normalized = (message or "").strip().lower()
            if self.SEARCH_COMMAND_REGEX.search(normalized):
                return (
                    True,
                    "Señor, necesito una consulta para buscar. Ejemplo: 'busca recetas de pizza'.",
                )
            return (False, "")

        if len(query) < 2:
            return (
                True,
                "Señor, la consulta es demasiado corta. Intente con algo más específico.",
            )

        encoded_query = quote_plus(query)
        url = f"https://www.google.com/search?q={encoded_query}"

        try:
            webbrowser.open(url)
            return (True, f"Buscando {query} en Google")
        except Exception as exc:
            log.error("No pude abrir navegador para búsqueda web: %s", exc)
            return (True, "Señor, no pude abrir el navegador para realizar la búsqueda.")

    def _available_models(self) -> List[str]:
        """Obtiene modelos disponibles en Ollama."""
        try:
            r = self.http.get(self.tags_endpoint, timeout=5)
            r.raise_for_status()
            models = r.json().get("models", [])
            names = [str(m.get("name", "")).strip() for m in models if m.get("name")]
            return [m for m in names if m]
        except Exception as exc:
            log.warning("No pude consultar modelos en Ollama: %s", exc)
            return []

    def _choose_model(self) -> str:
        """Selecciona modelo principal y fallback según disponibilidad."""
        available = set(self._available_models())
        candidates = [self.model] + [m for m in config.OLLAMA_MODEL_FALLBACKS if m != self.model]
        if available:
            for candidate in candidates:
                if candidate in available:
                    return candidate
            return next(iter(available))
        return self.model

    def build_prompt(
        self,
        message: str,
        history: List[Dict[str, str]] | None = None,
        extra_context: str = "",
        response_instruction: str = "",
    ) -> str:
        """Construye prompt final con historial breve."""
        history = history or []
        lines = [
            f"Sistema: {self.system_prompt}",
            (
                "Instrucción directa: responde en español, en máximo 5 líneas, "
                "sin inventar datos y priorizando pasos ejecutables."
            ),
        ]
        if response_instruction.strip():
            lines.append(f"Instrucción de estilo: {response_instruction.strip()}")
        if extra_context.strip():
            lines.append(f"Contexto del entorno: {extra_context.strip()}")
        for item in history[-6:]:
            role = str(item.get("role", "")).strip().lower()
            if role in {"user", "assistant"}:
                speaker = "Usuario" if role == "user" else "E.D.A."
                lines.append(f"{speaker}: {item.get('content', '')}")
                continue
            lines.append(f"Usuario: {item.get('user', '')}")
            lines.append(f"E.D.A.: {item.get('assistant', '')}")
        lines.append(f"Usuario: {message}")
        lines.append("E.D.A.:")
        return "\n".join(lines)

    def _fallback_answer(self, message: str) -> str:
        """Respuestas degradadas cuando Ollama no está disponible."""
        q = message.lower().strip()
        if "hora" in q:
            return f"Señor, en este momento son las {datetime.now().strftime('%H:%M:%S')}."
        if "fecha" in q or "día" in q:
            return f"Señor, hoy es {datetime.now().strftime('%d/%m/%Y')}."
        if "ayuda" in q or "comandos" in q:
            return (
                "Señor, estoy en modo degradado por falta de Ollama, "
                "pero aún puedo abrir/cerrar apps, optimizar el sistema, gestionar Bluetooth e investigar en web."
            )
        return (
            "Señor, no tengo conexión activa con Ollama en este instante. "
            "Continuaré en modo degradado hasta recuperar el servicio."
        )

    @staticmethod
    def _is_low_memory_condition() -> bool:
        """Evita consultas pesadas a Ollama si el equipo está bajo presión de RAM."""
        try:
            import psutil

            vm = psutil.virtual_memory()
            available_mb = vm.available / (1024 * 1024)
            return vm.percent >= 88 or available_mb < 700
        except Exception:
            return False

    def _is_low_quality_ollama_answer(self, answer: str) -> bool:
        """Heurística para detectar respuestas cortas, genéricas o inútiles."""
        normalized = (answer or "").strip().lower()
        if not normalized:
            return True

        if len(normalized) < 20:
            return True

        if any(phrase in normalized for phrase in self.LOW_QUALITY_PHRASES):
            return True

        # Respuestas muy vagas sin datos concretos.
        generic_markers = (
            "es importante",
            "puedo ayudarte",
            "intenta de nuevo",
            "en resumen",
            "depende",
        )
        words = re.findall(r"[a-záéíóúñ0-9]+", normalized)
        has_few_words = len(words) < 8
        has_generic_marker = any(marker in normalized for marker in generic_markers)

        if has_few_words and has_generic_marker:
            return True

        return False

    def detect_incapability(self, answer: str) -> bool:
        """Detecta frases típicas de incapacidad para activar AUTO_LEARN."""
        normalized = (answer or "").strip().lower()
        if not normalized:
            return False

        if any(ex in normalized for ex in self.AUTO_LEARN_EXCLUSIONS):
            return False

        return any(phrase in normalized for phrase in self.INCAPABILITY_PHRASES)

    def should_activate_auto_learn(self, user_message: str, candidate_answer: str) -> bool:
        """Decide si corresponde activar AUTO_LEARN según mensaje/respuesta."""
        msg = (user_message or "").strip()
        if len(msg) < 8:
            return False
        trivial = {
            "habla",
            "hola",
            "gracias",
            "ok",
            "vale",
            "si",
            "sí",
            "no",
            "calla",
            "silencio",
            "adios",
            "adiós",
        }
        if msg.lower().strip() in trivial:
            return False
        return self.detect_incapability(candidate_answer)

    @staticmethod
    def auto_learn_intro(task_text: str) -> str:
        task = (task_text or "esto").strip()
        return f"No sé cómo hacer eso todavía, pero déjame investigar y aprender... ({task})"

    def _web_search_fallback_answer(self, message: str) -> str:
        """Busca en línea y construye una respuesta breve apta para voz."""
        query = (message or "").strip()
        if len(query) < 3:
            return "Según mi búsqueda en línea, necesito una pregunta más específica para ayudarte mejor."

        try:
            log.info("[WEB_SEARCH] Buscando en línea: %s", query)
            return self._search_and_learn(query, max_results=3, source="web_search")
        except Exception as exc:
            log.error("[WEB_SEARCH] Error en fallback de búsqueda: %s", exc)
            return "Según mi búsqueda en línea, hubo un problema temporal al consultar la web."

    def ask(
        self,
        message: str,
        history: List[Dict[str, str]] | None = None,
        extra_context: str = "",
        *,
        allow_web_fallback: bool = True,
        response_instruction: str = "",
    ) -> str:
        """Consulta al modelo local y retorna texto."""
        started_at = time.perf_counter()
        online = has_internet_connectivity()
        if not online:
            allow_web_fallback = False

        def _finish(answer: str, source: str) -> str:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            log.info("[CORE] ask source=%s elapsed_ms=%.1f", source, elapsed_ms)
            return answer

        handled_search, search_answer = self.try_open_google_search(message)
        if handled_search:
            return _finish(search_answer, "search_command")

        prompt = self.build_prompt(message, history, extra_context=extra_context, response_instruction=response_instruction)

        if self._is_low_memory_condition():
            if allow_web_fallback:
                web_answer = self._web_search_fallback_answer(message)
                if web_answer:
                    return _finish(web_answer, "web_fallback_low_memory")
            return _finish(self._fallback_answer(message), "degraded_low_memory")

        if not self.is_ollama_alive():
            if remote_llm.use_remote_for_ask_fallback() and remote_llm.is_remote_fully_configured():
                remote_answer = remote_llm.try_completion_single_prompt(prompt, purpose="ask_no_ollama")
                if remote_answer:
                    return _finish(remote_answer, "remote_llm_fallback")
            # Sin Ollama, intentamos fallback web automático antes de degradar totalmente.
            if allow_web_fallback:
                web_answer = self._web_search_fallback_answer(message)
                if web_answer:
                    return _finish(web_answer, "web_fallback_no_ollama")
            return _finish(self._fallback_answer(message), "degraded_no_ollama")

        selected_model = self._choose_model()
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": config.OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": 0.25,
                "num_ctx": config.OLLAMA_NUM_CTX,
                "num_predict": config.OLLAMA_NUM_PREDICT,
                "num_thread": config.OLLAMA_NUM_THREAD,
            },
        }

        try:
            response = self.http.post(
                self.endpoint,
                json=payload,
                timeout=getattr(config, "OLLAMA_REQUEST_TIMEOUT_SECONDS", config.DEFAULT_TIMEOUT),
            )
            response.raise_for_status()
            data = response.json()
            content = str(data.get("response", "")).strip()

            if not content and remote_llm.use_remote_for_ask_fallback() and remote_llm.is_remote_fully_configured():
                remote_answer = remote_llm.try_completion_single_prompt(prompt, purpose="ask_ollama_empty")
                if remote_answer:
                    return _finish(remote_answer, "remote_llm_empty_ollama")

            if self._is_low_quality_ollama_answer(content):
                if allow_web_fallback:
                    log.info("[WEB_SEARCH] Respuesta de Ollama de baja calidad. Activando búsqueda web automática.")
                    return _finish(self._web_search_fallback_answer(message), "web_fallback_low_quality")
                return _finish(content or "No tengo una respuesta totalmente confiable para eso en este momento.", "ollama_low_quality_no_web")

            gc.collect()
            return _finish(content, "ollama")
        except Exception as exc:
            log.error("Error en Ollama: %s", exc)
            # Liberar referencias antes del fallback en entornos de RAM limitada.
            payload.clear()
            if remote_llm.use_remote_for_ask_fallback() and remote_llm.is_remote_fully_configured():
                remote_answer = remote_llm.try_completion_single_prompt(prompt, purpose="ask_ollama_error")
                if remote_answer:
                    return _finish(remote_answer, "remote_llm_after_ollama_error")
            if allow_web_fallback:
                web_answer = self._web_search_fallback_answer(message)
                if web_answer:
                    return _finish(web_answer, "web_fallback_error")
            return _finish(self._fallback_answer(message), "degraded_error")
