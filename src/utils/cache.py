from __future__ import annotations

import time
from typing import Generic, TypeVar


T = TypeVar("T")


class TTLCache(Generic[T]):
    """A simple in-process time-to-live cache keyed by string.

    Entries are evicted lazily on the next ``get`` after their TTL expires.
    All reads and writes are O(1).  Not thread-safe; safe for single-threaded
    asyncio event-loop usage.

    Type parameter ``T`` is the value type stored in the cache.
    """

    def __init__(self, ttl_seconds: int) -> None:
        """Initialise the cache.

        Args:
            ttl_seconds: How long entries live before they are considered
                stale.  A value of 0 would effectively disable caching.
        """
        self._ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        """Return the cached value for *key*, or ``None`` if absent or expired.

        If the entry exists but has passed its TTL it is deleted immediately
        so that stale data cannot be returned on a later call.

        Args:
            key: The cache key to look up.

        Returns:
            The cached value, or ``None``.
        """
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.time():
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: T) -> None:
        """Store *value* under *key* with a TTL of ``ttl_seconds``.

        Overwrites any existing entry for the same key.

        Args:
            key:   The cache key.
            value: The value to store.
        """
        self._store[key] = (time.time() + self._ttl_seconds, value)
