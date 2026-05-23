import json
from typing import Any, Optional

from core.config import settings


class CacheService:
    def __init__(self):
        self.enabled = bool(settings.REDIS_URL)
        self._client = None

    @property
    def client(self):
        if self._client is None and self.enabled:
            import redis

            self._client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._client

    def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        try:
            data = self.client.get(key)
            return json.loads(data) if data else None
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int = 300):
        if not self.enabled:
            return
        try:
            self.client.setex(key, ttl, json.dumps(value, default=str))
        except Exception:
            pass

    def delete(self, key: str):
        if not self.enabled:
            return
        try:
            self.client.delete(key)
        except Exception:
            pass

    def delete_pattern(self, pattern: str):
        """Delete all keys matching pattern"""
        if not self.enabled:
            return
        try:
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
        except Exception:
            pass


cache = CacheService()
