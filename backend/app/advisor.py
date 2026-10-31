"""Orchestrates one advice request end to end. Never raises for data problems:
missing sources are reported in the response instead."""
import asyncio
import logging
import time
import uuid

from . import baseline, config, evidence, fallback, grounding, language, llm, prompts
from .http import SourceResult
from .rules import deficit as deficit_rule
from .rules import fertiliser as fertiliser_rule
from .rules import heat as heat_rule
from .rules import heavy_rain as heavy_rule
from .rules import irrigation as irrigation_rule
from .rules import soil as soil_rule
from .rules import spray as spray_rule
from .sources import forecast, geocode, rainfall, soil
from .timeutil import iso, now_local, parse_local

log = logging.getLogger(__name__)

# Rough bounding box of Karnataka, used to validate raw coordinates.
KARNATAKA_BBOX = {"lat": (11.5, 18.6), "lon": (74.0, 78.7)}

SOURCE_ATTRIBUTION = {
    "geocode": config.ATTRIBUTION["open-meteo"],
    "forecast": config.ATTRIBUTION["open-meteo"],
    "rain_mtd": config.ATTRIBUTION["open-meteo"],
    "rain_baseline": config.ATTRIBUTION["open-meteo"],
    "soil": config.ATTRIBUTION["soilgrids"],
    "user": "Coordinates entered by the user",
}


class AdviceError(Exception):
    def __init__(self, code: str, message: str, http_status: int):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


async def resolve_location(name: str | None, lat: float | None, lon: float | None) -> tuple[dict, SourceResult]:
    if lat is not None and lon is not None:
        if not (KARNATAKA_BBOX["lat"][0] <= lat <= KARNATAKA_BBOX["lat"][1]
                and KARNATAKA_BBOX["lon"][0] <= lon <= KARNATAKA_BBOX["lon"][1]):
            raise AdviceError("outside_region", "These coordinates are outside Karnataka.", 422)
        place = {"name": name or f"{lat:.4f}, {lon:.4f}", "district": None, "state": config.REGION_NAME,
                 "lat": lat, "lon": lon}
        return place, SourceResult("user", "User-provided coordinates", "", fetched_at=now_local())

    name = (name or config.DEFAULT_LOCATION).strip()
    geo = await geocode.search(name)
    if not geo.ok:
        raise AdviceError("geocoding_failed",
                          f"Could not look up the location right now ({geo.error}). Try again, or pick a place from the list.",
                          503)
    if not geo.data:
        raise AdviceError("location_not_found",
                          f"Could not find '{name}' in {config.REGION_NAME}. Check the spelling or try the nearest town.",
                          404)
    return geo.data[0], geo


def _clean_items(items, known_ids: set[str]) -> list[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict) or not str(it.get("text", "")).strip():
            continue
        ev = [e for e in it.get("evidence") or [] if e in known_ids]
        out.append({"text": str(it["text"]).strip(), "evidence": ev})
    return out


async def advise(question: str, location: str | None = None, lat: float | None = None,
                 lon: float | None = None, lang: str | None = None) -> dict:
    t0 = time.monotonic()
    question = (question or "").strip()
    if not question:
        raise AdviceError("empty_question", "Please type a question.", 422)
    if len(question) > 1000:
        raise AdviceError("question_too_long", "Please keep the question under 1000 characters.", 422)

    lang = language.resolve(lang, question)
    place, geo = await resolve_location(location, lat, lon)
    now = now_local()

    # --- fetch all live data in parallel ------------------------------------
    win_start, win_end = deficit_rule.window(now.date())
    y0, y1 = rainfall.baseline_years(now.date())
    # One forecast request also returns this month's past daily rain (past_days).
    # The long-run baseline is read from the stored per-district file, never fetched here.
    fc, base, soil_src = await asyncio.gather(
        forecast.fetch(place["lat"], place["lon"], past_from=win_start, today=now.date()),
        baseline.store.get(place, now.date()),
        soil.fetch(place["lat"], place["lon"]),
    )
    mtd = rainfall.month_to_date(fc)
    # Average over the years actually stored (a stored baseline can lag a year until it is rebuilt).
    base_years = (base.data["start_year"], base.data["end_year"]) if base.ok else (y0, y1)
    sources = [geo, fc, mtd, base, soil_src]
    failed = [{"id": s.source_id, "name": s.name, "error": s.error} for s in sources if not s.ok]
    stale = [s for s in sources if s.ok and s.stale]
    fallbacks = [s for s in sources if s.ok and s.meta.get("fallback_for")]

    # --- apply rules -------------------------------------------------------
    results = {
        "spray": spray_rule.find_windows(fc.data["hours"], now) if fc.ok else None,
        "heavy_rain": heavy_rule.evaluate(fc.data["hours"], now) if fc.ok else None,
        "deficit": deficit_rule.evaluate(mtd.data["daily"] if mtd.ok else None,
                                         base.data["daily"] if base.ok else None,
                                         win_start, win_end, *base_years),
        "soil": soil_rule.evaluate(soil_src.data["properties"] if soil_src.ok else None),
        "irrigation": irrigation_rule.plan(fc.data.get("days", [])) if fc.ok else None,
        "heat": heat_rule.evaluate(fc.data.get("days", [])) if fc.ok else None,
        "fertiliser": fertiliser_rule.evaluate(fc.data["hours"], now) if fc.ok else None,
    }

    ev = evidence.Evidence()
    evidence.add_location(ev, place, geo)
    evidence.add_forecast(ev, fc, now)
    evidence.add_spray(ev, fc, results["spray"] or {})
    evidence.add_heavy_rain(ev, fc, results["heavy_rain"] or {})
    evidence.add_deficit(ev, mtd, base, results["deficit"])
    evidence.add_soil(ev, soil_src, results["soil"])
    evidence.add_irrigation(ev, fc, results["irrigation"])
    evidence.add_heat(ev, fc, results["heat"])
    evidence.add_fertiliser(ev, fc, results["fertiliser"])
    known = {p["id"] for p in ev.points}

    # --- language model (or deterministic fallback) -------------------------
    llm_error = None
    generated_by = config.LLM_MODEL
    try:
        msg = prompts.build_user_message(question, config.SUPPORTED_LANGUAGES[lang], place, iso(now),
                                         ev.points, ev.rules, failed, _freshness(sources, now))
        raw, generated_by = await llm.generate(msg)
    except llm.LLMError as e:
        llm_error = str(e)
        generated_by = "rules-fallback"
        raw = fallback.compose(lang, results, ev.rules, failed)

    answer = {
        "text": str(raw.get("answer", "")).strip(),
        "recommendations": _clean_items(raw.get("recommendations"), known),
        "why": _clean_items(raw.get("why"), known),
        "missing_data": [str(m) for m in raw.get("missing_data") or [] if str(m).strip()],
        "disclaimer": str(raw.get("disclaimer") or fallback.T[lang]["disclaimer"]).strip(),
    }

    # --- grounding check: every number must trace back to retrieved data ---
    allowed = grounding.allowed_numbers(evidence.all_values(ev, [iso(now)]))
    all_text = " ".join([answer["text"]] + [r["text"] for r in answer["recommendations"] + answer["why"]])
    unverified = grounding.unverified_numbers(all_text, allowed)

    return {
        "request_id": uuid.uuid4().hex[:12],
        "generated_at": iso(now),
        "elapsed_ms": round((time.monotonic() - t0) * 1000),
        "question": question,
        "language": lang,
        "location": {**place, "source": geo.name,
                     "fetched_at": iso(geo.fetched_at) if geo.fetched_at else None},
        "answer": answer,
        "generated_by": generated_by,
        "llm_error": llm_error,
        "unverified_numbers": unverified,
        "data_points": ev.points,
        "rules": ev.rules,
        "spray_windows": (results["spray"] or {}).get("windows", []),
        "forecast_hourly": _series(fc, now),
        "forecast_daily": _daily(fc),
        "water_balance": results["irrigation"],
        "heat": results["heat"],
        "fertiliser": results["fertiliser"],
        "sources": [_source_view(s, now) for s in sources],
        "data_age": _freshness(sources, now),
        "warnings": [f"{f['name']} unavailable: {f['error']}" for f in failed]
                    + [f"{s.name}: live refresh failed ({s.error}); showing data fetched {iso(s.fetched_at)}"
                       for s in stale]
                    + [f"{s.error} Fetched {iso(s.fetched_at)}." for s in fallbacks]
                    + ([f"Language model unavailable ({llm_error}); showing a rule-based summary."] if llm_error else []),
        "attribution": sorted(set(config.ATTRIBUTION.values())),
    }


def _series(fc: SourceResult, now) -> dict | None:
    if not fc.ok:
        return None
    current = now.replace(minute=0, second=0, microsecond=0)
    hours = [h for h in fc.data["hours"] if parse_local(h["time"]) >= current][: config.FORECAST_HOURS]
    return {"source": fc.name, "fetched_at": iso(fc.fetched_at), "units": fc.data.get("units", {}), "hours": hours}


def _age_minutes(s: SourceResult, now) -> int | None:
    return max(0, round((now - s.fetched_at).total_seconds() / 60)) if s.fetched_at else None


def _freshness(sources: list[SourceResult], now) -> list[dict]:
    """How old each piece of data is, and whether it came from the cache or a saved copy."""
    out = []
    for s in sources:
        if not s.ok or s.source_id == "user":
            continue
        out.append({"source": s.name, "fetched_at": iso(s.fetched_at) if s.fetched_at else None,
                    "age_minutes": _age_minutes(s, now), "cached": s.cached, "stale": s.stale})
    return out


def _daily(fc: SourceResult) -> dict | None:
    if not fc.ok or not fc.data.get("days"):
        return None
    return {"source": fc.name, "fetched_at": iso(fc.fetched_at), "units": fc.data.get("daily_units", {}),
            "days": fc.data["days"][: config.FORECAST_DAILY_DAYS]}


def _source_view(s: SourceResult, now) -> dict:
    return {
        "id": s.source_id,
        "name": s.name,
        "url": s.url,
        "status": s.status,
        "fetched_at": iso(s.fetched_at) if s.fetched_at else None,
        "cached": s.cached,
        "stale": s.stale,
        "fallback_for": s.meta.get("fallback_for"),
        "note": s.error if s.ok else None,
        "age_minutes": _age_minutes(s, now),
        "error": s.error,
        "attribution": SOURCE_ATTRIBUTION.get(s.source_id),
    }
