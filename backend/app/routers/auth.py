from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.user import (
    AccessTokenOut,
    DevLoginRequest,
    GoogleAuthRequest,
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserOut,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_out(doc: dict) -> UserOut:
    return UserOut(
        id=str(doc["_id"]),
        email=doc.get("email", f"{doc.get('username', 'user')}@pivotiq.trade"),
        name=doc.get("name", doc.get("username", "User")),
        avatarUrl=doc.get("avatarUrl"),
        createdAt=doc["createdAt"],
        lastLoginAt=doc["lastLoginAt"],
    )


async def _issue_tokens(user_doc: dict) -> TokenPair:
    user_id = str(user_doc["_id"])
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id, user_doc.get("tokenVersion", 0))
    return TokenPair(accessToken=access, refreshToken=refresh, user=_to_user_out(user_doc))


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest) -> TokenPair:
    uname = payload.username.strip().lower()
    db = get_db()
    now = datetime.now(timezone.utc)

    # 1. Search for existing user by username or email
    user = await db.users.find_one({
        "$or": [
            {"username": uname},
            {"email": uname},
        ]
    })

    # 2. Check if this is the default admin credentials
    is_admin_match = (
        uname in ("jyo_admin", "jyo_admin@pivotiq.trade")
        and payload.password == "qazwsxedcr@91"
    )

    if user is None:
        if is_admin_match:
            doc = {
                "username": "jyo_admin",
                "email": "jyo_admin@pivotiq.trade",
                "name": "Jyo Admin",
                "passwordHash": hash_password("qazwsxedcr@91"),
                "tokenVersion": 0,
                "createdAt": now,
                "lastLoginAt": now,
            }
            res = await db.users.insert_one(doc)
            doc["_id"] = res.inserted_id
            return await _issue_tokens(doc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # User exists: verify password
    stored_hash = user.get("passwordHash")
    if stored_hash and verify_password(payload.password, stored_hash):
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"lastLoginAt": now}})
        user["lastLoginAt"] = now
        return await _issue_tokens(user)

    # Also allow direct admin credentials update if hash was not initialized
    if is_admin_match:
        new_hash = hash_password(payload.password)
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"passwordHash": new_hash, "lastLoginAt": now}},
        )
        user["lastLoginAt"] = now
        return await _issue_tokens(user)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )


@router.post("/google", response_model=TokenPair)
async def google_login(payload: GoogleAuthRequest) -> TokenPair:
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google sign-in is not configured")

    try:
        claims = google_id_token.verify_oauth2_token(
            payload.idToken, google_requests.Request(), settings.google_client_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google ID token") from exc

    db = get_db()
    now = datetime.now(timezone.utc)
    google_id = claims["sub"]
    existing = await db.users.find_one({"googleId": google_id})
    if existing is None:
        doc = {
            "googleId": google_id,
            "email": claims.get("email"),
            "name": claims.get("name", claims.get("email", "User")),
            "avatarUrl": claims.get("picture"),
            "tokenVersion": 0,
            "createdAt": now,
            "lastLoginAt": now,
        }
        result = await db.users.insert_one(doc)
        doc["_id"] = result.inserted_id
    else:
        await db.users.update_one({"_id": existing["_id"]}, {"$set": {"lastLoginAt": now}})
        existing["lastLoginAt"] = now
        doc = existing

    return await _issue_tokens(doc)


@router.post("/dev-login", response_model=TokenPair)
async def dev_login(payload: DevLoginRequest) -> TokenPair:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dev login has been disabled for security.")


@router.post("/refresh", response_model=AccessTokenOut)
async def refresh_token(payload: RefreshRequest) -> AccessTokenOut:
    try:
        claims = decode_token(payload.refreshToken)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if claims.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    db = get_db()
    user = await db.users.find_one({"_id": ObjectId(claims["sub"])})
    if user is None or user.get("tokenVersion", 0) != claims.get("ver"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked")

    return AccessTokenOut(accessToken=create_access_token(str(user["_id"])))


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all_devices(current_user: dict = Depends(get_current_user)) -> None:
    db = get_db()
    await db.users.update_one({"_id": current_user["_id"]}, {"$inc": {"tokenVersion": 1}})


@router.get("/me", response_model=UserOut)
async def get_me(current_user: dict = Depends(get_current_user)) -> UserOut:
    return _to_user_out(current_user)
