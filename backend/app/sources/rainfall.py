"""Daily rainfall: recent (month-to-date) and historical (long-run baseline).

- Month-to-date comes from the same Forecast API request as the forecast
  (past_days), which serves recent days without the ~5 day delay of the archive.
  See month_to_date() - it costs no extra call.
- The baseline comes from the Archive API: one small request per baseline year
  covering only the month being compared. Open-Meteo weights calls by length, so a
  single 26-year request would cost ~680 of the 10,000 free daily calls; this costs ~57.
  It is built once per district and month, cached for 30 days, and saved to a file
  so a restart does not refetch it.
"""
import asyncio
import calendar
from datetime import date

from .. import config
from ..cache import FileCache
from ..http import FetchError, SourceResult, cached_fetch, coord_key, get_json

MTD_NAME = "Open-Meteo Forecast API (recent daily precipitation)"
BASELINE_NAME = "Open-Meteo Historical Weather (Archive) API"

baseline_store = FileCache(config.BASELINE_CACHE_FILE)


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


def baseline_key(place: dict) -> str:
    """Normals are built once per district (falling back to ~1 km coordinates when there is none)."""
    district = (place.get("district") or "").strip().lower()
    return f"district:{district}" if district else f"coord:{coord_key(place['lat'], place['lon'])}"


async def fetch_baseline(place: dict, start_year: int, end_year: int, month: int) -> SourceResult:
    """Daily rainfall for `month` in every year from start_year to end_year, for the place's district."""
    lat, lon = place["lat"], place["lon"]

    async def one_year(year: int) -> dict[str, float | None]:
        last = calendar.monthrange(year, month)[1]
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "precipitation_sum",
            "timezone": config.TIMEZONE,
            "start_date": f"{year}-{month:02d}-01",
            "end_date": f"{year}-{month:02d}-{last:02d}",
        }
        return parse_daily(await get_json(config.ARCHIVE_URL, params))

    years = list(range(start_year, end_year + 1))

    async def load():
        # Requests queue behind the Open-Meteo limit (one at a time) in http.get_json.
        results = await asyncio.gather(*(one_year(y) for y in years), return_exceptions=True)
        daily, got, errors = {}, [], []
        for y, r in zip(years, results):
            if isinstance(r, BaseException):
                errors.append(str(r))
            else:
                daily.update(r)
                got.append(y)
        if len(got) < min(config.BASELINE_MIN_YEARS, len(years)):
            raise FetchError(errors[0] if errors else "no baseline years returned")
        return {"daily": daily, "start_year": start_year, "end_year": end_year, "month": month,
                "district": place.get("district"), "lat": lat, "lon": lon,
                "years_fetched": got, "years_missing": [y for y in years if y not in got]}

    def ttl(data: dict) -> float:
        return config.TTL_PARTIAL_BASELINE if data["years_missing"] else config.TTL_BASELINE

    return await cached_fetch("rain_baseline", BASELINE_NAME, config.ARCHIVE_URL,
                              f"base:{baseline_key(place)}:{start_year}:{end_year}:{month:02d}",
                              config.TTL_BASELINE, load, ttl_for=ttl, store=baseline_store)
