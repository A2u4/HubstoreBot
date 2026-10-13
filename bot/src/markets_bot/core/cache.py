"""Small TTL + LRU cache. Every cache is bounded so long-running bots don't leak memory."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import TypeVar

V = TypeVar("V")


class TtlCache[V]:
    def __init__(self, ttl_seconds: float, max_size: int = 500) -> None:
        if ttl_seconds <= 0 or max_size <= 0:
            raise ValueError("ttl_seconds and max_size must be positive")
        self._ttl = ttl_seconds
        self._max = max_size
        self._store: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> V | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: V, ttl_seconds: float | None = None) -> None:
        if key in self._store:
            del self._store[key]
        elif len(self._store) >= self._max:
            self._store.popitem(last=False)
        self._store[key] = (time.monotonic() + (ttl_seconds or self._ttl), value)

    def claim(self, key: str) -> bool:
        """Set ``key`` if absent. Returns False when it was already present (dedupe helper)."""
        if self.get(key) is not None:
            return False
        self.set(key, True)  # type: ignore[arg-type]
        return True

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
