"""MET Norway Locationforecast 2.0 (compact): forecast fallback when Open-Meteo returns 429 or 5xx.

- Identifies itself with "YieldGuard/1.0 (contact: METNO_CONTACT)" as MET Norway's terms require;
  without METNO_CONTACT the fallback is not used.
- Coordinates are rounded to 4 decimals (MET Norway asks for at most 4).
- Responses are cached until their Expires / Cache-Control time, and revalidated with
  If-Modified-Since (a 304 keeps the stored copy and its original fetch time).
- Wind speed arrives in m/s and is converted to km/h (x 3.6) here, before any rule runs.
- The compact product has no rain probability, no evapotranspiration and no past rainfall,
  so those values are None (rules treat them as missing) and the result says so.
Data: MET Norway, licensed CC BY 4.0 / NLOD 2.0.
"""
import email.utils
import logging
import re
import time
from datetime import datetime

from .. import config
from ..http import SourceResult, get_client
from ..timeutil import TZ, now_local

log = logging.getLogger(__name__)

NAME = "MET Norway fallback (Locationforecast 2.0)"
LIMITS = ("MET Norway compact has no rain probability, evapotranspiration or past rainfall, so spray windows, "
          "rain-chance checks, the irrigation planner and rainfall-vs-normal are limited")
DEFAULT_TTL_S = 30 * 60

_cache: dict[str, dict] = {}  # "lat,lon" -> {"payload", "expires" (epoch), "last_modified", "fetched_at"}


def wind_kmh(ms: float | None) -> float | None:
    """MET Norway wind is m/s; every rule and threshold uses km/h."""
    return None if ms is None else round(ms * 3.6, 1)


def _expiry(headers) -> float:
    exp = headers.get("Expires")
    if exp:
        try:
            return email.utils.parsedate_to_datetime(exp).timestamp()
        except (TypeError, ValueError):
            pass
    m = re.search(r"max-age=(\d+)", headers.get("Cache-Control", ""))
    return time.time() + (int(m.group(1)) if m else DEFAULT_TTL_S)


def parse(payload: dict, now: datetime) -> dict:
    """Timeseries -> the same shape as sources/forecast.py data (hours, days, units), in local time."""
    current = now.replace(minute=0, second=0, microsecond=0)
    hours, per_day = [], {}
    for step in (payload.get("properties") or {}).get("timeseries") or []:
        t = datetime.fromisoformat(step["time"].replace("Z", "+00:00")).astimezone(TZ)
        data = step.get("data") or {}
        inst = (data.get("instant") or {}).get("details") or {}
        n1 = ((data.get("next_1_hours") or {}).get("details") or {}).get("precipitation_amount")
        n6 = ((data.get("next_6_hours") or {}).get("details") or {}).get("precipitation_amount")
        day = per_day.setdefault(t.date().isoformat(), {"temps": [], "rain": 0.0, "rain_steps": 0})
        if inst.get("air_temperature") is not None:
            day["temps"].append(inst["air_temperature"])
        # Hourly steps carry next_1_hours; later 6-hourly steps carry next_6_hours (no overlap).
        rain = n1 if "next_1_hours" in data else n6
        if rain is not None:
            day["rain"] += rain
            day["rain_steps"] += 1
        if "next_1_hours" in data and t >= current:
            hours.append({
                "time": t.strftime("%Y-%m-%dT%H:%M"),
                "temperature_2m": inst.get("air_temperature"),
                "relative_humidity_2m": inst.get("relative_humidity"),
                "precipitation_probability": None,  # not in the compact product
                "precipitation": n1,
                "wind_speed_10m": wind_kmh(inst.get("wind_speed")),
            })
    today = now.date().isoformat()
    days = [{"date": d, "precipitation_sum": round(v["rain"], 1) if v["rain_steps"] else None,
             "et0_fao_evapotranspiration": None,  # not available from MET Norway
             "temperature_2m_max": max(v["temps"]) if v["temps"] else None}
            for d, v in sorted(per_day.items()) if d >= today][: config.FORECAST_DAILY_DAYS]
    return {
        "hours": hours[: config.FORECAST_HOURS + 1],
        "units": {"temperature_2m": "°C", "relative_humidity_2m": "%", "precipitation": "mm",
                  "wind_speed_10m": "km/h (converted from m/s)"},
        "daily": {},  # no past rainfall in a forecast product
        "days": days,
        "daily_units": {"precipitation_sum": "mm", "temperature_2m_max": "°C (highest forecast value)"},
        "past_from": None,
        "provider": "metno",
        "limits": LIMITS,
    }


async def fetch(lat: float, lon: float, now: datetime | None = None) -> SourceResult:
    now = now or now_local()
    if not config.METNO_CONTACT:
        return SourceResult("forecast", NAME, config.METNO_URL, status="failed",
                            error="MET Norway fallback not configured (set METNO_CONTACT)")
    lat, lon = round(lat, 4), round(lon, 4)
    key = f"{lat},{lon}"
    entry = _cache.get(key)
    if entry and time.time() < entry["expires"]:
        return SourceResult("forecast", NAME, config.METNO_URL, data=parse(entry["payload"], now),
                            fetched_at=entry["fetched_at"], cached=True, meta={"fallback_for": "Open-Meteo"})

    headers = {"User-Agent": f"YieldGuard/1.0 (contact: {config.METNO_CONTACT})"}
    if entry and entry.get("last_modified"):
        headers["If-Modified-Since"] = entry["last_modified"]
    t0 = time.perf_counter()
    status: int | str = "-"
    try:
        resp = await get_client().get(config.METNO_URL, params={"lat": lat, "lon": lon}, headers=headers,
                                      timeout=config.HTTP_TIMEOUT_S)
        status = resp.status_code
        if resp.status_code == 304 and entry:
            entry["expires"] = _expiry(resp.headers)
            return SourceResult("forecast", NAME, config.METNO_URL, data=parse(entry["payload"], now),
                                fetched_at=entry["fetched_at"], cached=True, meta={"fallback_for": "Open-Meteo"})
        if resp.status_code not in (200, 203):
            return SourceResult("forecast", NAME, config.METNO_URL, status="failed",
                                error=f"MET Norway HTTP {resp.status_code}")
        payload = resp.json()
        entry = {"payload": payload, "expires": _expiry(resp.headers),
                 "last_modified": resp.headers.get("Last-Modified"), "fetched_at": now_local()}
        _cache[key] = entry
        return SourceResult("forecast", NAME, config.METNO_URL, data=parse(payload, now),
                            fetched_at=entry["fetched_at"], meta={"fallback_for": "Open-Meteo"})
    except Exception as e:  # network errors, bad JSON: the fallback must never crash the request
        status = type(e).__name__
        return SourceResult("forecast", NAME, config.METNO_URL, status="failed",
                            error=f"MET Norway unavailable ({type(e).__name__})")
    finally:
        log.info("fetch api.met.no /locationforecast lat=%s lon=%s -> %s in %.0f ms", lat, lon, status,
                 (time.perf_counter() - t0) * 1000)


def clear() -> None:
    _cache.clear()

