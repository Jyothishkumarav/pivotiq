"""Central configuration, sourced from environment variables / .env.

Kept as a single Settings object (pydantic-settings) so every module reads
config the same way, and so swapping the queue backend later (RabbitMQ,
Kafka, ...) only means adding new fields here, not touching call sites.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 4500
    log_level: str = "INFO"

    queue_max_size: int = 1000
    worker_thread_pool_size: int = 8

    telegram_bot_token: str = ""
    telegram_api_base_url: str = "https://api.telegram.org"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
