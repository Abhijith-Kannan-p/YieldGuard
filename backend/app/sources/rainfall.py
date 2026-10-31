"""Daily rainfall helpers: recent (month-to-date) and historical (long-run baseline).

- Month-to-date comes from the same Forecast API request as the forecast
  (past_days), which serves recent days without the ~5 day delay of the archive.
  See month_to_date() - it costs no extra call.
- The long-run baseline is built per district in the background from one Archive API
  request and saved to disk: see app/baseline.py. Questions never fetch it.
"""
from datetime import date

from .. import config
from ..http import SourceResult

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


def month_to_date(fc: SourceResult) -> SourceResult:
    """Recent daily rain taken from the combined forecast request: same fetch time, cache and status."""
    data = {"daily": fc.data.get("daily", {})} if fc.ok else None
    return SourceResult("rain_mtd", MTD_NAME, fc.url, status=fc.status, data=data, fetched_at=fc.fetched_at,
                        cached=fc.cached, stale=fc.stale, error=fc.error, meta={"same_request_as": "forecast"})
