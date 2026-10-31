"""Open-Meteo forecast in ONE request:
- hourly: the next FORECAST_HOURS hours from the current hour (forecast_hours / past_hours=0)
- daily: precipitation_sum, et0_fao_evapotranspiration and temperature_2m_max for the past days
  of this month (past_days, for month-to-date rain) and the next FORECAST_DAILY_DAYS days
  (irrigation planner, heat alert).
Month-to-date rain, the water balance and the heat check therefore cost no extra call."""
from datetime import date

from .. import config
from ..http import SourceResult, cached_fetch, coord_key, get_json
from .rainfall import parse_daily

NAME = "Open-Meteo Forecast API"


def parse_daily_vars(payload: dict) -> list[dict]:
    """Daily columns as a list of {"date", "precipitation_sum", "et0_fao_evapotranspiration", ...}."""
    daily = payload.get("daily") or {}
    rows = []
    for i, t in enumerate(daily.get("time") or []):
        row = {"date": t}
        for var in config.FORECAST_DAILY_VARS:
            col = daily.get(var) or []
            row[var] = col[i] if i < len(col) else None
        rows.append(row)
    return rows


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
    """Hourly forecast from now, plus daily data from `past_from` (the rainfall-deficit window start)
    to FORECAST_DAILY_DAYS days ahead.

    Result data: hours, units, daily ({date: rain mm}), days (list of daily rows from today),
    daily_units, past_from. Cached per location for TTL_FORECAST.
    """
    past_days = max(0, (today - past_from).days)
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(config.FORECAST_HOURLY_VARS),
        "daily": ",".join(config.FORECAST_DAILY_VARS),
        "timezone": config.TIMEZONE,
        "forecast_hours": config.FORECAST_HOURS + 1,  # Open-Meteo's "current hour" can trail ours by one
        "past_hours": 0,
        "forecast_days": config.FORECAST_DAILY_DAYS,
        "past_days": past_days,
    }

    async def load():
        payload = await get_json(config.FORECAST_URL, params)
        data = parse_hourly(payload, from_date=today.isoformat())
        data["daily"] = parse_daily(payload)
        data["days"] = [d for d in parse_daily_vars(payload) if d["date"] >= today.isoformat()]
        data["daily_units"] = payload.get("daily_units", {})
        data["past_from"] = past_from.isoformat()
        return data

    # The key includes the day so past_days is always right for the cached copy.
    return await cached_fetch("forecast", NAME, config.FORECAST_URL,
                              f"fc:{coord_key(lat, lon)}:{today.isoformat()}", config.TTL_FORECAST, load)
