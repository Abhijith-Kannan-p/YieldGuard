"""HTTP fetching with timeout, one retry, caching and a uniform result type.

Fetchers never raise: they return a SourceResult with status "ok" or "failed"
so the advisor can keep going and tell the user which source is missing.

Open-Meteo's free tier is rate-limited per IP address, so calls to it are
sent one at a time, and after an Open-Meteo HTTP 429 no further Open-Meteo call
is sent until the backoff period has passed (Retry-After, or at least
RATE_LIMIT_BACKOFF_S). Other providers (SoilGrids) get no backoff: a 429 there
is retried once like a 5xx. Gemini does not go through this module.
Every external call is logged with its status and duration.
"""
import asyncio
import email.utils
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from . import config
from .cache import cache
from .timeutil import now_local

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {500, 502, 503, 504}  # plus 429 for non-Open-Meteo providers (see get_json)


@dataclass
class SourceResult:
    source_id: str            # e.g. "forecast", "soil"
    name: str                 # human-readable
    url: str                  # endpoint called (no secrets in these URLs)
    status: str = "ok"        # "ok" | "failed"
    data: Any = None
    fetched_at: datetime | None = None
    cached: bool = False
    stale: bool = False       # live refresh failed; data is the last good response
    error: str | None = None  # why the source failed, or why the refresh failed when stale
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


# ---------------------------------------------------------------------------
# Rate limiting: one call at a time per provider, and a shared backoff after HTTP 429
# ---------------------------------------------------------------------------
_clock = time.monotonic           # replaced in tests
_backoff_until: dict[str, float] = {}
_gates: dict[tuple[str, int], asyncio.Semaphore] = {}


def provider(url: str) -> str:
    """Open-Meteo counts all its hosts (forecast, archive, geocoding) against one per-IP limit."""
    host = urlsplit(url).hostname or ""
    return "open-meteo" if host == "open-meteo.com" or host.endswith(".open-meteo.com") else host


def _gate(name: str) -> asyncio.Semaphore:
    key = (name, id(asyncio.get_running_loop()))  # a semaphore belongs to one event loop
    if key not in _gates:
        limit = config.OPEN_METEO_MAX_CONCURRENT if name == "open-meteo" else config.OTHER_MAX_CONCURRENT
        _gates[key] = asyncio.Semaphore(limit)
    return _gates[key]


def backoff_remaining(url: str) -> float:
    return max(0.0, _backoff_until.get(provider(url), 0.0) - _clock())


def _retry_after_s(resp: httpx.Response) -> float:
    """Seconds to wait after a 429: the Retry-After header if usable, else the configured minimum."""
    value = resp.headers.get("Retry-After", "").strip()
    wait = 0.0
    if value.isdigit():
        wait = float(value)
    elif value:
        try:
            wait = email.utils.parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            wait = 0.0
    return min(max(wait, config.RATE_LIMIT_BACKOFF_S), config.RATE_LIMIT_BACKOFF_MAX_S)


def _describe(params: Any) -> str:
    """Short, key-free description of a request for the log."""
    if not isinstance(params, dict):
        return ""
    keys = ("latitude", "longitude", "lat", "lon", "name", "start_date", "end_date", "past_days")
    return " ".join(f"{k}={params[k]}" for k in keys if k in params)


async def get_json(url: str, params: Any, timeout_s: float = config.HTTP_TIMEOUT_S,
                   retries: int = config.HTTP_RETRIES) -> Any:
    """GET a JSON document. Retries once on timeouts, connection errors and 5xx.

    An Open-Meteo HTTP 429 is never retried: Open-Meteo is put in backoff and every call
    to it fails fast (without a request) until the backoff ends, so callers can fall
    back to cached data. A 429 from another provider is retried once, without backoff.
    """
    name = provider(url)
    path = urlsplit(url).path
    last_err: str = "unknown error"
    for attempt in range(retries + 1):
        wait = backoff_remaining(url)
        if wait > 0:
            log.info("skip  %s %s %s: rate-limit backoff, %.0f s left", name, path, _describe(params), wait)
            raise FetchError(f"rate limit reached; paused for {wait:.0f} s more")
        async with _gate(name):
            wait = backoff_remaining(url)  # another call may have hit a 429 while this one waited
            if wait > 0:
                log.info("skip  %s %s %s: rate-limit backoff, %.0f s left", name, path, _describe(params), wait)
                raise FetchError(f"rate limit reached; paused for {wait:.0f} s more")
            t0 = time.perf_counter()
            status: int | str = "-"
            try:
                resp = await get_client().get(url, params=params, timeout=timeout_s)
                status = resp.status_code
                if resp.status_code == 429 and name == "open-meteo":
                    pause = _retry_after_s(resp)
                    _backoff_until[name] = _clock() + pause
                    reason = _reason(resp)
                    raise FetchError(f"rate limit reached (HTTP 429{': ' + reason if reason else ''}); "
                                     f"paused for {pause:.0f} s")
                if resp.status_code == 429:
                    last_err = "rate limit reached (HTTP 429)"
                elif resp.status_code in RETRYABLE_STATUS:
                    last_err = f"HTTP {resp.status_code}"
                elif resp.status_code >= 400:
                    # Client errors won't fix themselves - do not retry.
                    raise FetchError(f"HTTP {resp.status_code}: {_short(resp.text)}")
                else:
                    return resp.json()
            except FetchError:
                raise
            except httpx.TimeoutException:
                status = "timeout"
                last_err = f"timed out after {timeout_s:.0f}s"
            except httpx.HTTPError as e:
                status = type(e).__name__
                last_err = f"network error ({type(e).__name__})"
            except ValueError:
                last_err = "response was not valid JSON"
            finally:
                log.info("fetch %s %s %s -> %s in %.0f ms", name, path, _describe(params), status,
                         (time.perf_counter() - t0) * 1000)
        if attempt < retries:
            await asyncio.sleep(0.5)
    raise FetchError(last_err)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
_inflight: dict[str, asyncio.Future] = {}


async def cached_fetch(source_id: str, name: str, url: str, cache_key: str, ttl_s: float,
                       loader: Callable[[], Any], ttl_for: Callable[[Any], float] | None = None,
                       store=None) -> SourceResult:
    """Return a cached SourceResult or run `loader` (an async callable returning data).

    Concurrent requests for the same key share one live call. If the live call fails and
    an earlier good response is stored (within STALE_MAX_AGE_S), that response is returned
    marked stale, with its original fetch time and the refresh error.
    `store` defaults to the in-memory cache; the rainfall baseline uses a file-backed store.
    """
    store = store if store is not None else cache
    hit = store.get(cache_key)
    if hit is not None:
        return SourceResult(source_id, name, url, data=hit.value, fetched_at=hit.fetched_at, cached=True)

    if cache_key in _inflight:
        try:
            data, fetched_at = await asyncio.shield(_inflight[cache_key])
            return SourceResult(source_id, name, url, data=data, fetched_at=fetched_at, cached=True)
        except Exception as e:
            error = str(e)  # the shared live call failed; fall back to stored data below
    else:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        _inflight[cache_key] = fut
        try:
            data = await loader()
            fetched_at = now_local()
            store.set(cache_key, data, fetched_at, ttl_for(data) if ttl_for else ttl_s)
            fut.set_result((data, fetched_at))
            return SourceResult(source_id, name, url, data=data, fetched_at=fetched_at, cached=False)
        except Exception as e:
            if isinstance(e, FetchError):
                error = str(e)
            else:  # parsing bugs or unexpected shapes must not crash the request
                log.exception("loader for %s failed", source_id)
                error = f"unexpected response ({type(e).__name__})"
            fut.set_exception(FetchError(error))
            fut.exception()  # mark retrieved so asyncio does not warn when nobody else waited
        finally:
            _inflight.pop(cache_key, None)

    old = store.get_stale(cache_key)
    max_age = config.STALE_MAX_AGE_S.get(source_id, 0)
    if old is not None and (now_local() - old.fetched_at).total_seconds() <= max_age:
        log.warning("%s refresh failed (%s); serving data fetched %s", source_id, error, old.fetched_at)
        return SourceResult(source_id, name, url, data=old.value, fetched_at=old.fetched_at, cached=True,
                            stale=True, error=error)
    return SourceResult(source_id, name, url, status="failed", error=error)


def coord_key(lat: float, lon: float) -> str:
    d = config.CACHE_COORD_DECIMALS
    return f"{round(lat, d)},{round(lon, d)}"


def _reason(resp: httpx.Response) -> str:
    """Open-Meteo explains errors as {"error": true, "reason": "..."}."""
    try:
        return _short(str(resp.json().get("reason") or ""), 120)
    except Exception:
        return ""


def _short(text: str, n: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "..."
