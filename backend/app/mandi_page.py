"""The Mandi page: today's reported prices without asking a question. No language model.

Both endpoints read the same cached data.gov.in snapshot as the advice page (sources/mandi.py) and label
it the same way (live / cached / saved copy / unavailable) with its fetch time.
"""
from . import config, crops
from .advisor import _source_view, resolve_location
from .sources import mandi
from .timeutil import iso, now_local


def _status(src) -> str:
    if not src.ok:
        return "unavailable"
    return "ok" if src.data["records"] else "no_data"


async def crop_list() -> dict:
    """The commodities in the current Karnataka snapshot, for the crop picker."""
    now = now_local()
    src = await mandi.fetch()
    status = _status(src)
    return {
        "status": status,
        "crops": crops.snapshot_crops(src.data["records"]) if status == "ok" else [],
        "snapshot_date": src.data["snapshot_date"] if src.ok else None,
        "today": now.date().isoformat(),
        "computed_at": iso(now),
        "source": _source_view(src, now),
        "attribution": config.ATTRIBUTION["datagov"],
    }


async def prices(location: str | None, lat: float | None, lon: float | None, commodity: str) -> dict:
    """The nearest market within MANDI_MAX_DISTANCE_KM reporting this exact commodity, and the others nearby."""
    place, geo = await resolve_location(location, lat, lon)
    now = now_local()
    src = await mandi.fetch()
    alias = crops.alias_for(commodity)
    res = await mandi.nearest(place, {"crop": alias, "word": commodity}, src, now.date(), commodity=commodity)
    listed = crops.snapshot_crops(src.data["records"]) if _status(src) == "ok" else []
    labels = next((c["labels"] for c in listed if c["commodity"] == commodity),
                  {"en": commodity, "hi": commodity, "kn": commodity})
    return {
        **res,
        "labels": labels,
        "location": {"name": place["name"], "district": place.get("district"), "lat": place["lat"],
                     "lon": place["lon"], "source": geo.name},
        "computed_at": iso(now),
        "source": _source_view(src, now),
        "attribution": config.ATTRIBUTION["datagov"],
    }
