"""In-memory TTL cache that keeps the original fetch time with every value."""
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    fetched_at: datetime   # when the live API call was made
    expires_at: float      # monotonic seconds


class TTLCache:
    def __init__(self, clock=time.monotonic):
        self._store: dict[str, CacheEntry] = {}
        self._clock = clock

    def get(self, key: str) -> CacheEntry | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if self._clock() >= entry.expires_at:
            self._store.pop(key, None)
            return None
        return entry

    def set(self, key: str, value: Any, fetched_at: datetime, ttl_s: float) -> CacheEntry:
        entry = CacheEntry(value=value, fetched_at=fetched_at, expires_at=self._clock() + ttl_s)
        self._store[key] = entry
        return entry

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


cache = TTLCache()
