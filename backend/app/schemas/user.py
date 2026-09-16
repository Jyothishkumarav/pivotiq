from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    avatarUrl: str | None = None
    createdAt: datetime
    lastLoginAt: datetime


class GoogleAuthRequest(BaseModel):
    idToken: str


class DevLoginRequest(BaseModel):
    name: str = "Demo User"
    email: EmailStr = "demo@pivotiq.dev"


class TokenPair(BaseModel):
    accessToken: str
    refreshToken: str
    user: UserOut


class RefreshRequest(BaseModel):
    refreshToken: str


class AccessTokenOut(BaseModel):
    accessToken: str
