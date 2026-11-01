"""Mandi prices: Agmarknet daily prices from data.gov.in, nearest reporting market to the farmer.

- One cached snapshot of all Karnataka records (paged on "total"), refreshed every TTL_MANDI.
  The API only serves the latest day per market; the arrival_date filter is ignored.
- Prices are Rs per quintal, as the API gives them. Rows without a usable modal price are skipped.
- data.gov.in can take a minute to answer. A question waits at most MANDI_WAIT_S; a slower fetch
  keeps running and fills the cache for the next question. After a failure no new attempt is made
  for MANDI_RETRY_AFTER_S (a saved snapshot is shown meanwhile, with its fetch time).
- Markets are located by geocoding their names (sources/geocode.py), at most MANDI_MAX_GEOCODES new
  lookups per question, remembered in memory. A market farther than MANDI_MAX_DISTANCE_KM is never used.
"""
import asyncio
import logging
import re
import time
from datetime import date, datetime

from .. import config, crops
from ..cache import cache
from ..http import FetchError, SourceResult, cached_fetch, get_json
from ..timeutil import now_local
from . import geocode
from .soil import distance_km

log = logging.getLogger(__name__)

NAME = "Agmarknet mandi prices (data.gov.in)"
CACHE_KEY = "mandi:karnataka"
UNIT = "Rs/quintal"
MAX_PLAUSIBLE_PRICE = 1_000_000  # Rs per quintal; above this a row is treated as broken

_clock = time.monotonic  # replaced in tests
_retry_at = 0.0
_task: asyncio.Task | None = None
_located: dict[str, dict | None] = {}  # "market|district" -> geocoded place, or None if not found


def clear() -> None:
    global _retry_at, _task
    _retry_at, _task = 0.0, None
    _located.clear()


def _number(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return f if 0 < f < MAX_PLAUSIBLE_PRICE else None


def _date(v) -> str | None:
    try:
        return datetime.strptime(str(v).strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def parse(records: list, total: int) -> dict:
    """API records -> rows with numeric prices and ISO dates; unusable rows are counted, not guessed."""
    rows, skipped = [], 0
    for r in records:
        if not isinstance(r, dict):
            skipped += 1
            continue
        modal, arrival = _number(r.get("modal_price")), _date(r.get("arrival_date"))
        market, commodity = str(r.get("market") or "").strip(), str(r.get("commodity") or "").strip()
        if modal is None or arrival is None or not market or not commodity:
            skipped += 1
            continue
        rows.append({"state": r.get("state"), "district": str(r.get("district") or "").strip(), "market": market,
                     "commodity": commodity, "variety": str(r.get("variety") or "").strip(), "arrival_date": arrival,
                     "min_price": _number(r.get("min_price")), "max_price": _number(r.get("max_price")),
                     "modal_price": modal})
    return {"records": rows, "total": total, "skipped": skipped,
            "snapshot_date": max((r["arrival_date"] for r in rows), default=None)}


def _params(offset: int) -> dict:
    return {"api-key": config.DATAGOV_API_KEY, "format": "json", "limit": config.MANDI_PAGE_SIZE, "offset": offset,
            "filters[state.keyword]": config.REGION_NAME}


async def _load() -> dict:
    records, offset, total = [], 0, 0
    while True:
        payload = await get_json(config.MANDI_URL, _params(offset), timeout_s=config.MANDI_TIMEOUT_S,
                                 headers=config.MANDI_HEADERS)
        if not isinstance(payload, dict) or payload.get("status") == "error" or "records" not in payload:
            msg = payload.get("message") if isinstance(payload, dict) else None
            raise FetchError(f"unexpected response from data.gov.in{': ' + str(msg)[:120] if msg else ''}")
        page = payload.get("records") or []
        try:
            total = int(payload.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        records += page
        offset += len(page)
        if not page or offset >= total or offset >= config.MANDI_MAX_RECORDS:
            return parse(records, total)


def _saved_or_failed(error: str) -> SourceResult:
    """A saved snapshot young enough to show (STALE_MAX_AGE_S), labelled with its fetch time, else failed."""
    old = cache.get_stale(CACHE_KEY)
    if old is not None and (now_local() - old.fetched_at).total_seconds() <= config.STALE_MAX_AGE_S["mandi"]:
        return SourceResult("mandi", NAME, config.MANDI_URL, data=old.value, fetched_at=old.fetched_at, cached=True,
                            stale=True, error=error)
    return SourceResult("mandi", NAME, config.MANDI_URL, status="failed", error=error)


async def _fetch_and_note() -> SourceResult:
    global _retry_at
    res = await cached_fetch("mandi", NAME, config.MANDI_URL, CACHE_KEY, config.TTL_MANDI, _load)
    if not res.ok or res.stale:
        _retry_at = _clock() + config.MANDI_RETRY_AFTER_S
    return res


async def fetch() -> SourceResult:
    """All Karnataka mandi records (latest day), cached TTL_MANDI. Never waits longer than MANDI_WAIT_S."""
    global _task
    if not config.DATAGOV_API_KEY:
        return SourceResult("mandi", NAME, config.MANDI_URL, status="failed",
                            error="mandi prices are not configured (DATAGOV_API_KEY is not set)")
    hit = cache.get(CACHE_KEY)
    if hit is not None:
        return SourceResult("mandi", NAME, config.MANDI_URL, data=hit.value, fetched_at=hit.fetched_at, cached=True)
    wait = _retry_at - _clock()
    if wait > 0:
        return _saved_or_failed(f"data.gov.in failed recently; next attempt in {wait:.0f} s")
    loop = asyncio.get_running_loop()
    if _task is None or _task.done() or _task.get_loop() is not loop:
        _task = loop.create_task(_fetch_and_note())
    try:
        return await asyncio.wait_for(asyncio.shield(_task), config.MANDI_WAIT_S)
    except TimeoutError:
        return _saved_or_failed(f"data.gov.in is slow to answer (over {config.MANDI_WAIT_S:.0f} s); "
                                f"prices will be ready for a later question")


def market_query(market: str) -> str:
    """Market name -> place name to geocode: "Ranebennur APMC" -> "Ranebennur"."""
    name = re.sub(r"\(.*?\)", " ", market)
    name = re.sub(r"\b(apmc|f&v|market|yard|sub|main|mandi)\b", " ", name, flags=re.I)
    return " ".join(name.split())


def _district(s: str | None) -> str:
    return re.sub(r"\bdistrict\b", "", (s or "").lower()).strip()


def _same_district(a: str | None, b: str | None) -> bool:
    return bool(_district(a)) and _district(a) == _district(b)


async def _locate(market: str, district: str) -> tuple[dict | None, bool]:
    """(place or None, whether a new lookup was made). Lookup errors are not remembered."""
    key = f"{market}|{district}"
    if key in _located:
        return _located[key], False
    res = await geocode.search(market_query(market))
    if not res.ok:
        return None, True
    hits = res.data or []
    place = next((h for h in hits if _same_district(h.get("district"), district)), hits[0] if hits else None)
    _located[key] = place
    return place, True


def _today_text(snapshot_date: str | None, today: date) -> str:
    """'today' only when the data is from today; otherwise 'in the latest data (<date>)'."""
    return "today" if snapshot_date == today.isoformat() else f"in the latest data ({snapshot_date})"


async def nearest(place: dict, crop: dict, src: SourceResult, today: date) -> dict:
    """The nearest market within MANDI_MAX_DISTANCE_KM that reports the crop, or an explicit state."""
    out = {"status": "unknown", "crop": crop["crop"], "crop_word": crop["word"], "today": today.isoformat(),
           "snapshot_date": None, "market": None, "records": [], "nearest_beyond": None, "markets_reporting": 0,
           "markets_not_located": 0, "max_distance_km": config.MANDI_MAX_DISTANCE_KM, "note": None}
    if not src.ok:
        out["note"] = f"mandi prices unavailable ({src.error})"
        return out
    data = src.data
    out["snapshot_date"] = data["snapshot_date"]
    if not data["records"]:
        out["status"], out["note"] = "no_data", "data.gov.in returned no Karnataka mandi records"
        return out

    rows = [r for r in data["records"] if crops.matches(crop["crop"], r["commodity"])]
    markets: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        markets.setdefault((r["market"], r["district"]), []).append(r)
    out["markets_reporting"] = len(markets)
    when = _today_text(data["snapshot_date"], today)
    if not markets:
        out["status"], out["note"] = "no_market", f"no Karnataka market reports {crop['word']} {when}"
        return out

    # The farmer's own district first, so the cap on new lookups is spent where a near market is likely.
    order = sorted(markets, key=lambda k: (not _same_district(k[1], place.get("district")), k[1], k[0]))
    located, lookups, unlocated = [], 0, 0
    for market, district in order:
        if f"{market}|{district}" not in _located and lookups >= config.MANDI_MAX_GEOCODES:
            unlocated += 1
            continue
        hit, new = await _locate(market, district)
        lookups += new
        if hit is None:
            unlocated += 1
            continue
        km = distance_km(place["lat"], place["lon"], hit["lat"], hit["lon"])
        located.append((km, market, district, hit))
    out["markets_not_located"] = unlocated
    located.sort(key=lambda x: x[0])

    near = [x for x in located if x[0] <= config.MANDI_MAX_DISTANCE_KM]
    if not near:
        if located:
            km, market, district, _ = located[0]
            out["nearest_beyond"] = {"market": market, "district": district, "distance_km": km}
        if unlocated:
            out["status"] = "incomplete"
            out["note"] = (f"no market within {config.MANDI_MAX_DISTANCE_KM:g} km reports {crop['word']} {when} among "
                           f"those located; {unlocated} reporting market(s) could not be located")
        else:
            out["status"] = "no_nearby_market"
            out["note"] = f"no market within {config.MANDI_MAX_DISTANCE_KM:g} km reports {crop['word']} {when}"
        return out

    km, market, district, hit = near[0]
    recs = sorted(markets[(market, district)], key=lambda r: r["arrival_date"], reverse=True)
    out["market"] = {"name": market, "district": district, "distance_km": km,
                     "lat": hit["lat"], "lon": hit["lon"], "located_as": hit.get("name")}
    out["records"] = recs[: config.MANDI_MAX_VARIETIES]
    latest = out["records"][0]["arrival_date"]
    out["status"] = "found" if latest == today.isoformat() else "latest"
    return out
