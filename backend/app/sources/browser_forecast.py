"""Forecast fetched in the visitor's browser and posted with the question (POST /api/advice).

Open-Meteo limits requests per IP address. The server's shared address was getting HTTP 429, so the
advice page now sends the forecast request from the visitor's own browser (web/lib/forecastClient.ts,
the same parameters as sources/forecast.py) and posts the JSON here. Before any rule uses it the server
checks that:
- the expected hourly and daily columns exist and match their time axis in length,
- every value is within config.BROWSER_FORECAST_PLAUSIBLE,
- the times are in Asia/Kolkata, the first hour is the current one and the daily rows include today,
- Open-Meteo's grid point is near the place asked about,
- the fetch time is recent (config.BROWSER_FORECAST_MAX_AGE_S).
Anything else is rejected with InvalidForecast, whose message says what was wrong.

If the browser fetch failed (429, timeout, network), the server goes straight to MET Norway and
never calls Open-Meteo itself.
"""
import math
import re
from datetime import date, datetime, timedelta

from .. import config
from ..http import SourceResult
from ..timeutil import TZ, parse_local
from . import forecast, metno

NAME = "Open-Meteo (fetched in your browser)"
MAX_ROWS = {"hourly": 24 * 10, "daily": 31 + config.FORECAST_DAILY_DAYS + 2}
_TIME = {"hourly": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"), "daily": re.compile(r"^\d{4}-\d{2}-\d{2}$")}
_VARS = {"hourly": config.FORECAST_HOURLY_VARS, "daily": config.FORECAST_DAILY_VARS}


class InvalidForecast(ValueError):
    """The posted forecast failed a check; the message names the check."""


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_fetched_at(value) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise InvalidForecast("the browser fetch time is missing or not a valid time") from None
    if dt.tzinfo is None:
        raise InvalidForecast("the browser fetch time has no time zone")
    return dt.astimezone(TZ)


def validate(payload, lat: float, lon: float, fetched_at: datetime, now: datetime) -> None:
    if not isinstance(payload, dict):
        raise InvalidForecast("no forecast data was sent")
    if payload.get("timezone") != config.TIMEZONE:
        raise InvalidForecast(f"forecast times must be in {config.TIMEZONE}")
    glat, glon = payload.get("latitude"), payload.get("longitude")
    if not (_number(glat) and _number(glon)):
        raise InvalidForecast("the forecast has no grid coordinates")
    off = config.BROWSER_FORECAST_MAX_GRID_OFFSET_DEG
    if abs(glat - lat) > off or abs(glon - lon) > off:
        raise InvalidForecast(f"the forecast is for {glat:.3f}, {glon:.3f}, not for {lat:.3f}, {lon:.3f}")

    age = (now - fetched_at).total_seconds()
    if age > config.BROWSER_FORECAST_MAX_AGE_S:
        raise InvalidForecast(f"the forecast was fetched {age / 60:.0f} minutes ago; please ask again")
    if age < -config.BROWSER_FORECAST_MAX_AHEAD_S:
        raise InvalidForecast("the forecast fetch time is in the future; check the device clock")

    for section in ("hourly", "daily"):
        block = payload.get(section)
        times = block.get("time") if isinstance(block, dict) else None
        if not isinstance(times, list) or not times:
            raise InvalidForecast(f"'{section}.time' is missing")
        if len(times) > MAX_ROWS[section]:
            raise InvalidForecast(f"'{section}' has too many rows ({len(times)})")
        if not all(isinstance(t, str) and _TIME[section].match(t) for t in times):
            raise InvalidForecast(f"'{section}.time' has a value that is not a {section} timestamp")
        if any(a >= b for a, b in zip(times, times[1:])):
            raise InvalidForecast(f"'{section}.time' is not in order")
        for var in _VARS[section]:
            col = block.get(var)
            if not isinstance(col, list) or len(col) != len(times):
                raise InvalidForecast(f"'{section}.{var}' is missing or has the wrong length")
            lo, hi = config.BROWSER_FORECAST_PLAUSIBLE[var]
            for v in col:
                if v is not None and not (_number(v) and lo <= v <= hi):
                    raise InvalidForecast(f"'{section}.{var}' has the value {v!r}, outside {lo:g} to {hi:g}")

    # The hourly forecast starts at the current hour (past_hours=0); allow for a cached copy and clock skew.
    current = now.replace(minute=0, second=0, microsecond=0)
    first = parse_local(payload["hourly"]["time"][0])
    if not current - timedelta(hours=2) <= first <= current + timedelta(hours=1):
        raise InvalidForecast(f"the forecast starts at {payload['hourly']['time'][0]}, not at the current hour")
    if now.date().isoformat() not in payload["daily"]["time"]:
        raise InvalidForecast("the daily forecast does not include today")


def _failure(posted: dict) -> str:
    status = posted.get("status")
    if isinstance(status, int) and not isinstance(status, bool):
        return f"HTTP {status}"
    return str(posted.get("error") or "no response")[:120]


async def resolve(posted: dict, lat: float, lon: float, past_from: date, today: date, now: datetime) -> SourceResult:
    """The forecast source for one question: the browser's copy if it passes the checks, MET Norway if the
    browser fetch failed. Raises InvalidForecast if a forecast was sent but fails a check."""
    if not posted.get("ok"):
        why = _failure(posted)
        res = await metno.fetch(lat, lon, now)
        if res.ok:
            res.error = f"Open-Meteo in your browser failed ({why}); using {metno.NAME}. {metno.LIMITS}."
            return res
        return SourceResult("forecast", NAME, config.FORECAST_URL, status="failed",
                            error=f"Open-Meteo in your browser failed ({why}), and {res.error}")
    fetched_at = parse_fetched_at(posted.get("fetched_at"))
    payload = posted.get("data")
    validate(payload, lat, lon, fetched_at, now)
    return SourceResult("forecast", NAME, config.FORECAST_URL, data=forecast.parse_payload(payload, past_from, today),
                        fetched_at=fetched_at, cached=bool(posted.get("cached")), meta={"fetched_in": "browser"})
