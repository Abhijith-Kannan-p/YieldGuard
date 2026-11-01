"""Mandi prices: Agmarknet daily prices from data.gov.in, nearest reporting market to the farmer.

- One cached snapshot of all Karnataka records (paged on "total"), refreshed every TTL_MANDI.
  The API only serves the latest day per market; the arrival_date filter is ignored.
- Prices are Rs per quintal, as the API gives them. Rows without a usable modal price are skipped.
- data.gov.in can take a minute to answer. A question waits at most MANDI_WAIT_S; a slower fetch
  keeps running and fills the cache for the next question. After a failure no new attempt is made
  for MANDI_RETRY_AFTER_S (a saved snapshot is shown meanwhile, with its fetch time).
- If the live call fails (or no key is set), a saved copy is used: the in-memory one, or the copy published
  from a home connection to the "data" branch on GitHub (publish_mandi_snapshot.py), whichever was
  fetched later. It is labelled "saved copy" with its own fetch time; one older than MANDI_SAVED_MAX_AGE_DAYS
  (by newest arrival date) is not used.
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
from ..timeutil import TZ, iso, now_local
from . import geocode
from .soil import distance_km

log = logging.getLogger(__name__)

NAME = "Agmarknet mandi prices (data.gov.in)"
CACHE_KEY = "mandi:karnataka"
SAVED_KEY = "mandi:saved"
DATED_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
UNIT = "Rs/quintal"
MAX_PLAUSIBLE_PRICE = 1_000_000  # Rs per quintal; above this a row is treated as broken

_clock = time.monotonic  # replaced in tests
_retry_at = 0.0
_saved_retry_at = 0.0
_task: asyncio.Task | None = None
_located: dict[str, dict | None] = {}  # "market|district" -> geocoded place, or None if not found


def clear() -> None:
    global _retry_at, _saved_retry_at, _task
    _retry_at, _saved_retry_at, _task = 0.0, 0.0, None
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


async def _live() -> SourceResult:
    """The live call (cached TTL_MANDI), or the in-memory copy marked stale, or failed. Waits at most MANDI_WAIT_S."""
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


def _raw_url(name: str) -> str:
    return (f"{config.MANDI_SAVED_RAW_BASE}/{config.MANDI_SAVED_REPO}/{config.MANDI_SAVED_BRANCH}/"
            f"{config.MANDI_SAVED_DIR}/{name}")


async def _newest_saved_name() -> str:
    """The newest dated file: from index.json, or from the GitHub contents API if the index is missing."""
    try:
        index = await get_json(_raw_url("index.json"), None)
        names = index.get("files") if isinstance(index, dict) else None
    except FetchError as e:
        if e.status != 404:
            raise
        listing = await get_json(f"{config.MANDI_SAVED_API_BASE}/repos/{config.MANDI_SAVED_REPO}/contents/"
                                 f"{config.MANDI_SAVED_DIR}", {"ref": config.MANDI_SAVED_BRANCH})
        names = [x.get("name") for x in listing if isinstance(x, dict)] if isinstance(listing, list) else None
    dated = sorted(n for n in names or [] if isinstance(n, str) and DATED_FILE.match(n))
    if not dated:
        raise FetchError("the data branch has no saved snapshot")
    return dated[-1]


async def _load_saved() -> dict:
    """The newest saved snapshot, parsed like a live one. Empty or invalid files are refused, never used."""
    name = await _newest_saved_name()
    doc = await get_json(_raw_url(name), None)
    if not isinstance(doc, dict) or not isinstance(doc.get("records"), list):
        raise FetchError(f"saved snapshot {name} is not valid")
    data = parse(doc["records"], 0)
    if not data["records"]:
        raise FetchError(f"saved snapshot {name} has no usable records")
    try:
        fetched_at = datetime.fromisoformat(str(doc.get("fetched_at"))).astimezone(TZ)
        data["total"] = int(doc.get("total") or 0)
    except (TypeError, ValueError):
        raise FetchError(f"saved snapshot {name} is not valid") from None
    return {"data": data, "fetched_at": iso(fetched_at), "file": name}


async def saved_copy() -> SourceResult:
    """The data-branch copy, cached TTL_MANDI_SAVED; after a failure no new attempt for MANDI_SAVED_RETRY_AFTER_S."""
    global _saved_retry_at
    if not config.MANDI_SAVED_REPO:
        return SourceResult("mandi", NAME, "", status="failed", error="no saved-copy repository is configured")
    wait = _saved_retry_at - _clock()
    if wait > 0 and cache.get(SAVED_KEY) is None:
        return SourceResult("mandi", NAME, "", status="failed", error=f"failed recently; next attempt in {wait:.0f} s")
    res = await cached_fetch("mandi", NAME, _raw_url("index.json"), SAVED_KEY, config.TTL_MANDI_SAVED, _load_saved)
    if not res.ok:
        _saved_retry_at = _clock() + config.MANDI_SAVED_RETRY_AFTER_S
    return res


def _too_old(data: dict, today: date) -> str | None:
    """Why a copy is too old to show, by its newest arrival date, or None."""
    newest = data.get("snapshot_date")
    if newest and (today - date.fromisoformat(newest)).days > config.MANDI_SAVED_MAX_AGE_DAYS:
        return f"latest arrival date {newest} is more than {config.MANDI_SAVED_MAX_AGE_DAYS:g} days old"
    return None


def _when(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%d %b %Y, %H:%M IST").lstrip("0")


async def fetch() -> SourceResult:
    """Live first. Otherwise the newer of the in-memory copy and the data-branch copy (a tie keeps the in-memory one),
    labelled "saved copy" with its own fetch time and a note naming the live failure. Else failed with both causes."""
    live = await _live()
    if live.ok and not live.stale:
        return live
    cause = live.error if live.error.startswith("data.gov.in") else f"data.gov.in failed ({live.error})"
    today = now_local().date()
    candidates = []
    if live.ok and not _too_old(live.data, today):
        candidates.append(("memory", live.fetched_at, live.data, config.MANDI_URL))
    saved = await saved_copy()
    saved_why = saved.error
    if saved.ok:
        when = datetime.fromisoformat(saved.data["fetched_at"])
        saved_why = _too_old(saved.data["data"], today)
        if saved_why is None:
            candidates.append(("data branch", when, saved.data["data"], _raw_url(saved.data["file"])))
    if not candidates:
        memory_why = f"; in-memory copy: {_too_old(live.data, today)}" if live.ok else ""
        return SourceResult("mandi", NAME, config.MANDI_URL, status="failed",
                            error=f"{cause}; saved copy unavailable ({saved_why}){memory_why}")
    where, when, data, url = max(candidates, key=lambda c: c[1])  # max keeps the first (in-memory) on a tie
    label = "the YieldGuard data branch" if where == "data branch" else "this server's memory"
    return SourceResult("mandi", f"{NAME}, saved copy from {label}", url, data=data, fetched_at=when, cached=True,
                        stale=True, error=f"{cause}; showing the copy fetched {_when(when)} from {label}",
                        meta={"saved_copy": where})


def market_query(market: str) -> str:
    """Market name -> place name to geocode: "Ranebennur APMC" -> "Ranebennur"."""
    name = re.sub(r"\(.*?\)", " ", market)
    name = re.sub(r"\b(apmc|f&v|market|yard|sub|main|mandi)\b", " ", name, flags=re.I)
    return " ".join(name.split())


def lookup_name(market: str) -> str:
    """The name to geocode: the cleaned market name, or its alias from MARKET_GEOCODE_NAMES."""
    q = market_query(market)
    return config.MARKET_GEOCODE_NAMES.get(q, q)


def _district(s: str | None) -> str:
    return re.sub(r"\bdistrict\b", "", (s or "").lower()).strip()


def _same_district(a: str | None, b: str | None) -> bool:
    return bool(_district(a)) and _district(a) == _district(b)


async def _locate(market: str, district: str) -> tuple[dict | None, bool]:
    """(place or None, whether a new lookup was made). Lookup errors are not remembered."""
    key = f"{market}|{district}"
    if key in _located:
        return _located[key], False
    res = await geocode.search(lookup_name(market))
    if not res.ok:
        return None, True
    hits = res.data or []
    place = next((h for h in hits if _same_district(h.get("district"), district)), hits[0] if hits else None)
    _located[key] = place
    return place, True


def _today_text(snapshot_date: str | None, today: date) -> str:
    """'today' only when the data is from today; otherwise 'in the latest data (<date>)'."""
    return "today" if snapshot_date == today.isoformat() else f"in the latest data ({snapshot_date})"


def _latest_first(recs: list[dict]) -> list[dict]:
    return sorted(recs, key=lambda r: r["arrival_date"], reverse=True)[: config.MANDI_MAX_VARIETIES]


async def nearest(place: dict, crop: dict, src: SourceResult, today: date, commodity: str | None = None) -> dict:
    """The nearest market within MANDI_MAX_DISTANCE_KM that reports the crop, or an explicit state.
    `commodity`: an exact Agmarknet name (Mandi page); without it the crop's aliases are matched (advice).
    `nearby` lists the other located markets within the limit, nearest first."""
    out = {"status": "unknown", "crop": crop["crop"], "crop_word": crop["word"], "commodity": commodity,
           "today": today.isoformat(), "snapshot_date": None, "market": None, "records": [], "nearby": [],
           "nearest_beyond": None, "markets_reporting": 0, "markets_not_located": 0,
           "max_distance_km": config.MANDI_MAX_DISTANCE_KM, "note": None}
    if not src.ok:
        out["note"] = f"mandi prices unavailable ({src.error})"
        return out
    data = src.data
    out["snapshot_date"] = data["snapshot_date"]
    if not data["records"]:
        out["status"], out["note"] = "no_data", "data.gov.in returned no Karnataka mandi records"
        return out

    rows = [r for r in data["records"]
            if (r["commodity"] == commodity if commodity else crops.matches(crop["crop"], r["commodity"]))]
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
    out["market"] = {"name": market, "district": district, "distance_km": km,
                     "lat": hit["lat"], "lon": hit["lon"], "located_as": hit.get("name")}
    out["records"] = _latest_first(markets[(market, district)])
    out["nearby"] = [{"market": m, "district": d, "distance_km": k, "located_as": h.get("name"),
                      "records": _latest_first(markets[(m, d)])} for k, m, d, h in near[1:]]
    latest = out["records"][0]["arrival_date"]
    out["status"] = "found" if latest == today.isoformat() else "latest"
    return out
