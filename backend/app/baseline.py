"""Long-run rainfall baseline, per district, built in the background and saved to data/.

- One Open-Meteo Archive request per district covers the whole baseline period
  (BASELINE_START_YEAR-01-01 to the last full year's 12-31, daily precipitation_sum).
- The parsed daily values, the years used and the build time are saved to
  BASELINE_FILE and loaded at startup. Questions never fetch the baseline: they read
  the stored copy, and the deficit rule averages the same calendar dates over its years.
- A district that is missing (or older than TTL_BASELINE) is queued for a background
  build. Builds run one at a time, spaced BASELINE_BUILD_SPACING_S apart. Until a build
  succeeds, the answer says the baseline is not available yet.
"""
import asyncio
import calendar
import json
import logging
import os
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

from . import config
from .http import FetchError, SourceResult, coord_key, get_json
from .sources.rainfall import BASELINE_NAME, baseline_years, parse_daily
from .timeutil import iso, now_local

log = logging.getLogger(__name__)


def district_key(place: dict) -> str:
    """Baselines are shared by every place in a district (coordinates if the district is unknown)."""
    district = (place.get("district") or "").strip().lower()
    return f"district:{district}" if district else f"coord:{coord_key(place['lat'], place['lon'])}"


def _label(place: dict) -> str:
    return place.get("district") or place.get("name") or f"{place['lat']:.2f}, {place['lon']:.2f}"


def build_entry(place: dict, payload: dict, start_year: int, end_year: int, built_at: datetime) -> dict:
    """Turn one archive response into the stored form: per-year lists of daily rainfall (index = day of year)."""
    daily = parse_daily(payload)
    years: dict[str, list[float | None]] = {}
    for y in range(start_year, end_year + 1):
        n = 366 if calendar.isleap(y) else 365
        start = date(y, 1, 1).toordinal()
        vals = [daily.get(date.fromordinal(start + i).isoformat()) for i in range(n)]
        if sum(v is not None for v in vals) >= n - 5:  # tolerate a few missing days; the rule skips gaps
            years[str(y)] = vals
    if len(years) < config.BASELINE_MIN_YEARS:
        raise FetchError(f"archive returned only {len(years)} usable years")
    return {
        "district": place.get("district"),
        "place": place.get("name"),
        "lat": place["lat"],
        "lon": place["lon"],
        "start_year": start_year,
        "end_year": end_year,
        "years_used": sorted(int(y) for y in years),
        "built_at": iso(built_at),
        "source": BASELINE_NAME,
        "request": f"start_date={start_year}-01-01 end_date={end_year}-12-31 daily=precipitation_sum",
        "years": years,
    }


def entry_daily(entry: dict) -> dict[str, float | None]:
    """Stored per-year lists back to {YYYY-MM-DD: mm}, the shape the deficit rule uses."""
    out: dict[str, float | None] = {}
    for y, vals in entry["years"].items():
        start = date(int(y), 1, 1).toordinal()
        for i, v in enumerate(vals):
            out[date.fromordinal(start + i).isoformat()] = v
    return out


class BaselineStore:
    def __init__(self, path: Path, autostart: bool = True):
        self.path = Path(path)
        self.autostart = autostart          # tests and local dev tools turn the background worker off
        self.entries: dict[str, dict] = {}
        self._daily: dict[str, dict] = {}   # key -> expanded daily dict (memory only)
        self._places: dict[str, dict] = {}  # queued key -> place
        self._queue: asyncio.Queue | None = None
        self._worker: asyncio.Task | None = None
        self.building: str | None = None
        self.errors: dict[str, dict] = {}   # key -> {"error", "at", "retry_after"}

    # ---- persistence ------------------------------------------------------
    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = raw.get("districts", {})
            log.info("loaded rainfall baselines for %d district(s) from %s", len(self.entries), self.path)
        except FileNotFoundError:
            log.info("no rainfall baseline file at %s yet; it will be built in the background", self.path)
        except (OSError, ValueError) as e:
            log.warning("ignoring unreadable baseline file %s (%s)", self.path, e)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "districts": self.entries}, f)
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("could not write baseline file %s (%s); keeping it in memory only", self.path, e)

    # ---- reading (never calls an external service) -------------------------
    def _needs_refresh(self, entry: dict, end_year: int) -> bool:
        age = (now_local() - datetime.fromisoformat(entry["built_at"])).total_seconds()
        return entry["end_year"] < end_year or age > config.TTL_BASELINE

    async def get(self, place: dict, today: date) -> SourceResult:
        """The stored baseline for the place's district, or a clear 'not available yet' result."""
        key = district_key(place)
        start_year, end_year = baseline_years(today)
        entry = self.entries.get(key)
        if entry is not None:
            if self._needs_refresh(entry, end_year):
                self.schedule(place)  # keep serving the stored copy meanwhile
            if key not in self._daily:
                self._daily[key] = entry_daily(entry)
            data = {"daily": self._daily[key], "district": entry.get("district"), "start_year": entry["start_year"],
                    "end_year": entry["end_year"], "years_used": entry["years_used"], "built_at": entry["built_at"]}
            return SourceResult("rain_baseline", BASELINE_NAME, config.ARCHIVE_URL, data=data,
                                fetched_at=datetime.fromisoformat(entry["built_at"]), cached=True)

        self.schedule(place)
        err = self.errors.get(key)
        where = _label(place)
        if err:
            msg = (f"the rainfall baseline for {where} is not available yet (last build failed: {err['error']}); "
                   f"it will be retried automatically")
        else:
            msg = f"the rainfall baseline for {where} is not available yet; it is being built now, try again in a minute"
        return SourceResult("rain_baseline", BASELINE_NAME, config.ARCHIVE_URL, status="failed", error=msg)

    def status(self) -> dict:
        return {
            "districts": sorted(e.get("district") or k for k, e in self.entries.items()),
            "building": self.building,
            "queued": [k for k in self._places if k != self.building],
            "last_errors": {k: v["error"] for k, v in self.errors.items()},
        }

    # ---- background building ---------------------------------------------
    def schedule(self, place: dict) -> None:
        if not self.autostart:
            return
        key = district_key(place)
        if key in self._places:
            return
        err = self.errors.get(key)
        if err and time.monotonic() < err["retry_after"]:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._queue is None or self._worker is None or self._worker.done():
            self._queue = asyncio.Queue()
            self._worker = loop.create_task(self._run(), name="baseline-builder")
            self._places.clear()
        self._places[key] = place
        self._queue.put_nowait(key)
        log.info("queued rainfall baseline build for %s", _label(place))

    async def _run(self) -> None:
        while True:
            key = await self._queue.get()
            place = self._places.get(key)
            if place is None:
                continue
            self.building = key
            try:
                await self.build(place)
            except Exception:  # never let the worker die
                log.exception("baseline build for %s crashed", key)
            finally:
                self.building = None
                self._places.pop(key, None)
            await asyncio.sleep(config.BASELINE_BUILD_SPACING_S)  # keep big archive calls apart

    async def build(self, place: dict) -> bool:
        """Fetch the whole baseline period in ONE archive request and store it. Returns success."""
        key = district_key(place)
        start_year, end_year = baseline_years(now_local().date())
        params = {
            "latitude": place["lat"],
            "longitude": place["lon"],
            "daily": "precipitation_sum",
            "timezone": config.TIMEZONE,
            "start_date": f"{start_year}-01-01",
            "end_date": f"{end_year}-12-31",
        }
        t0 = time.perf_counter()
        try:
            payload = await get_json(config.ARCHIVE_URL, params, timeout_s=config.BASELINE_TIMEOUT_S)
            entry = build_entry(place, payload, start_year, end_year, now_local())
        except Exception as e:
            error = str(e) if isinstance(e, FetchError) else f"unexpected response ({type(e).__name__})"
            self.errors[key] = {"error": error, "at": iso(now_local()),
                                "retry_after": time.monotonic() + config.BASELINE_RETRY_AFTER_S}
            log.warning("rainfall baseline build for %s failed: %s", _label(place), error)
            return False
        self.entries[key] = entry
        self._daily.pop(key, None)
        self.errors.pop(key, None)
        self._save()
        log.info("built rainfall baseline for %s: %d years in %.1f s", _label(place), len(entry["years_used"]),
                 time.perf_counter() - t0)
        return True

    async def prebuild_default(self) -> None:
        """At startup, if nothing is stored yet, queue the default location's district."""
        if self.entries or not self.autostart:
            return
        from .sources import geocode  # local import: geocode is only needed for this background step

        res = await geocode.search(config.DEFAULT_LOCATION)
        if res.ok and res.data:
            self.schedule(res.data[0])
        else:
            log.warning("could not look up %s to prebuild its baseline: %s", config.DEFAULT_LOCATION, res.error)


store = BaselineStore(config.BASELINE_FILE)
