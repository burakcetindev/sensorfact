from __future__ import annotations

import time
from typing import Generic, TypeVar


T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.time():
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: T) -> None:
        self._store[key] = (time.time() + self._ttl_seconds, value)
