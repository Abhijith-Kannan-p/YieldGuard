"""'Today in your field': a short live summary for the landing page and saved fields.

No language model and no baseline fetch: it reuses the same cached forecast request as
the advice page (so the two share one Open-Meteo call per hour per location) and the
cached SoilGrids response. The computed summary itself is cached per location for
TTL_TODAY (one hour), so a location is refreshed from the APIs at most once per hour.
"""
from . import baseline, config
from .advisor import resolve_location
from .cache import TTLCache
from .http import SourceResult, coord_key
from .rules import deficit as deficit_rule
from .rules import fertiliser as fertiliser_rule
from .rules import heat as heat_rule
from .rules import heavy_rain as heavy_rule
from .rules import soil as soil_rule
from .rules import spray as spray_rule
from .sources import forecast, rainfall, soil
from .timeutil import iso, now_local

_cache = TTLCache()


def cache_key(location: str | None, lat: float | None, lon: float | None) -> str:
    if lat is not None and lon is not None:
        return f"today:{coord_key(lat, lon)}"
    return f"today:{(location or config.DEFAULT_LOCATION).strip().lower()}"


def _src(s: SourceResult) -> dict:
    return {"name": s.name, "status": s.status, "fetched_at": iso(s.fetched_at) if s.fetched_at else None,
            "cached": s.cached, "stale": s.stale, "error": s.error}


async def summary(location: str | None = None, lat: float | None = None, lon: float | None = None) -> dict:
    key = cache_key(location, lat, lon)
    hit = _cache.get(key)
    if hit is not None:
        return {**hit.value, "served_from_cache": True}

    place, geo = await resolve_location(location, lat, lon)
    now = now_local()
    win_start, win_end = deficit_rule.window(now.date())
    fc = await forecast.fetch(place["lat"], place["lon"], past_from=win_start, today=now.date())
    soil_src = await soil.fetch(place["lat"], place["lon"])
    base = await baseline.store.get(place, now.date())  # stored file only, never fetched here

    out: dict = {
        "location": {"name": place["name"], "district": place.get("district"), "lat": place["lat"], "lon": place["lon"]},
        "computed_at": iso(now),
        "refresh_after_s": config.TTL_TODAY,
        "sources": {"forecast": _src(fc), "soil": _src(soil_src), "baseline": _src(base)},
        "spray": None, "rain_24h": None, "soil": None, "warnings": [],
    }

    if fc.ok:
        hours = fc.data["hours"]
        windows = spray_rule.find_windows(hours, now)["windows"]
        out["spray"] = {"next": windows[0] if windows else None, "hours_checked": len(hours),
                        "thresholds": {"max_wind_kmh": config.SPRAY_MAX_WIND_KMH,
                                       "max_precip_prob_pct": config.SPRAY_MAX_PRECIP_PROB_PCT}}
        hr = heavy_rule.evaluate(hours, now)
        out["rain_24h"] = {"max_prob_pct": hr["max_precip_prob_pct"], "max_prob_time": hr["max_precip_prob_time"],
                           "total_mm": hr["total_precip_mm"], "window_start": hr["window_start"],
                           "window_end": hr["window_end"], "status": hr["status"]}
        if hr["status"] == "warning":
            out["warnings"].append({"id": "heavy_rain", "time": hr["max_precip_prob_time"],
                                    "value": hr["max_precip_prob_pct"], "unit": "%"})
        ht = heat_rule.evaluate(fc.data.get("days", []))
        if ht["status"] == "warning":
            first = ht["hot_days"][0]
            out["warnings"].append({"id": "heat", "time": first["date"], "value": first["tmax_c"], "unit": "°C"})
        fe = fertiliser_rule.evaluate(hours, now)
        if fe["status"] == "delay":
            out["warnings"].append({"id": "fertiliser", "time": fe["max_precip_prob_time"],
                                    "value": fe["max_precip_prob_pct"], "unit": "%"})
        mtd = rainfall.month_to_date(fc)
        if base.ok:
            df = deficit_rule.evaluate(mtd.data["daily"], base.data["daily"], win_start, win_end,
                                       base.data["start_year"], base.data["end_year"])
            if df["status"] in ("drought_risk", "waterlogging_risk"):
                out["warnings"].append({"id": df["status"], "time": f"{win_start} to {win_end}",
                                        "value": df["percent_of_normal"], "unit": "% of normal"})

    if soil_src.ok:
        res = soil_rule.evaluate(soil_src.data["properties"])
        props = soil_src.data["properties"]
        out["soil"] = {"sand_pct": (props.get("sand") or {}).get("value"),
                       "clay_pct": (props.get("clay") or {}).get("value"),
                       "ph": (props.get("phh2o") or {}).get("value"),
                       "flags": res["flags"], "offset_km": soil_src.data.get("offset_km")}

    _cache.set(key, out, now, config.TTL_TODAY)
    return {**out, "served_from_cache": False}


def clear() -> None:
    _cache.clear()

