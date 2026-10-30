"""TTL caches that keep the original fetch time with every value.

- TTLCache: in memory (forecast, soil, place search).
- FileCache: the same interface, saved to a JSON file so a restart does not
  refetch slow-changing data (the rainfall baseline).
"""
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    value: Any
    fetched_at: datetime   # when the live API call was made
    expires_at: float      # in the cache's clock (monotonic for TTLCache, epoch for FileCache)


class TTLCache:
    def __init__(self, clock=time.monotonic):
        self._store: dict[str, CacheEntry] = {}
        self._clock = clock

    def get(self, key: str) -> CacheEntry | None:
        """Fresh entry, or None if missing or expired (expired entries are kept for get_stale)."""
        entry = self._store.get(key)
        if entry is None or self._clock() >= entry.expires_at:
            return None
        return entry

    def get_stale(self, key: str) -> CacheEntry | None:
        """Last stored entry even if expired; used only when a live refresh fails."""
        return self._store.get(key)

    def set(self, key: str, value: Any, fetched_at: datetime, ttl_s: float) -> CacheEntry:
        entry = CacheEntry(value=value, fetched_at=fetched_at, expires_at=self._clock() + ttl_s)
        self._store[key] = entry
        return entry

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


class FileCache:
    """TTL cache persisted to one JSON file. Uses wall-clock time so entries survive restarts.
    Values must be JSON-serialisable. A missing or corrupt file just means an empty cache."""

    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self._clock = clock
        self._store: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._store is None:
            try:
                self._store = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                self._store = {}
            except (OSError, ValueError) as e:
                log.warning("ignoring unreadable cache file %s (%s)", self.path, e)
                self._store = {}
        return self._store

    def _entry(self, key: str) -> CacheEntry | None:
        raw = self._load().get(key)
        if raw is None:
            return None
        return CacheEntry(value=raw["value"], fetched_at=datetime.fromisoformat(raw["fetched_at"]),
                          expires_at=raw["expires_at"])

    def get(self, key: str) -> CacheEntry | None:
        entry = self._entry(key)
        if entry is None or self._clock() >= entry.expires_at:
            return None
        return entry

    def get_stale(self, key: str) -> CacheEntry | None:
        return self._entry(key)

    def set(self, key: str, value: Any, fetched_at: datetime, ttl_s: float) -> CacheEntry:
        entry = CacheEntry(value=value, fetched_at=fetched_at, expires_at=self._clock() + ttl_s)
        self._load()[key] = {"value": value, "fetched_at": fetched_at.isoformat(), "expires_at": entry.expires_at}
        self._save()
        return entry

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._store, f)
            os.replace(tmp, self.path)  # atomic: a crash never leaves a half-written file
        except OSError as e:
            log.warning("could not write cache file %s (%s); keeping it in memory only", self.path, e)

    def clear(self) -> None:
        self._store = {}
        try:
            self.path.unlink()
        except OSError:
            pass


cache = TTLCache()
