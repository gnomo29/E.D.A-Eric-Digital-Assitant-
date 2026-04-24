"""Persistencia de memoria y aprendizaje local."""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, List

from . import config
from .logger import get_logger
from .nlp_utils import normalize_learned_trigger_key
from .utils import safe_json_load, safe_json_save

log = get_logger("memory")

DEFAULT_MEMORY: Dict[str, Any] = {
    "profile": {"name": "Eric", "language": "es"},
    "preferences": {
        "voice_enabled": True,
        "theme": "jarvis",
        "model": config.OLLAMA_MODEL,
        "action_permissions": {
            "system": True,
            "web": True,
            "automation": True,
            "learning": True,
        },
        "proactive_insights_enabled": True,
        "ui_chat_font_size": config.UI_CHAT_FONT_DEFAULT,
    },
    "behavior_events": [],
    "assistant_state": {"proactive": {}},
    "history": [],
    "chat_history": [],
    "learned_commands": {},
    "learned_skills": {},
    "habits": {},
    "objectives": [],
    "objective_history": [],
    "remembered": {},
    "reminders": [],
    "knowledge_base": {},
    "knowledge_order": [],
}


class MemoryManager:
    """Gestiona archivos JSON de memoria de E.D.A."""

    def __init__(self, knowledge_limit: int = 1000) -> None:
        self.memory_file = config.MEMORY_FILE
        self.bt_file = config.BT_MEMORY_FILE
        self.cache_file = config.SOLUTIONS_CACHE_FILE
        self.knowledge_limit = max(1, int(knowledge_limit))
        self._lock = threading.Lock()
        self._memory_cache: Dict[str, Any] | None = None
        self._memory_cache_mtime: float | None = None
        self._memory_cache_loaded_at = 0.0
        self._bootstrap()

    def _bootstrap(self) -> None:
        """Crea archivos iniciales si faltan y migra estructura antigua."""
        if not self.memory_file.exists():
            safe_json_save(self.memory_file, dict(DEFAULT_MEMORY))
        else:
            data = self._normalize_memory_schema(safe_json_load(self.memory_file, {}))
            safe_json_save(self.memory_file, data)

        if not self.bt_file.exists():
            safe_json_save(self.bt_file, {"known_devices": [], "favorites": []})
        else:
            bt_data = safe_json_load(self.bt_file, {"known_devices": [], "favorites": []})
            bt_data.setdefault("known_devices", [])
            bt_data.setdefault("favorites", [])
            safe_json_save(self.bt_file, bt_data)

        if not self.cache_file.exists():
            safe_json_save(self.cache_file, {"solutions": {}})

    def get_memory(self) -> Dict[str, Any]:
        return self.load_memory()

    def _normalize_memory_schema(self, data: Any) -> Dict[str, Any]:
        """Garantiza una estructura mínima consistente para la memoria."""
        if not isinstance(data, dict):
            return dict(DEFAULT_MEMORY)

        normalized = dict(DEFAULT_MEMORY)
        normalized.update(data)

        if not isinstance(normalized.get("profile"), dict):
            normalized["profile"] = dict(DEFAULT_MEMORY["profile"])
        if not isinstance(normalized.get("preferences"), dict):
            normalized["preferences"] = dict(DEFAULT_MEMORY["preferences"])

        normalized["profile"].setdefault("name", "Eric")
        normalized["profile"].setdefault("language", "es")
        normalized["preferences"].setdefault("voice_enabled", True)
        normalized["preferences"].setdefault("theme", "jarvis")
        normalized["preferences"].setdefault("model", config.OLLAMA_MODEL)
        action_permissions = normalized["preferences"].get("action_permissions", {})
        if not isinstance(action_permissions, dict):
            action_permissions = {}
        action_permissions.setdefault("system", True)
        action_permissions.setdefault("web", True)
        action_permissions.setdefault("automation", True)
        action_permissions.setdefault("learning", True)
        normalized["preferences"]["action_permissions"] = action_permissions
        normalized["preferences"].setdefault("proactive_insights_enabled", True)
        fs = normalized["preferences"].get("ui_chat_font_size", config.UI_CHAT_FONT_DEFAULT)
        try:
            fs_int = int(fs)
        except (TypeError, ValueError):
            fs_int = int(config.UI_CHAT_FONT_DEFAULT)
        normalized["preferences"]["ui_chat_font_size"] = max(
            int(config.UI_CHAT_FONT_MIN), min(int(config.UI_CHAT_FONT_MAX), fs_int)
        )

        if not isinstance(normalized.get("behavior_events"), list):
            normalized["behavior_events"] = []
        if not isinstance(normalized.get("assistant_state"), dict):
            normalized["assistant_state"] = {}
        if not isinstance(normalized["assistant_state"].get("proactive"), dict):
            normalized["assistant_state"]["proactive"] = {}

        if not isinstance(normalized.get("history"), list):
            normalized["history"] = []
        if not isinstance(normalized.get("chat_history"), list):
            normalized["chat_history"] = []

        for key in ("learned_commands", "learned_skills", "habits", "remembered", "knowledge_base"):
            if not isinstance(normalized.get(key), dict):
                normalized[key] = {}
        if not isinstance(normalized.get("objectives"), list):
            normalized["objectives"] = []
        if not isinstance(normalized.get("objective_history"), list):
            normalized["objective_history"] = []
        if not isinstance(normalized.get("reminders"), list):
            normalized["reminders"] = []
        if not isinstance(normalized.get("knowledge_order"), list):
            normalized["knowledge_order"] = []

        return normalized

    def load_memory(self) -> Dict[str, Any]:
        """Carga memoria desde disco, repara estructura y persiste si hubo cambios."""
        with self._lock:
            ttl = max(0.2, float(getattr(config, "MEMORY_CACHE_TTL_SECONDS", 2.0)))
            now = time.time()
            current_mtime = self.memory_file.stat().st_mtime if self.memory_file.exists() else None
            if (
                self._memory_cache is not None
                and current_mtime == self._memory_cache_mtime
                and (now - self._memory_cache_loaded_at) <= ttl
            ):
                return dict(self._memory_cache)

            raw_data = safe_json_load(self.memory_file, {})
            normalized_data = self._normalize_memory_schema(raw_data)
            if normalized_data != raw_data:
                safe_json_save(self.memory_file, normalized_data)
                current_mtime = self.memory_file.stat().st_mtime if self.memory_file.exists() else current_mtime
            self._memory_cache = dict(normalized_data)
            self._memory_cache_mtime = current_mtime
            self._memory_cache_loaded_at = now
            return normalized_data

    def save_memory(self, memory_data: Dict[str, Any]) -> bool:
        with self._lock:
            normalized_data = self._normalize_memory_schema(memory_data)
            saved = safe_json_save(self.memory_file, normalized_data)
            if saved:
                self._memory_cache = dict(normalized_data)
                self._memory_cache_mtime = self.memory_file.stat().st_mtime if self.memory_file.exists() else None
                self._memory_cache_loaded_at = time.time()
            return saved

    @staticmethod
    def _build_chat_message(role: str, content: str, timestamp: str | None = None) -> Dict[str, str] | None:
        clean_role = (role or "").strip().lower()
        clean_content = (content or "").strip()
        if clean_role not in {"user", "assistant", "system"} or not clean_content:
            return None
        return {
            "role": clean_role,
            "content": clean_content,
            "timestamp": timestamp or datetime.now().isoformat(timespec="seconds"),
        }

    def append_chat_message(self, role: str, content: str, timestamp: str | None = None, limit: int = 300) -> bool:
        """Agrega un mensaje al chat persistente en formato role/content/timestamp."""
        message = self._build_chat_message(role, content, timestamp=timestamp)
        if not message:
            return False
        data = self.load_memory()
        chat_history = data.get("chat_history", [])
        if not isinstance(chat_history, list):
            chat_history = []
        chat_history.append(message)
        data["chat_history"] = chat_history[-max(10, int(limit)) :]
        return self.save_memory(data)

    def add_history(self, user_text: str, assistant_text: str) -> bool:
        data = self.get_memory()
        history: List[Dict[str, str]] = data.get("history", [])
        history.append(
            {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "user": user_text,
                "assistant": assistant_text,
            }
        )
        data["history"] = history[-120:]
        chat_history = data.get("chat_history", [])
        if not isinstance(chat_history, list):
            chat_history = []
        user_msg = self._build_chat_message("user", user_text)
        assistant_msg = self._build_chat_message("assistant", assistant_text)
        if user_msg:
            chat_history.append(user_msg)
        if assistant_msg:
            chat_history.append(assistant_msg)
        data["chat_history"] = chat_history[-300:]
        return self.save_memory(data)

    def learn_command(self, trigger: str, action: str, append: bool = True) -> bool:
        data = self.get_memory()
        learned = data.get("learned_commands", {})
        key = normalize_learned_trigger_key(trigger)
        new_action = (action or "").strip()
        if not key or not new_action:
            return False

        current = learned.get(key)
        if current is None:
            learned[key] = [new_action]
        else:
            if isinstance(current, list):
                actions = current
            elif isinstance(current, str):
                actions = [current]
            else:
                actions = []

            if append:
                if new_action not in actions:
                    actions.append(new_action)
            else:
                actions = [new_action]
            learned[key] = actions

        data["learned_commands"] = learned
        log.info("Nuevo aprendizaje guardado: %s -> %s", trigger, new_action)
        return self.save_memory(data)

    def get_learned_action(self, trigger: str) -> str | None:
        data = self.get_memory()
        value = data.get("learned_commands", {}).get(normalize_learned_trigger_key(trigger))
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
        return None

    def get_learned_actions(self, trigger: str) -> List[str]:
        data = self.get_memory()
        value = data.get("learned_commands", {}).get(normalize_learned_trigger_key(trigger))
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def save_learned_skill(self, skill_name: str, trigger: str, module: str, function_name: str) -> bool:
        """Guarda habilidad aprendida para reutilización futura."""
        data = self.get_memory()
        skills = data.get("learned_skills", {})
        key = self._normalize_text(skill_name) or skill_name.strip().lower()
        skills[key] = {
            "learned_at": datetime.now().strftime("%Y-%m-%d"),
            "trigger": trigger.strip().lower(),
            "module": module,
            "function": function_name,
        }
        data["learned_skills"] = skills
        log.info("[AUTO_LEARN] Habilidad guardada: %s -> %s.%s", key, module, function_name)
        return self.save_memory(data)

    def get_learned_skills(self) -> Dict[str, Any]:
        data = self.get_memory()
        return data.get("learned_skills", {})

    def forget_learned_skill(self, skill_name: str) -> bool:
        """Elimina una habilidad aprendida por nombre/clave normalizada."""
        key = self._normalize_text(skill_name) or (skill_name or "").strip().lower()
        if not key:
            return False
        data = self.get_memory()
        skills = data.get("learned_skills", {})
        if not isinstance(skills, dict):
            return False
        skills.pop(key, None)
        data["learned_skills"] = skills
        return self.save_memory(data)

    def find_learned_skill(self, user_text: str) -> Dict[str, Any] | None:
        """Encuentra habilidad aprendida por coincidencia de trigger en el texto del usuario."""
        normalized = self._normalize_text(user_text)
        if not normalized:
            return None

        for skill_name, payload in self.get_learned_skills().items():
            if not isinstance(payload, dict):
                continue
            trigger = self._normalize_text(str(payload.get("trigger", "")))
            if not trigger:
                continue
            # El usuario incluye el gatillo completo en su mensaje.
            if trigger in normalized:
                return {"skill": skill_name, **payload}
            # Evitar falsos positivos (ej. "re" dentro de "aprender...").
            if len(normalized) >= 12 and normalized in trigger:
                return {"skill": skill_name, **payload}
        return None

    def remember(self, key: str, value: str) -> bool:
        data = self.get_memory()
        remembered = data.get("remembered", {})
        remembered[key.strip().lower()] = {
            "value": value,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        data["remembered"] = remembered
        return self.save_memory(data)

    def forget(self, key: str) -> bool:
        data = self.get_memory()
        remembered = data.get("remembered", {})
        remembered.pop(key.strip().lower(), None)
        data["remembered"] = remembered
        return self.save_memory(data)

    def recall(self, key: str) -> str | None:
        data = self.get_memory()
        remembered = data.get("remembered", {})
        item = remembered.get(key.strip().lower())
        if isinstance(item, dict):
            return str(item.get("value", ""))
        return None

    def register_habit(self, habit_name: str) -> bool:
        data = self.get_memory()
        habits = data.get("habits", {})
        current = habits.get(habit_name, 0)
        habits[habit_name] = int(current) + 1
        data["habits"] = habits
        return self.save_memory(data)

    def clear_behavior_events(self) -> bool:
        """Borra solo el historial de patrones de uso y el estado de sugerencias proactivas."""
        data = self.get_memory()
        data["behavior_events"] = []
        state = data.get("assistant_state")
        if isinstance(state, dict):
            state["proactive"] = {}
            data["assistant_state"] = state
        return self.save_memory(data)

    def record_behavior_event(self, intent: str, entity: str, user_preview: str) -> bool:
        if self._contains_sensitive_data(user_preview):
            return False
        data = self.get_memory()
        events = data.get("behavior_events", [])
        if not isinstance(events, list):
            events = []
        preview = (user_preview or "").strip()[:240]
        events.append(
            {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "intent": (intent or "chat")[:48],
                "entity": (entity or "")[:120],
                "preview": preview,
            }
        )
        max_e = max(20, int(getattr(config, "BEHAVIOR_EVENTS_MAX", 250)))
        data["behavior_events"] = events[-max_e:]
        return self.save_memory(data)

    def get_behavior_insights(self, window: int = 120) -> Dict[str, Any]:
        data = self.load_memory()
        events = data.get("behavior_events", [])
        if not isinstance(events, list):
            events = []
        slice_e = events[-max(10, window) :]
        intent_counts: Dict[str, int] = {}
        open_app_entities: Dict[str, int] = {}
        for e in slice_e:
            if not isinstance(e, dict):
                continue
            it = str(e.get("intent", "chat"))
            intent_counts[it] = intent_counts.get(it, 0) + 1
            if it == "open_app":
                ent = str(e.get("entity", "")).strip().lower()[:80]
                if ent:
                    open_app_entities[ent] = open_app_entities.get(ent, 0) + 1
        top_intents = sorted(intent_counts.items(), key=lambda x: -x[1])[:6]
        top_open = sorted(open_app_entities.items(), key=lambda x: -x[1])[:6]
        return {
            "total": len(slice_e),
            "top_intents": top_intents,
            "top_open_app_targets": top_open,
        }

    def should_emit_proactive_suggestion(self) -> bool:
        if not getattr(config, "PROACTIVE_INSIGHTS_ENABLED", True):
            return False
        data = self.load_memory()
        prefs = data.get("preferences", {})
        if isinstance(prefs, dict) and prefs.get("proactive_insights_enabled") is False:
            return False
        events = data.get("behavior_events", [])
        if not isinstance(events, list):
            return False
        min_ev = int(getattr(config, "PROACTIVE_MIN_BEHAVIOR_EVENTS", 12))
        if len(events) < min_ev:
            return False
        state = data.get("assistant_state")
        if not isinstance(state, dict):
            return True
        pro = state.get("proactive")
        if not isinstance(pro, dict):
            return True
        last_ts = str(pro.get("last_ts", "")).strip()
        if not last_ts:
            return True
        try:
            last = datetime.fromisoformat(last_ts)
            hours = float(getattr(config, "PROACTIVE_SUGGESTION_COOLDOWN_HOURS", 4))
            if datetime.now() - last < timedelta(hours=hours):
                return False
        except Exception:
            return True
        return True

    def mark_proactive_suggestion_sent(self, message: str) -> bool:
        data = self.load_memory()
        if not isinstance(data.get("assistant_state"), dict):
            data["assistant_state"] = {}
        state = data["assistant_state"]
        if not isinstance(state.get("proactive"), dict):
            state["proactive"] = {}
        state["proactive"]["last_ts"] = datetime.now().isoformat(timespec="seconds")
        state["proactive"]["last_message"] = (message or "")[:500]
        return self.save_memory(data)

    def build_proactive_suggestion_text(self) -> str | None:
        insights = self.get_behavior_insights(window=120)
        total = max(1, int(insights.get("total", 1)))
        top = insights.get("top_intents") or []
        if not top:
            return None
        name, cnt = top[0]
        ratio = cnt / total
        if ratio < 0.32:
            return None
        if name == "open_app":
            targets = insights.get("top_open_app_targets") or []
            if targets:
                ent, ec = targets[0]
                if ec >= 3 and ent:
                    return (
                        f"Noto que abre a menudo «{ent}». "
                        "Si quiere encadenar acciones, puede enseñarme: «Quiero que cuando diga modo trabajo abras …»."
                    )
        if name == "search_web":
            return (
                "Consulta la web con frecuencia. Para síntesis más profunda: «investiga …» "
                "o un plan local: «¿cómo implementarías …?»"
            )
        if name in ("chat", "question") and ratio > 0.52:
            return (
                "Muchas consultas en modo conversación. Para acciones concretas: «abre …», «busca …» "
                "o «Quiero que …» para automatizar con seguridad."
            )
        return None

    # --------------------------
    # Knowledge base persistente
    # --------------------------

    @staticmethod
    def _strip_accents(text: str) -> str:
        normalized = unicodedata.normalize("NFD", text or "")
        return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")

    def _normalize_text(self, text: str) -> str:
        base = self._strip_accents((text or "").lower())
        base = re.sub(r"[^a-z0-9\s]", " ", base)
        base = re.sub(r"\s+", " ", base).strip()
        return base

    def _extract_keywords(self, text: str) -> List[str]:
        stopwords = {
            "el",
            "la",
            "los",
            "las",
            "un",
            "una",
            "unos",
            "unas",
            "de",
            "del",
            "al",
            "y",
            "o",
            "que",
            "por",
            "para",
            "con",
            "sobre",
            "acerca",
            "a",
            "en",
            "es",
            "quien",
            "quienes",
            "cual",
            "cuales",
            "hablame",
            "dime",
            "investiga",
            "biografia",
            "historia",
            "favor",
            "podrias",
            "puedes",
        }
        norm = self._normalize_text(text)
        words = [w for w in norm.split() if len(w) > 1 and w not in stopwords]
        return words

    def _infer_topic(self, question: str, explicit_topic: str = "") -> str:
        if explicit_topic:
            normalized_topic = self._normalize_text(explicit_topic)
            return normalized_topic[:80] if normalized_topic else "general"

        keywords = self._extract_keywords(question)
        if not keywords:
            normalized = self._normalize_text(question)
            return normalized[:80] if normalized else "general"
        return " ".join(keywords[:4]).strip()

    def _contains_sensitive_data(self, text: str) -> bool:
        raw = text or ""
        lowered = raw.lower()
        sensitive_markers = ["contraseña", "password", "token", "api key", "tarjeta", "dni", "cedula", "correo"]
        if any(marker in lowered for marker in sensitive_markers):
            return True
        if re.search(r"\b\d{8,}\b", raw):
            return True
        if re.search(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", raw):
            return True
        return False

    def save_knowledge(self, topic: str, question: str, answer: str, source: str = "web_search") -> bool:
        """Guarda conocimiento nuevo con límite FIFO y persistencia."""
        if not answer or len(answer.strip()) < 8:
            return False

        if self._contains_sensitive_data(question) or self._contains_sensitive_data(answer):
            log.info("[MEMORY] Se omitió guardar conocimiento por posible contenido sensible.")
            return False

        data = self.get_memory()
        kb = data.get("knowledge_base", {})
        order = data.get("knowledge_order", [])

        inferred_topic = self._infer_topic(question, explicit_topic=topic)
        if not inferred_topic:
            inferred_topic = "general"

        kb[inferred_topic] = {
            "question": (question or "").strip(),
            "answer": (answer or "").strip(),
            "learned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
        }

        if inferred_topic in order:
            order.remove(inferred_topic)
        order.append(inferred_topic)

        while len(order) > self.knowledge_limit:
            oldest = order.pop(0)
            kb.pop(oldest, None)

        data["knowledge_base"] = kb
        data["knowledge_order"] = order
        return self.save_memory(data)

    def search_knowledge(self, query: str) -> Dict[str, Any] | None:
        """Busca una coincidencia semántica simple en knowledge_base."""
        data = self.get_memory()
        kb = data.get("knowledge_base", {})
        if not kb:
            return None

        query_norm = self._normalize_text(query)
        query_keywords = set(self._extract_keywords(query))
        if not query_norm and not query_keywords:
            return None

        best_topic = ""
        best_entry: Dict[str, Any] = {}
        best_score = 0

        for topic, entry in kb.items():
            if not isinstance(entry, dict):
                continue

            topic_norm = self._normalize_text(topic)
            question_norm = self._normalize_text(str(entry.get("question", "")))
            search_blob = f"{topic_norm} {question_norm}".strip()
            entry_keywords = set(self._extract_keywords(f"{topic} {entry.get('question', '')}"))

            score = 0
            if topic_norm and topic_norm in query_norm:
                score += 6
            if query_norm and query_norm in search_blob:
                score += 4

            overlap = query_keywords.intersection(entry_keywords)
            score += len(overlap) * 2

            if len(query_keywords) >= 2 and len(overlap) >= 2:
                score += 3
            elif len(query_keywords) <= 2 and len(overlap) >= 1:
                score += 2

            if score > best_score:
                best_score = score
                best_topic = topic
                best_entry = entry

        if best_score < 3:
            return None

        return {
            "topic": best_topic,
            "question": best_entry.get("question", ""),
            "answer": best_entry.get("answer", ""),
            "learned_at": best_entry.get("learned_at", ""),
            "source": best_entry.get("source", "web_search"),
            "score": best_score,
        }

    def clear_knowledge(self) -> bool:
        """Limpia por completo la base de conocimiento aprendida."""
        data = self.get_memory()
        data["knowledge_base"] = {}
        data["knowledge_order"] = []
        return self.save_memory(data)

    def clear_all_memory(self) -> bool:
        """Restablece la memoria principal a valores base, conservando preferencias principales."""
        current = self.get_memory()
        reset = dict(DEFAULT_MEMORY)
        # Conserva perfil y preferencias actuales para no romper experiencia del usuario.
        if isinstance(current.get("profile"), dict):
            reset["profile"] = dict(current.get("profile", {}))
        if isinstance(current.get("preferences"), dict):
            reset["preferences"] = dict(current.get("preferences", {}))
        return self.save_memory(reset)

    def get_reminders(self) -> List[Dict[str, Any]]:
        data = self.get_memory()
        reminders = data.get("reminders", [])
        if isinstance(reminders, list):
            return reminders
        return []

    def save_reminders(self, reminders: List[Dict[str, Any]]) -> bool:
        data = self.get_memory()
        data["reminders"] = reminders if isinstance(reminders, list) else []
        return self.save_memory(data)

    def get_objectives(self) -> List[Dict[str, Any]]:
        data = self.get_memory()
        objectives = data.get("objectives", [])
        return objectives if isinstance(objectives, list) else []

    def save_objectives(self, objectives: List[Dict[str, Any]]) -> bool:
        data = self.get_memory()
        data["objectives"] = objectives if isinstance(objectives, list) else []
        return self.save_memory(data)

    def archive_objective(self, objective_payload: Dict[str, Any]) -> bool:
        data = self.get_memory()
        history = data.get("objective_history", [])
        if not isinstance(history, list):
            history = []
        history.append(objective_payload)
        data["objective_history"] = history[-100:]
        return self.save_memory(data)

    def get_solution_cache(self) -> Dict[str, Any]:
        return safe_json_load(self.cache_file, {"solutions": {}})

    def cache_solution(self, key: str, payload: Dict[str, Any]) -> bool:
        data = self.get_solution_cache()
        solutions = data.get("solutions", {})
        solutions[key] = payload
        data["solutions"] = solutions
        return safe_json_save(self.cache_file, data)

    def get_cached_solution(self, key: str) -> Dict[str, Any] | None:
        data = self.get_solution_cache()
        return data.get("solutions", {}).get(key)

    def save_bt_devices(self, known_devices: List[Dict[str, Any]], favorites: List[Dict[str, Any]] | None = None) -> bool:
        current = safe_json_load(self.bt_file, {"known_devices": [], "favorites": []})
        data = {
            "known_devices": known_devices,
            "favorites": favorites if favorites is not None else current.get("favorites", []),
        }
        return safe_json_save(self.bt_file, data)

    def get_bt_devices(self) -> Dict[str, Any]:
        return safe_json_load(self.bt_file, {"known_devices": [], "favorites": []})

    def add_bt_favorite(self, device: Dict[str, Any]) -> bool:
        data = self.get_bt_devices()
        favorites = data.get("favorites", [])
        address = str(device.get("address", "")).strip()
        if not address:
            return False
        if not any(str(d.get("address", "")).strip() == address for d in favorites):
            favorites.append(device)
        return self.save_bt_devices(data.get("known_devices", []), favorites)
