"""Runtime helpers used by routers."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone

from bson import ObjectId

from app.database import get_db

# Per-request Fyers access token. Set by the `fyers_context` FastAPI dependency;
# read by market_data facade so sync helpers (position/holding computation,
# watchlist row enrichment) automatically use Fyers when the caller is connected.
_current_fyers_token: ContextVar[str | None] = ContextVar("fyers_token", default=None)


def current_fyers_token() -> str | None:
    return _current_fyers_token.get()


def set_current_fyers_token(token: str | None) -> None:
    _current_fyers_token.set(token)


async def get_active_fyers_token(user_id: ObjectId) -> str | None:
    """Return the user's Fyers access token if the session is still valid, else None."""
    cred = await get_db().fyers_credentials.find_one({"userId": user_id})
    if not cred:
        return None
    token = cred.get("accessToken")
    if not token:
        return None
    expires_at = cred.get("expiresAt")
    if expires_at is not None:
        # MongoDB stores naive datetimes; normalize to UTC-aware for comparison.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None
    return token
