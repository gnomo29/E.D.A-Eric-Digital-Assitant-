"""Persistencia de memoria y aprendizaje local."""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import shutil
import zipfile
import unicodedata
import base64
import hashlib
import math
import json
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from . import config
from .logger import get_logger
from .nlp_utils import normalize_learned_trigger_key
from .utils import safe_json_load, safe_json_save
from .utils.security import redact_sensitive_data

try:
    from cryptography.fernet import Fernet
except Exception:
    Fernet = None  # type: ignore[assignment]


class _FallbackCipher:
    """Cipher liviano de compatibilidad cuando cryptography no está disponible."""

    def __init__(self, key_bytes: bytes) -> None:
        self.key = key_bytes or b"eda"

    def encrypt(self, content: bytes) -> bytes:
        xored = bytes(content[i] ^ self.key[i % len(self.key)] for i in range(len(content)))
        return base64.urlsafe_b64encode(xored)

    def decrypt(self, token: bytes) -> bytes:
        raw = base64.urlsafe_b64decode(token)
        return bytes(raw[i] ^ self.key[i % len(self.key)] for i in range(len(raw)))

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
    "user_preferences": {},
    "session_context": {},
}


class MemoryManager:
    """Gestiona archivos JSON de memoria de E.D.A."""

    def __init__(self, knowledge_limit: int = 1000) -> None:
        self.memory_file = config.MEMORY_FILE
        self.bt_file = config.BT_MEMORY_FILE
        self.cache_file = config.SOLUTIONS_CACHE_FILE
        self.user_profile_file = config.USER_PROFILE_FILE
        self.long_term_db_file = config.LONG_TERM_DB_FILE
        self.knowledge_limit = max(1, int(knowledge_limit))
        self._lock = threading.Lock()
        self._long_term_lock = threading.Lock()
        self._memory_cache: Dict[str, Any] | None = None
        self._memory_cache_mtime: float | None = None
        self._memory_cache_loaded_at = 0.0
        self._vector_index: Dict[str, Dict[str, float]] = {}
        self._bootstrap()

    def _bootstrap(self) -> None:
        """Crea archivos iniciales si faltan y migra estructura antigua."""
        if not self.memory_file.exists():
            self._save_memory_payload(dict(DEFAULT_MEMORY))
        else:
            raw = self._load_memory_payload()
            data = self._normalize_memory_schema(raw)
            self._save_memory_payload(data)

        if not self.bt_file.exists():
            safe_json_save(self.bt_file, {"known_devices": [], "favorites": []})
        else:
            bt_data = safe_json_load(self.bt_file, {"known_devices": [], "favorites": []})
            bt_data.setdefault("known_devices", [])
            bt_data.setdefault("favorites", [])
            safe_json_save(self.bt_file, bt_data)

        if not self.cache_file.exists():
            safe_json_save(self.cache_file, {"solutions": {}})
        if not self.user_profile_file.exists():
            safe_json_save(
                self.user_profile_file,
                {"name": "Eric", "traits": [], "facts": {}, "updated_at": datetime.now().isoformat(timespec="seconds")},
            )
        self._bootstrap_long_term_db()

    def _bootstrap_long_term_db(self) -> None:
        self.long_term_db_file.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.long_term_db_file)) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
            if cols and not {"tag", "text", "created_at", "metadata_json"}.issubset(set(cols)):
                try:
                    conn.execute("ALTER TABLE memories RENAME TO memories_legacy")
                except Exception:
                    pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tag TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS triggers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phrase TEXT NOT NULL,
                    match_type TEXT NOT NULL,
                    fuzzy_threshold REAL NOT NULL,
                    action_type TEXT NOT NULL,
                    action_payload TEXT NOT NULL,
                    require_confirm INTEGER NOT NULL,
                    owner TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_triggers_phrase ON triggers(phrase)")
            conn.commit()

    def get_memory(self) -> Dict[str, Any]:
        return self.load_memory()

    def get_user_profile(self) -> Dict[str, Any]:
        raw = safe_json_load(self.user_profile_file, {})
        if not isinstance(raw, dict):
            raw = {}
        profile = {
            "name": str(raw.get("name", "Eric")).strip() or "Eric",
            "traits": raw.get("traits", []) if isinstance(raw.get("traits"), list) else [],
            "facts": raw.get("facts", {}) if isinstance(raw.get("facts"), dict) else {},
            "updated_at": str(raw.get("updated_at", datetime.now().isoformat(timespec="seconds"))),
        }
        return profile

    def save_user_profile(self, profile: Dict[str, Any]) -> bool:
        payload = {
            "name": str(profile.get("name", "Eric")).strip() or "Eric",
            "traits": profile.get("traits", []) if isinstance(profile.get("traits"), list) else [],
            "facts": profile.get("facts", {}) if isinstance(profile.get("facts"), dict) else {},
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        return safe_json_save(self.user_profile_file, payload)

    def extract_identity_facts(self, text: str) -> Dict[str, str]:
        low = (text or "").strip().lower()
        if not low:
            return {}
        facts: Dict[str, str] = {}
        m_name = re.search(
            r"\b(?:me llamo|mi nombre es|i am|my name is)\s+([a-záéíóúñ][a-záéíóúñ0-9 _-]{1,40}?)(?:\s+y\s+|\s*,|$)",
            low,
        )
        if m_name:
            facts["name"] = m_name.group(1).strip().title()
        m_role = re.search(r"\b(?:soy|i am)\s+(programador|developer|ingeniero|estudiante|diseñador|doctor|abogado)\b", low)
        if m_role:
            facts["role"] = m_role.group(1).strip()
        m_city = re.search(r"\b(?:vivo en|i live in)\s+([a-záéíóúñ][a-záéíóúñ _-]{1,40})", low)
        if m_city:
            facts["location"] = m_city.group(1).strip().title()
        return facts

    def update_user_profile_from_text(self, text: str) -> Dict[str, str]:
        facts = self.extract_identity_facts(text)
        if not facts:
            return {}
        profile = self.get_user_profile()
        fact_map = profile.get("facts", {})
        if not isinstance(fact_map, dict):
            fact_map = {}
        if facts.get("name"):
            profile["name"] = facts["name"]
        for k, v in facts.items():
            fact_map[k] = v
        profile["facts"] = fact_map
        self.save_user_profile(profile)
        return facts

    def get_profile_summary_for_prompt(self) -> str:
        profile = self.get_user_profile()
        facts = profile.get("facts", {})
        if not isinstance(facts, dict):
            facts = {}
        chunks = [f"nombre={profile.get('name', 'Eric')}"]
        for key in ("role", "location"):
            val = str(facts.get(key, "")).strip()
            if val:
                chunks.append(f"{key}={val}")
        prefs = self.get_user_preferences()
        if prefs:
            pref_chunks = [f"{k}={v}" for k, v in list(prefs.items())[:4]]
            if pref_chunks:
                chunks.append("preferencias=" + ",".join(pref_chunks))
        context = self.get_active_context()
        if context:
            ctx_chunks = [f"{k}={v}" for k, v in list(context.items())[:3]]
            if ctx_chunks:
                chunks.append("contexto=" + ",".join(ctx_chunks))
        return " | ".join(chunks)

    def get_user_preferences(self) -> Dict[str, str]:
        data = self.get_memory()
        prefs = data.get("user_preferences", {})
        if not isinstance(prefs, dict):
            return {}
        return {str(k): str(v) for k, v in prefs.items() if str(v).strip()}

    def set_user_preference(self, key: str, value: str) -> bool:
        k = self._normalize_text(key).replace(" ", "_")[:48]
        v = str(value or "").strip()[:160]
        if not k or not v:
            return False
        data = self.get_memory()
        prefs = data.get("user_preferences", {})
        if not isinstance(prefs, dict):
            prefs = {}
        prefs[k] = v
        data["user_preferences"] = prefs
        return self.save_memory(data)

    def set_temporary_context(self, key: str, value: str, ttl_minutes: int = 120) -> bool:
        k = self._normalize_text(key).replace(" ", "_")[:48]
        v = str(value or "").strip()[:200]
        if not k or not v:
            return False
        expires = datetime.now() + timedelta(minutes=max(5, int(ttl_minutes)))
        data = self.get_memory()
        ctx = data.get("session_context", {})
        if not isinstance(ctx, dict):
            ctx = {}
        ctx[k] = {"value": v, "expires_at": expires.isoformat(timespec="seconds")}
        data["session_context"] = ctx
        return self.save_memory(data)

    def get_active_context(self) -> Dict[str, str]:
        data = self.get_memory()
        ctx = data.get("session_context", {})
        if not isinstance(ctx, dict):
            return {}
        now = datetime.now()
        active: Dict[str, str] = {}
        changed = False
        for k, item in list(ctx.items()):
            if not isinstance(item, dict):
                ctx.pop(k, None)
                changed = True
                continue
            exp = str(item.get("expires_at", "")).strip()
            val = str(item.get("value", "")).strip()
            if not exp or not val:
                ctx.pop(k, None)
                changed = True
                continue
            try:
                if datetime.fromisoformat(exp) < now:
                    ctx.pop(k, None)
                    changed = True
                    continue
            except Exception:
                ctx.pop(k, None)
                changed = True
                continue
            active[str(k)] = val
        if changed:
            data["session_context"] = ctx
            self.save_memory(data)
        return active

    def update_preferences_from_text(self, text: str) -> Dict[str, str]:
        low = self._normalize_text(text)
        updated: Dict[str, str] = {}
        if not low:
            return updated

        pref_patterns = [
            (r"\bprefiero\s+(.+)$", "preferencia_general"),
            (r"\bme gusta\s+(.+)$", "gusto_general"),
            (r"\bsiempre\s+responde\s+(.+)$", "estilo_respuesta"),
        ]
        for pat, key in pref_patterns:
            m = re.search(pat, low)
            if m:
                val = m.group(1).strip(" .,:;!?")
                if val and self.set_user_preference(key, val):
                    updated[key] = val

        if any(tok in low for tok in ("por ahora", "hoy ", "en esta sesion", "en esta sesión")):
            m_ctx = re.search(r"\b(?:por ahora|hoy|en esta sesion|en esta sesión)\s+(.+)$", low)
            if m_ctx:
                val = m_ctx.group(1).strip(" .,:;!?")
                if val and self.set_temporary_context("preferencia_temporal", val, ttl_minutes=180):
                    updated["preferencia_temporal"] = val
        return updated

    def remember_identity_answer(self, query: str) -> str:
        low = (query or "").strip().lower()
        profile = self.get_user_profile()
        name = str(profile.get("name", "")).strip()
        if any(k in low for k in ("cómo me llamo", "como me llamo", "mi nombre", "what is my name")) and name:
            return f"Te llamas {name}, señor."
        return ""

    def save(self, tag: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        text_clean = (text or "").strip()
        tag_clean = (tag or "general").strip().lower()
        if not text_clean:
            return
        with self._long_term_lock:
            with closing(sqlite3.connect(self.long_term_db_file)) as conn:
                conn.execute(
                    "INSERT INTO memories(tag,text,created_at,metadata_json) VALUES(?,?,?,?)",
                    (
                        tag_clean[:64],
                        text_clean[:3000],
                        datetime.now().isoformat(timespec="seconds"),
                        json.dumps(metadata or {}, ensure_ascii=False),
                    ),
                )
                conn.commit()

    def query(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        keywords = [w for w in self._extract_keywords(query) if len(w) >= 3][:5]
        if not keywords:
            keywords = [self._normalize_text(query)[:32]] if query.strip() else []
        if not keywords:
            return []
        where = " OR ".join(["lower(text) LIKE ? OR lower(tag) LIKE ?" for _ in keywords])
        params: list[str] = []
        for kw in keywords:
            like = f"%{kw.lower()}%"
            params.extend([like, like])
        sql = (
            "SELECT id,tag,text,created_at,metadata_json FROM memories "
            f"WHERE {where} ORDER BY created_at DESC LIMIT ?"
        )
        params.append(str(max(1, int(k))))
        out: list[dict[str, Any]] = []
        with self._long_term_lock:
            with closing(sqlite3.connect(self.long_term_db_file)) as conn:
                rows = conn.execute(sql, params).fetchall()
        for row_id, tag, text, created_at, metadata_json in rows:
            try:
                meta = json.loads(metadata_json) if metadata_json else {}
            except Exception:
                meta = {}
            out.append(
                {
                    "id": int(row_id),
                    "tag": str(tag),
                    "text": str(text),
                    "created_at": str(created_at),
                    "metadata": meta if isinstance(meta, dict) else {},
                }
            )
        return out

    def save_long_term_memory(self, user_text: str, assistant_text: str, *, tags: list[str] | None = None, importance: int = 1) -> None:
        merged = f"USER: {user_text}\nASSISTANT: {assistant_text}"
        self.save((tags or ["interaction"])[0], merged, metadata={"tags": tags or [], "importance": int(importance)})

    def search_long_term_memory(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        hits = self.query(query, k=limit)
        out: list[dict[str, Any]] = []
        for hit in hits:
            txt = str(hit.get("text", ""))
            parts = txt.split("\nASSISTANT:", 1)
            user_part = parts[0].replace("USER:", "").strip() if parts else txt
            asst_part = parts[1].strip() if len(parts) > 1 else txt
            out.append(
                {
                    "ts": hit.get("created_at", ""),
                    "user_text": user_part,
                    "assistant_text": asst_part,
                    "tags": hit.get("metadata", {}).get("tags", []),
                    "importance": hit.get("metadata", {}).get("importance", 1),
                }
            )
        return out

    def clear_session_history(self) -> bool:
        data = self.get_memory()
        data["history"] = []
        data["chat_history"] = []
        return self.save_memory(data)

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
        if not isinstance(normalized.get("user_preferences"), dict):
            normalized["user_preferences"] = {}
        if not isinstance(normalized.get("session_context"), dict):
            normalized["session_context"] = {}
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

            raw_data = self._load_memory_payload()
            normalized_data = self._normalize_memory_schema(raw_data)
            if normalized_data != raw_data:
                self._save_memory_payload(normalized_data)
                current_mtime = self.memory_file.stat().st_mtime if self.memory_file.exists() else current_mtime
            self._memory_cache = dict(normalized_data)
            self._memory_cache_mtime = current_mtime
            self._memory_cache_loaded_at = now
            return normalized_data

    def save_memory(self, memory_data: Dict[str, Any]) -> bool:
        with self._lock:
            normalized_data = self._normalize_memory_schema(memory_data)
            redacted = self._redact_memory_tree(normalized_data)
            saved = self._save_memory_payload(redacted)
            if saved:
                self._memory_cache = dict(redacted)
                self._memory_cache_mtime = self.memory_file.stat().st_mtime if self.memory_file.exists() else None
                self._memory_cache_loaded_at = time.time()
            return saved

    def create_memory_snapshot(self, label: str = "") -> Path | None:
        backup_dir = config.BACKUPS_DIR / "memory_snapshots"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", (label or "").strip())[:24]
        suffix = f"_{safe_label}" if safe_label else ""
        out = backup_dir / f"memory_snapshot_{stamp}{suffix}.zip"
        tmp = backup_dir / f".tmp_{stamp}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            files = [
                (self.memory_file, "memoria.json"),
                (self.user_profile_file, "user_profile.json"),
                (self.long_term_db_file, "long_term.db"),
            ]
            for src, name in files:
                if src.exists():
                    shutil.copy2(src, tmp / name)
            if not any((tmp / n).exists() for _s, n in files):
                return None
            zip_path = shutil.make_archive(str(out.with_suffix("")), "zip", root_dir=str(tmp))
            return Path(zip_path)
        except Exception:
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def list_memory_snapshots(self, limit: int = 20) -> list[Path]:
        backup_dir = config.BACKUPS_DIR / "memory_snapshots"
        if not backup_dir.exists():
            return []
        files = sorted(backup_dir.glob("memory_snapshot_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[: max(1, min(int(limit), 200))]

    def restore_memory_snapshot(self, snapshot_file: Path, sections: set[str] | None = None) -> bool:
        src = Path(snapshot_file)
        if not src.exists() or src.suffix.lower() != ".zip":
            return False
        temp = src.parent / f".restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        temp.mkdir(parents=True, exist_ok=True)
        try:
            shutil.unpack_archive(str(src), str(temp), "zip")
            requested = {s.strip().lower() for s in (sections or {"memory", "profile", "db"}) if s}
            mapping = [
                ("memory", temp / "memoria.json", self.memory_file),
                ("profile", temp / "user_profile.json", self.user_profile_file),
                ("db", temp / "long_term.db", self.long_term_db_file),
            ]
            restored = 0
            for key, origin, target in mapping:
                if key not in requested:
                    continue
                if not origin.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, target)
                restored += 1
            if restored == 0:
                return False
            self._memory_cache = None
            self._memory_cache_mtime = None
            self._memory_cache_loaded_at = 0.0
            return True
        except Exception:
            return False
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def compare_memory_snapshots(self, first: Path, second: Path) -> dict[str, Any]:
        a = Path(first)
        b = Path(second)
        if not a.exists() or not b.exists():
            return {"ok": False, "error": "snapshot_missing"}
        try:
            with zipfile.ZipFile(a, "r") as za, zipfile.ZipFile(b, "r") as zb:
                map_a = {i.filename: (int(i.file_size), int(i.CRC)) for i in za.infolist() if not i.is_dir()}
                map_b = {i.filename: (int(i.file_size), int(i.CRC)) for i in zb.infolist() if not i.is_dir()}
            names_a = set(map_a.keys())
            names_b = set(map_b.keys())
            added = sorted(list(names_b - names_a))
            removed = sorted(list(names_a - names_b))
            changed = sorted([n for n in names_a.intersection(names_b) if map_a.get(n) != map_b.get(n)])
            return {
                "ok": True,
                "added": added,
                "removed": removed,
                "changed": changed,
                "same": not added and not removed and not changed,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _derive_fernet(self) -> Any | None:
        seed = f"{Path.home()}::{config.APP_NAME}::{config.PROJECT_ROOT}".encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        key = base64.urlsafe_b64encode(digest)
        if Fernet is None:
            return _FallbackCipher(digest)
        try:
            return Fernet(key)
        except Exception:
            return _FallbackCipher(digest)

    def _load_memory_payload(self) -> Dict[str, Any]:
        raw = safe_json_load(self.memory_file, {})
        if not isinstance(raw, dict):
            raw = {}
        encrypted = raw.get("__encrypted__")
        if not encrypted:
            return raw
        fernet = self._derive_fernet()
        try:
            decrypted = fernet.decrypt(str(encrypted).encode("utf-8")).decode("utf-8")
            import json

            payload = json.loads(decrypted)
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            log.warning("[MEMORY] No pude descifrar memoria: %s", exc)
            # Fallback de recuperación para persistencia robusta: intentar copia .bak
            bak = self.memory_file.with_suffix(self.memory_file.suffix + ".bak")
            backup_raw = safe_json_load(bak, {})
            if isinstance(backup_raw, dict):
                backup_encrypted = backup_raw.get("__encrypted__")
                if backup_encrypted:
                    try:
                        decrypted = fernet.decrypt(str(backup_encrypted).encode("utf-8")).decode("utf-8")
                        payload = json.loads(decrypted)
                        if isinstance(payload, dict):
                            log.info("[MEMORY] Recuperé memoria desde backup .bak.")
                            return payload
                    except Exception:
                        pass
                elif backup_raw:
                    log.info("[MEMORY] Recuperé memoria en claro desde backup .bak.")
                    return backup_raw
            return {}

    def _save_memory_payload(self, data: Dict[str, Any]) -> bool:
        # Copia de seguridad incremental para recuperación ante cortes/corrupción.
        bak = self.memory_file.with_suffix(self.memory_file.suffix + ".bak")
        try:
            if self.memory_file.exists():
                shutil.copy2(self.memory_file, bak)
        except Exception:
            pass
        fernet = self._derive_fernet()
        try:
            import json

            token = fernet.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("utf-8")
            return safe_json_save(self.memory_file, {"__encrypted__": token, "schema": "fernet-v1"})
        except Exception as exc:
            log.warning("[MEMORY] Falló cifrado, guardando en claro: %s", exc)
            return safe_json_save(self.memory_file, data)

    def _redact_memory_tree(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self._redact_memory_tree(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_memory_tree(v) for v in value]
        if isinstance(value, str):
            return redact_sensitive_data(value)
        return value

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

    def persist_interaction(
        self,
        user_text: str,
        assistant_text: str,
        *,
        intent: str,
        entity: str,
        record_behavior: bool = True,
    ) -> bool:
        """Persiste interacción y evento en una sola escritura de memoria."""
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

        if record_behavior and not self._contains_sensitive_data(user_text):
            events = data.get("behavior_events", [])
            if not isinstance(events, list):
                events = []
            events.append(
                {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "intent": (intent or "chat")[:48],
                    "entity": (entity or "")[:120],
                    "preview": (user_text or "").strip()[:240],
                }
            )
            max_e = max(20, int(getattr(config, "BEHAVIOR_EVENTS_MAX", 250)))
            data["behavior_events"] = events[-max_e:]
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

    def _embed_text(self, text: str) -> Dict[str, float]:
        """Embedding liviano por hash de tokens (sin FAISS, RAM-friendly)."""
        tokens = self._extract_keywords(text)
        if not tokens:
            return {}
        vec: Dict[str, float] = {}
        for token in tokens:
            key = hashlib.md5(token.encode("utf-8")).hexdigest()[:8]
            vec[key] = vec.get(key, 0.0) + 1.0
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    @staticmethod
    def _cosine_sparse(a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(k, 0.0) for k, v in a.items())

    def _rebuild_vector_index(self, kb: Dict[str, Any]) -> None:
        self._vector_index = {}
        for topic, entry in kb.items():
            if not isinstance(entry, dict):
                continue
            text = f"{entry.get('question', '')} {entry.get('answer', '')}"
            self._vector_index[str(topic)] = self._embed_text(text)

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
            "question": redact_sensitive_data((question or "").strip()),
            "answer": redact_sensitive_data((answer or "").strip()),
            "learned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
        }
        # Compactación semántica básica: si tema muy similar existe, fusiona.
        for topic, entry in list(kb.items()):
            if topic == inferred_topic or not isinstance(entry, dict):
                continue
            sim = self._cosine_sparse(
                self._embed_text(f"{entry.get('question', '')} {entry.get('answer', '')}"),
                self._embed_text(f"{question} {answer}"),
            )
            if sim >= 0.92:
                merged = f"{entry.get('answer', '')}\n\nResumen consolidado: {answer}".strip()
                kb[topic]["answer"] = merged[:2000]
                kb.pop(inferred_topic, None)
                if inferred_topic in order:
                    order.remove(inferred_topic)
                inferred_topic = topic
                break

        if inferred_topic in order:
            order.remove(inferred_topic)
        order.append(inferred_topic)

        while len(order) > self.knowledge_limit:
            oldest = order.pop(0)
            kb.pop(oldest, None)

        data["knowledge_base"] = kb
        data["knowledge_order"] = order
        self._rebuild_vector_index(kb)
        return self.save_memory(data)

    def search_knowledge(self, query: str) -> Dict[str, Any] | None:
        """Busca una coincidencia semántica simple en knowledge_base."""
        data = self.get_memory()
        kb = data.get("knowledge_base", {})
        if not kb:
            return None
        if not self._vector_index:
            self._rebuild_vector_index(kb)

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
            query_vec = self._embed_text(query)
            best_topic_vec = ""
            best_sim = 0.0
            for topic, vec in self._vector_index.items():
                sim = self._cosine_sparse(query_vec, vec)
                if sim > best_sim:
                    best_sim = sim
                    best_topic_vec = topic
            if best_topic_vec and best_sim >= 0.45:
                entry = kb.get(best_topic_vec, {})
                return {
                    "topic": best_topic_vec,
                    "question": entry.get("question", ""),
                    "answer": entry.get("answer", ""),
                    "learned_at": entry.get("learned_at", ""),
                    "source": entry.get("source", "web_search"),
                    "score": round(best_sim, 3),
                }
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

    def run_maintenance(self, days_to_keep_logs: int = 30) -> Dict[str, Any]:
        """Limpieza periódica para evitar degradación en sesiones largas."""
        report: Dict[str, Any] = {"logs_removed": 0, "history_trimmed": False, "old_records_purged": 0}
        try:
            data = self.get_memory()
            history = data.get("history", [])
            chat = data.get("chat_history", [])
            if isinstance(history, list) and len(history) > 200:
                data["history"] = history[-120:]
                report["history_trimmed"] = True
            if isinstance(chat, list) and len(chat) > 400:
                data["chat_history"] = chat[-300:]
                report["history_trimmed"] = True
            if report["history_trimmed"]:
                self.save_memory(data)
            cutoff = datetime.now() - timedelta(days=30)
            filtered_history = []
            for item in data.get("history", []):
                if not isinstance(item, dict):
                    continue
                ts = str(item.get("ts", ""))
                try:
                    if datetime.fromisoformat(ts) < cutoff:
                        report["old_records_purged"] = int(report["old_records_purged"]) + 1
                        continue
                except Exception:
                    pass
                filtered_history.append(item)
            if len(filtered_history) != len(data.get("history", [])):
                data["history"] = filtered_history[-120:]
                self.save_memory(data)
        except Exception:
            pass

        try:
            now = datetime.now()
            logs_dir = Path(config.LOGS_DIR)
            if logs_dir.exists():
                for p in logs_dir.glob("*.log"):
                    try:
                        age = now - datetime.fromtimestamp(p.stat().st_mtime)
                        if age > timedelta(days=max(1, int(days_to_keep_logs))):
                            p.unlink(missing_ok=True)
                            report["logs_removed"] = int(report.get("logs_removed", 0)) + 1
                    except Exception:
                        continue
        except Exception:
            pass
        return report
