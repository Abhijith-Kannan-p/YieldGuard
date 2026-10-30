"""Open-Meteo 72-hour hourly forecast."""
from .. import config
from ..http import SourceResult, cached_fetch, coord_key, get_json

NAME = "Open-Meteo Forecast API"


def parse_hourly(payload: dict) -> dict:
    """Turn Open-Meteo's column arrays into a list of per-hour dicts.

    Missing columns or short arrays become None rather than raising.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    hours = []
    for i, t in enumerate(times):
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


async def fetch(lat: float, lon: float) -> SourceResult:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(config.FORECAST_HOURLY_VARS),
        "timezone": config.TIMEZONE,
        "forecast_days": config.FORECAST_DAYS,
    }

    async def load():
        return parse_hourly(await get_json(config.FORECAST_URL, params))

    return await cached_fetch("forecast", NAME, config.FORECAST_URL,
                              f"fc:{coord_key(lat, lon)}", config.TTL_FORECAST, load)
