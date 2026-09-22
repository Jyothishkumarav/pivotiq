from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Search for .env in the repo root (preferred) and the backend/ folder as fallback.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILES = (_REPO_ROOT / ".env", _REPO_ROOT / "backend" / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017/pivotiq"
    mongo_db_name: str = "pivotiq"
    redis_url: str | None = None  # e.g. redis://redis:6379/0; used by app.services.cache

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    google_client_id: str = ""
    allow_dev_login: bool = True

    fyers_app_id: str = ""
    fyers_secret: str = ""
    fyers_redirect_uri: str = "https://trade.fyers.in/api-login/redirect-uri/index.html"

    cors_origins: list[str] = ["*"]

    notification_service_url: str = "http://localhost:4100"
    notification_service_enabled: bool = False
    notification_channels: list[str] = ["telegram"]
    notification_telegram_chat_id: str = ""
    notification_enabled_strategies: list[str] = ["orb_flow", "orb_pullback_support", "orb_pullback"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
