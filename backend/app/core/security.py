"""Authentication (JWT), password hashing, credential encryption, RBAC helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings

_PBKDF2_ITERATIONS = 310_000
_JWT_ALGORITHMS = {"HS256", "HS384", "HS512", "RS256", "ES256"}


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- JWT
def create_access_token(
    user_id: uuid.UUID | str, role: str, settings: Settings | None = None
) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "iss": "prism-ai",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if settings.jwt_algorithm not in _JWT_ALGORITHMS:
        raise ValueError("unsupported JWT algorithm")
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# ---------------------------------------------------------------- credential encryption (at rest)
def _fernet(settings: Settings) -> Fernet:
    key_b64 = settings.credential_encryption_key
    if key_b64:
        return Fernet(key_b64.encode())
    # Dev fallback: derive a deterministic key from the JWT secret so that dev
    # setups work without extra config. Production MUST set the env var.
    digest = hashlib.sha256(("prism-credentials:" + settings.jwt_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str, settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    try:
        return _fernet(settings).decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None


def new_opaque_id() -> str:
    return secrets.token_urlsafe(12)


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
