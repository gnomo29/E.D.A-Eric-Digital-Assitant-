"""Persistencia de memoria y aprendizaje local."""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from datetime import datetime
from typing import Any, Dict, List

import config
from logger import get_logger
from utils import safe_json_load, safe_json_save

log = get_logger("memory")

DEFAULT_MEMORY: Dict[str, Any] = {
    "profile": {"name": "Eric", "language": "es"},
    "preferences": {
        "voice_enabled": True,
        "theme": "jarvis",
        "model": config.OLLAMA_MODEL,
    },
    "history": [],
    "chat_history": [],
    "learned_commands": {},
    "learned_skills": {},
    "habits": {},
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

        if not isinstance(normalized.get("history"), list):
            normalized["history"] = []
        if not isinstance(normalized.get("chat_history"), list):
            normalized["chat_history"] = []

        for key in ("learned_commands", "learned_skills", "habits", "remembered", "knowledge_base"):
            if not isinstance(normalized.get(key), dict):
                normalized[key] = {}
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

    def learn_command(self, trigger: str, action: str) -> bool:
        data = self.get_memory()
        learned = data.get("learned_commands", {})
        learned[trigger.lower().strip()] = action
        data["learned_commands"] = learned
        log.info("Nuevo aprendizaje guardado: %s -> %s", trigger, action)
        return self.save_memory(data)

    def get_learned_action(self, trigger: str) -> str | None:
        data = self.get_memory()
        return data.get("learned_commands", {}).get(trigger.lower().strip())

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

    def find_learned_skill(self, user_text: str) -> Dict[str, Any] | None:
        """Encuentra habilidad aprendida por coincidencia de trigger en el texto del usuario."""
        normalized = self._normalize_text(user_text)
        if not normalized:
            return None

        for skill_name, payload in self.get_learned_skills().items():
            if not isinstance(payload, dict):
                continue
            trigger = self._normalize_text(str(payload.get("trigger", "")))
            if trigger and (trigger in normalized or normalized in trigger):
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
