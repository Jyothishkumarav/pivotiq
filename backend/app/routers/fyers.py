from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.services import fyers_client
from app.services.fyers_client import FyersError

router = APIRouter(prefix="/fyers", tags=["fyers"], dependencies=[Depends(get_current_user)])


class LoginUrlOut(BaseModel):
    url: str
    state: str


class ExchangeCodeIn(BaseModel):
    authCode: str
    state: str | None = None


class ConnectionStatusOut(BaseModel):
    connected: bool
    connectedAt: datetime | None = None
    expiresAt: datetime | None = None
    profileName: str | None = None


def _cred_query(user_id: ObjectId) -> dict:
    return {"userId": user_id}


async def _get_cred(user_id: ObjectId) -> dict | None:
    return await get_db().fyers_credentials.find_one(_cred_query(user_id))


async def _require_access_token(user_id: ObjectId) -> str:
    cred = await _get_cred(user_id)
    if not cred or not cred.get("accessToken"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Fyers is not connected for this user.")
    expires_at = cred.get("expiresAt")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Fyers session expired. Reconnect.")
    return cred["accessToken"]


@router.get("/auth-url", response_model=LoginUrlOut)
async def get_auth_url(current_user: dict = Depends(get_current_user)) -> LoginUrlOut:
    state = token_urlsafe(24)
    try:
        url = fyers_client.build_login_url(state)
    except FyersError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # Stash the state on the user so we can validate the round-trip.
    await get_db().users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"fyersLoginState": {"value": state, "issuedAt": datetime.now(timezone.utc)}}},
    )
    return LoginUrlOut(url=url, state=state)


@router.post("/exchange-code", response_model=ConnectionStatusOut)
async def exchange_code(payload: ExchangeCodeIn, current_user: dict = Depends(get_current_user)) -> ConnectionStatusOut:
    db = get_db()

    # Optional state check — Fyers' hosted redirect URI doesn't preserve state
    # cleanly so we only enforce it when the client actually sends one back.
    expected_state = (current_user.get("fyersLoginState") or {}).get("value")
    if payload.state and expected_state and payload.state != expected_state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State mismatch")

    try:
        tokens = fyers_client.exchange_auth_code(payload.authCode)
    except FyersError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    now = datetime.now(timezone.utc)
    # Fyers issues a JWT whose `exp` claim is the real expiry (~06:00 IST next).
    # Fall back to a conservative 12h if we can't parse it.
    expires_at = fyers_client.parse_access_token_expiry(access_token) or (
        now + timedelta(hours=12)
    )

    profile_name: str | None = None
    try:
        profile = fyers_client.get_profile(access_token)
        profile_name = (profile.get("data") or {}).get("name")
    except FyersError:
        # Profile lookup is a nice-to-have; don't block the connection if it hiccups.
        pass

    await db.fyers_credentials.update_one(
        {"userId": current_user["_id"]},
        {
            "$set": {
                "accessToken": access_token,
                "refreshToken": refresh_token,
                "connectedAt": now,
                "expiresAt": expires_at,
                "profileName": profile_name,
            },
            "$setOnInsert": {"createdAt": now, "userId": current_user["_id"]},
        },
        upsert=True,
    )
    return ConnectionStatusOut(connected=True, connectedAt=now, expiresAt=expires_at, profileName=profile_name)


@router.get("/status", response_model=ConnectionStatusOut)
async def get_status(current_user: dict = Depends(get_current_user)) -> ConnectionStatusOut:
    cred = await _get_cred(current_user["_id"])
    if not cred:
        return ConnectionStatusOut(connected=False)
    expires_at = cred.get("expiresAt")
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    is_valid = bool(cred.get("accessToken")) and (expires_at is None or expires_at > datetime.now(timezone.utc))
    return ConnectionStatusOut(
        connected=is_valid,
        connectedAt=cred.get("connectedAt"),
        expiresAt=expires_at,
        profileName=cred.get("profileName"),
    )


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(current_user: dict = Depends(get_current_user)) -> None:
    await get_db().fyers_credentials.delete_one({"userId": current_user["_id"]})


@router.get("/holdings")
async def holdings(current_user: dict = Depends(get_current_user)) -> dict:
    token = await _require_access_token(current_user["_id"])
    try:
        return fyers_client.get_holdings(token)
    except FyersError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/positions")
async def positions(current_user: dict = Depends(get_current_user)) -> dict:
    token = await _require_access_token(current_user["_id"])
    try:
        return fyers_client.get_positions(token)
    except FyersError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/funds")
async def funds(current_user: dict = Depends(get_current_user)) -> dict:
    token = await _require_access_token(current_user["_id"])
    try:
        return fyers_client.get_funds(token)
    except FyersError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
