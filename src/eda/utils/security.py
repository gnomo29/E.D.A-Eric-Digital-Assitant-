"""Controles Zero-Trust para entrada, comandos y datos sensibles."""

from __future__ import annotations

import re
import shlex
import base64
import hashlib
from pathlib import Path
import json
from dataclasses import dataclass
from typing import Iterable
from hmac import compare_digest

try:
    from cryptography.fernet import Fernet
except Exception:
    Fernet = None  # type: ignore[assignment]

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
except Exception:
    hashes = None  # type: ignore[assignment]
    serialization = None  # type: ignore[assignment]
    ed25519 = None  # type: ignore[assignment]

SHELL_META_PATTERN = re.compile(r"[;&|`$<>]")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")
API_KEY_PATTERN = re.compile(r"\b(?:sk|api|tok|key)[_-]?[a-z0-9]{10,}\b", re.IGNORECASE)
PASSWORD_ASSIGN_PATTERN = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*([^\s,;]+)"
)
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]{12,}")

SAFE_TOKEN_PATTERN = re.compile(r"^[a-zA-Z0-9_./:=+\-\\]+$")

DEFAULT_ALLOWED_COMMANDS = {
    "dir",
    "echo",
    "cd",
    "type",
    "copy",
    "move",
    "mkdir",
    "python",
    "pip",
    "where",
    "tasklist",
    "ipconfig",
}


@dataclass
class ValidationResult:
    allowed: bool
    sanitized: str
    reason: str = ""


def _derive_local_key(label: str = "eda_local") -> bytes:
    seed = f"{label}::{Path.home()}".encode("utf-8")
    return hashlib.sha256(seed).digest()


def encrypt_secret(plain_text: str, *, label: str = "eda_secret") -> str:
    content = (plain_text or "").encode("utf-8")
    key = _derive_local_key(label)
    if Fernet is not None:
        token_key = base64.urlsafe_b64encode(key)
        token = Fernet(token_key).encrypt(content)
        return token.decode("utf-8")
    xored = bytes(content[i] ^ key[i % len(key)] for i in range(len(content)))
    return base64.urlsafe_b64encode(xored).decode("utf-8")


def decrypt_secret(cipher_text: str, *, label: str = "eda_secret") -> str:
    raw = (cipher_text or "").encode("utf-8")
    key = _derive_local_key(label)
    if Fernet is not None:
        token_key = base64.urlsafe_b64encode(key)
        return Fernet(token_key).decrypt(raw).decode("utf-8")
    data = base64.urlsafe_b64decode(raw)
    plain = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
    return plain.decode("utf-8")


def redact_sensitive_data(text: str) -> str:
    """Redacta PII/secretos frecuentes en cualquier string."""
    content = text or ""
    content = EMAIL_PATTERN.sub("[REDACTED]", content)
    content = API_KEY_PATTERN.sub("[REDACTED]", content)
    content = PASSWORD_ASSIGN_PATTERN.sub(r"\1=[REDACTED]", content)
    content = BEARER_PATTERN.sub("Bearer [REDACTED]", content)
    return content


def sanitize_user_input(text: str, max_len: int = 512) -> ValidationResult:
    raw = (text or "").strip()
    if not raw:
        return ValidationResult(False, "", "input vacío")
    clipped = raw[:max_len]
    if SHELL_META_PATTERN.search(clipped):
        return ValidationResult(False, clipped, "caracteres de inyección detectados")
    safe = redact_sensitive_data(clipped)
    return ValidationResult(True, safe, "")


def validate_shell_command(command: str, allowed_commands: Iterable[str] | None = None) -> ValidationResult:
    """Valida comando shell con whitelist estricta y sin metacaracteres."""
    base = (command or "").strip()
    if not base:
        return ValidationResult(False, "", "comando vacío")
    if SHELL_META_PATTERN.search(base):
        return ValidationResult(False, base, "metacaracter bloqueado")
    try:
        parts = shlex.split(base, posix=False)
    except Exception:
        return ValidationResult(False, base, "formato inválido")
    if not parts:
        return ValidationResult(False, base, "comando vacío")
    cmd = parts[0].lower()
    allow = {c.lower() for c in (allowed_commands or DEFAULT_ALLOWED_COMMANDS)}
    if cmd not in allow:
        return ValidationResult(False, base, f"comando no permitido: {cmd}")
    for token in parts[1:]:
        if not SAFE_TOKEN_PATTERN.match(token):
            return ValidationResult(False, base, f"argumento no seguro: {token}")
    return ValidationResult(True, " ".join(parts), "")


def sanitize_app_target(target: str) -> ValidationResult:
    """Sanitiza nombres de apps/url target evitando inyección."""
    raw = (target or "").strip()
    if not raw:
        return ValidationResult(False, "", "objetivo vacío")
    if SHELL_META_PATTERN.search(raw):
        return ValidationResult(False, raw, "objetivo contiene metacaracteres")
    if not re.fullmatch(r"[a-zA-Z0-9_ ./:\\-]+", raw):
        return ValidationResult(False, raw, "objetivo contiene caracteres no permitidos")
    return ValidationResult(True, raw[:260], "")


def generate_skill_keypair(private_key_path: Path, public_key_path: Path) -> None:
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    if ed25519 is None or serialization is None:
        seed = base64.urlsafe_b64encode(_derive_local_key("eda_skill_signing"))
        private_key_path.write_text(seed.decode("utf-8"), encoding="utf-8")
        public_key_path.write_text(seed.decode("utf-8"), encoding="utf-8")
        return
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_key_path.write_bytes(private_bytes)
    public_key_path.write_bytes(public_bytes)


def sign_file(path: Path, private_key_path: Path) -> str:
    content = path.read_bytes()
    if ed25519 is None or serialization is None:
        key = private_key_path.read_text(encoding="utf-8").encode("utf-8")
        digest = hashlib.sha256(key + content).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8")
    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    signature = private_key.sign(content)
    return base64.urlsafe_b64encode(signature).decode("utf-8")


def verify_file_signature(path: Path, signature_b64: str, public_key_path: Path) -> bool:
    content = path.read_bytes()
    try:
        signature = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
    except Exception:
        return False
    if ed25519 is None or serialization is None:
        key = public_key_path.read_text(encoding="utf-8").encode("utf-8")
        digest = hashlib.sha256(key + content).digest()
        return compare_digest(digest, signature)
    try:
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        public_key.verify(signature, content)
        return True
    except Exception:
        return False


def load_signatures(signatures_path: Path) -> dict:
    try:
        return json.loads(signatures_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

