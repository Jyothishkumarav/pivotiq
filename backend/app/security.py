import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt

from app.config import get_settings

TokenType = Literal["access", "refresh"]

_SALT = "pivotiq_secure_salt_2026"


def hash_password(password: str) -> str:
    return hashlib.sha256(f"{_SALT}:{password}".encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hmac.compare_digest(hash_password(plain_password), hashed_password)


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta, extra_claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    return _create_token(user_id, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(user_id: str, token_version: int) -> str:
    settings = get_settings()
    return _create_token(
        user_id,
        "refresh",
        timedelta(days=settings.refresh_token_expire_days),
        {"ver": token_version},
    )


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
