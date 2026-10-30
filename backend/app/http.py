"""HTTP fetching with timeout, one retry, caching and a uniform result type.

Fetchers never raise: they return a SourceResult with status "ok" or "failed"
so the advisor can keep going and tell the user which source is missing.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import httpx

from . import config
from .cache import cache
from .timeutil import now_local

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class SourceResult:
    source_id: str            # e.g. "forecast", "soil"
    name: str                 # human-readable
    url: str                  # endpoint called (no secrets in these URLs)
    status: str = "ok"        # "ok" | "failed"
    data: Any = None
    fetched_at: datetime | None = None
    cached: bool = False
    error: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class FetchError(Exception):
    pass


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(headers={"User-Agent": "YieldGuard/1.0 (student buildathon)"})
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_json(url: str, params: Any, timeout_s: float = config.HTTP_TIMEOUT_S,
                   retries: int = config.HTTP_RETRIES) -> Any:
    """GET a JSON document. Retries on timeouts, connection errors and 429/5xx."""
    last_err: str = "unknown error"
    for attempt in range(retries + 1):
        try:
            resp = await get_client().get(url, params=params, timeout=timeout_s)
            if resp.status_code in RETRYABLE_STATUS:
                last_err = f"HTTP {resp.status_code}"
            elif resp.status_code >= 400:
                # Client errors won't fix themselves - do not retry.
                raise FetchError(f"HTTP {resp.status_code}: {_short(resp.text)}")
            else:
                return resp.json()
        except FetchError:
            raise
        except httpx.TimeoutException:
            last_err = f"timed out after {timeout_s:.0f}s"
        except httpx.HTTPError as e:
            last_err = f"network error ({type(e).__name__})"
        except ValueError:
            last_err = "response was not valid JSON"
        log.warning("fetch %s attempt %d failed: %s", url, attempt + 1, last_err)
        if attempt < retries:
            await asyncio.sleep(0.5)
    raise FetchError(last_err)


async def cached_fetch(source_id: str, name: str, url: str, cache_key: str, ttl_s: float,
                       loader: Callable[[], Any]) -> SourceResult:
    """Return a cached SourceResult or run `loader` (an async callable returning data)."""
    hit = cache.get(cache_key)
    if hit is not None:
        return SourceResult(source_id, name, url, data=hit.value, fetched_at=hit.fetched_at, cached=True)
    try:
        data = await loader()
    except FetchError as e:
        return SourceResult(source_id, name, url, status="failed", error=str(e))
    except Exception as e:  # parsing bugs or unexpected shapes must not crash the request
        log.exception("loader for %s failed", source_id)
        return SourceResult(source_id, name, url, status="failed", error=f"unexpected response ({type(e).__name__})")
    fetched_at = now_local()
    cache.set(cache_key, data, fetched_at, ttl_s)
    return SourceResult(source_id, name, url, data=data, fetched_at=fetched_at, cached=False)


def coord_key(lat: float, lon: float) -> str:
    d = config.CACHE_COORD_DECIMALS
    return f"{round(lat, d)},{round(lon, d)}"


def _short(text: str, n: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "..."
