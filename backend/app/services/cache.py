"""Generic Redis-backed key/value cache with an in-memory fallback.

Any service that needs a lightweight "get/set with TTL" cache (dedup flags,
short-lived computed results, etc.) should depend on `get_cache_client()`
instead of rolling its own dict. It transparently degrades to an in-process
store when Redis is not configured or unreachable (e.g. local dev without
Docker), so callers never have to special-case that.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


class _InMemoryBackend:
    """Fallback store used when Redis is not configured or unreachable."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        now = time.time()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if now >= expires_at:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl_seconds, value)

    def exists(self, key: str) -> bool:
        return self.get(key) is not None


class CacheClient:
    """Thin key-value cache facade backed by Redis, with in-memory fallback."""

    def __init__(self) -> None:
        self._redis = None
        self._fallback = _InMemoryBackend()
        settings = get_settings()
        if settings.redis_url:
            try:
                import redis  # optional dependency; only imported when configured

                self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
                self._redis.ping()
                logger.info("cache: connected to Redis at %s", settings.redis_url)
            except Exception:
                logger.exception("cache: failed to connect to Redis, falling back to in-memory cache")
                self._redis = None

    def get(self, key: str) -> str | None:
        if self._redis is not None:
            try:
                return self._redis.get(key)
            except Exception:
                logger.exception("cache: Redis GET failed for key=%s, falling back", key)
        return self._fallback.get(key)

    def get_json(self, key: str) -> Any | None:
        raw = self.get(key)
        return json.loads(raw) if raw is not None else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        if self._redis is not None:
            try:
                self._redis.set(key, value, ex=ttl_seconds)
                return
            except Exception:
                logger.exception("cache: Redis SET failed for key=%s, falling back", key)
        self._fallback.set(key, value, ttl_seconds)

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.set(key, json.dumps(value), ttl_seconds)

    def exists(self, key: str) -> bool:
        if self._redis is not None:
            try:
                return bool(self._redis.exists(key))
            except Exception:
                logger.exception("cache: Redis EXISTS failed for key=%s, falling back", key)
        return self._fallback.exists(key)


_client: CacheClient | None = None
_client_lock = threading.Lock()


def get_cache_client() -> CacheClient:
    """Process-wide singleton; safe to call from any service/router."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = CacheClient()
    return _client
