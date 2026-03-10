"""Unit tests for TTLCache."""
from __future__ import annotations

import time

import pytest

from src.utils.cache import TTLCache


class TestTTLCacheBasicOperations:
    """Tests for set/get round-trip behaviour."""

    def test_get_returns_none_for_missing_key(self):
        """A fresh cache returns None for any key."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_set_then_get_returns_value(self):
        """A value stored with set is retrievable with get."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_set_overwrites_existing_entry(self):
        """Calling set twice on the same key replaces the value."""
        cache: TTLCache[int] = TTLCache(ttl_seconds=60)
        cache.set("k", 1)
        cache.set("k", 2)
        assert cache.get("k") == 2

    def test_different_keys_are_independent(self):
        """Setting one key does not affect a different key."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        cache.set("a", "alpha")
        cache.set("b", "beta")
        assert cache.get("a") == "alpha"
        assert cache.get("b") == "beta"

    def test_none_value_is_storable(self):
        """None is a valid stored value — get returns it as-is before TTL."""
        cache: TTLCache[None] = TTLCache(ttl_seconds=60)
        cache.set("k", None)
        # We can't distinguish stored-None from cache-miss via the API —
        # this is a known limitation documented in the class.
        # The test simply confirms no exception is raised.

    def test_stores_complex_objects(self):
        """Dicts and lists are stored and returned by identity."""
        cache: TTLCache[dict] = TTLCache(ttl_seconds=60)
        payload = {"hash": "abc", "height": 42}
        cache.set("block", payload)
        assert cache.get("block") is payload


class TestTTLCacheExpiry:
    """Tests for TTL-based eviction."""

    def test_expired_entry_returns_none(self, monkeypatch):
        """An entry is evicted and None returned once its TTL has elapsed."""
        now = time.time()
        cache: TTLCache[str] = TTLCache(ttl_seconds=10)
        cache.set("k", "v")

        # Advance time past the TTL
        monkeypatch.setattr(time, "time", lambda: now + 20)
        assert cache.get("k") is None

    def test_expired_entry_is_deleted_from_store(self, monkeypatch):
        """An expired entry is removed from the internal store on access."""
        now = time.time()
        cache: TTLCache[str] = TTLCache(ttl_seconds=10)
        cache.set("k", "v")

        monkeypatch.setattr(time, "time", lambda: now + 20)
        cache.get("k")  # triggers eviction
        # Re-patching time to "now" won't bring it back
        assert "k" not in cache._store

    def test_entry_still_valid_just_before_expiry(self, monkeypatch):
        """An entry is still returned when time is just below TTL."""
        now = time.time()
        cache: TTLCache[str] = TTLCache(ttl_seconds=10)
        monkeypatch.setattr(time, "time", lambda: now)
        cache.set("k", "v")

        # Advance to 1 second before expiry
        monkeypatch.setattr(time, "time", lambda: now + 9)
        assert cache.get("k") == "v"

    def test_ttl_zero_entries_expire_immediately(self, monkeypatch):
        """A TTL of 0 means entries expire as soon as the clock advances at all."""
        now = time.time()
        monkeypatch.setattr(time, "time", lambda: now)
        cache: TTLCache[str] = TTLCache(ttl_seconds=0)
        cache.set("k", "v")

        monkeypatch.setattr(time, "time", lambda: now + 0.001)
        assert cache.get("k") is None

    def test_fresh_set_after_expiry_is_retrievable(self, monkeypatch):
        """After expiry a new set on the same key creates a fresh valid entry."""
        now = time.time()
        monkeypatch.setattr(time, "time", lambda: now)
        cache: TTLCache[str] = TTLCache(ttl_seconds=5)
        cache.set("k", "old")

        # Expire the old entry
        monkeypatch.setattr(time, "time", lambda: now + 10)
        assert cache.get("k") is None

        # Re-insert
        cache.set("k", "new")
        assert cache.get("k") == "new"
