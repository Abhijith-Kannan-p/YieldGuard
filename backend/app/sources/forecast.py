"""Open-Meteo forecast: the next 72 hours (hourly) plus recent past days (daily rain),
fetched in ONE request using past_days, so month-to-date rainfall costs no extra call."""
from datetime import date

from .. import config
from ..http import SourceResult, cached_fetch, coord_key, get_json
from .rainfall import parse_daily

NAME = "Open-Meteo Forecast API"


def parse_hourly(payload: dict, from_date: str | None = None) -> dict:
    """Turn Open-Meteo's column arrays into a list of per-hour dicts.

    Missing columns or short arrays become None rather than raising. Hours before
    `from_date` (YYYY-MM-DD) are dropped: past_days also returns past hours.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    hours = []
    for i, t in enumerate(times):
        if from_date and t[:10] < from_date:
            continue
        row = {"time": t}
        for var in config.FORECAST_HOURLY_VARS:
            col = hourly.get(var) or []
            row[var] = col[i] if i < len(col) else None
        hours.append(row)
    return {
        "hours": hours,
        "units": payload.get("hourly_units", {}),
        "grid_lat": payload.get("latitude"),
        "grid_lon": payload.get("longitude"),
        "elevation_m": payload.get("elevation"),
    }


async def fetch(lat: float, lon: float, past_from: date, today: date) -> SourceResult:
    """Hourly forecast from today, plus daily rain from `past_from` (the rainfall-deficit window start).

    Result data: hours, units, daily ({date: mm}), past_from. Cached per location for TTL_FORECAST.
    """
    past_days = max(0, (today - past_from).days)
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(config.FORECAST_HOURLY_VARS),
        "daily": "precipitation_sum",
        "timezone": config.TIMEZONE,
        "forecast_days": config.FORECAST_DAYS,
        "past_days": past_days,
    }

    async def load():
        payload = await get_json(config.FORECAST_URL, params)
        data = parse_hourly(payload, from_date=today.isoformat())
        data["daily"] = parse_daily(payload)
        data["past_from"] = past_from.isoformat()
        return data

    # The key includes the day so past_days is always right for the cached copy.
    return await cached_fetch("forecast", NAME, config.FORECAST_URL,
                              f"fc:{coord_key(lat, lon)}:{today.isoformat()}", config.TTL_FORECAST, load)
