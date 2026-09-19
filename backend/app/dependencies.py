from datetime import datetime, timezone

from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import get_db
from app.security import decode_token
from app.services.market_context import get_active_fyers_token, set_current_fyers_token

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    db = get_db()
    user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def with_fyers_context(current_user: dict = Depends(get_current_user)) -> dict:
    """Fetches the current user's Fyers token (if connected) and stashes it in a
    ContextVar so downstream sync market-data calls automatically use Fyers."""
    token = await get_active_fyers_token(current_user["_id"])
    set_current_fyers_token(token)
    return current_user
