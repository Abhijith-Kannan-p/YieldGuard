"""Daily rainfall: recent (month-to-date) and historical (long-run baseline).

- Month-to-date comes from the Forecast API, which serves recent past days
  without the ~5 day delay of the reanalysis archive.
- The baseline comes from the Archive API in a single request covering all
  baseline years, cached for days because history does not change.
"""
from datetime import date

from .. import config
from ..http import SourceResult, cached_fetch, coord_key, get_json

MTD_NAME = "Open-Meteo Forecast API (recent daily precipitation)"
BASELINE_NAME = "Open-Meteo Historical Weather (Archive) API"


def parse_daily(payload: dict) -> dict[str, float | None]:
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    values = daily.get("precipitation_sum") or []
    return {t: (values[i] if i < len(values) else None) for i, t in enumerate(times)}


def baseline_years(today: date) -> tuple[int, int]:
    end = config.BASELINE_END_YEAR or today.year - 1
    return config.BASELINE_START_YEAR, end


async def fetch_month_to_date(lat: float, lon: float, start: date, end: date) -> SourceResult:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum",
        "timezone": config.TIMEZONE,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }

    async def load():
        return {"daily": parse_daily(await get_json(config.FORECAST_URL, params)),
                "start": start.isoformat(), "end": end.isoformat()}

    return await cached_fetch("rain_mtd", MTD_NAME, config.FORECAST_URL,
                              f"mtd:{coord_key(lat, lon)}:{start}:{end}", config.TTL_MONTH_TO_DATE, load)


async def fetch_baseline(lat: float, lon: float, start_year: int, end_year: int) -> SourceResult:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum",
        "timezone": config.TIMEZONE,
        "start_date": f"{start_year}-01-01",
        "end_date": f"{end_year}-12-31",
    }

    async def load():
        payload = await get_json(config.ARCHIVE_URL, params, timeout_s=config.ARCHIVE_TIMEOUT_S)
        return {"daily": parse_daily(payload), "start_year": start_year, "end_year": end_year}

    return await cached_fetch("rain_baseline", BASELINE_NAME, config.ARCHIVE_URL,
                              f"base:{coord_key(lat, lon)}:{start_year}:{end_year}", config.TTL_BASELINE, load)
