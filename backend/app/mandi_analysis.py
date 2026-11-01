"""The Mandi page analysis: one crop at the nearest reporting market, the markets nearby, the price spread and
varieties, and the forecast for harvest and transport timing. Gemini writes it from these data points only,
with the same citations and number check as the advice page; without Gemini a labelled rule-based summary.

The forecast comes from the visitor's browser, as on the advice page (MET Norway if that fetch failed).
A repeat request for the same place, crop and language within TTL_MANDI_ANALYSIS returns the cached result.
"""
import time
import uuid

from . import config, crops, evidence, fallback, grounding, llm, prompts
from .advisor import _forecast, _freshness, _source_view, resolve_location
from .cache import TTLCache
from .http import coord_key
from .rules import deficit as deficit_rule
from .rules import dry_days as dry_rule
from .rules import heat as heat_rule
from .rules import heavy_rain as heavy_rule
from .sources import mandi
from .timeutil import iso, now_local

_cache = TTLCache()


def clear() -> None:
    _cache.clear()


def _clean_sections(items, known: set[str]) -> list[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict) or not str(it.get("text", "")).strip():
            continue
        out.append({"title": str(it.get("title", "")).strip(), "text": str(it["text"]).strip(),
                    "evidence": [e for e in it.get("evidence") or [] if e in known]})
    return out


async def analyse(commodity: str, location: str | None, lat: float | None, lon: float | None, lang: str,
                  client_forecast: dict) -> dict:
    t0 = time.monotonic()
    lang = lang if lang in config.SUPPORTED_LANGUAGES else "en"
    place, geo = await resolve_location(location, lat, lon)
    key = f"analysis:{coord_key(place['lat'], place['lon'])}:{commodity}:{lang}"
    hit = _cache.get(key)
    if hit is not None:
        return {**hit.value, "served_from_cache": True}

    now = now_local()
    mandi_src = await mandi.fetch()
    alias = crops.alias_for(commodity)
    res = await mandi.nearest(place, {"crop": alias, "word": commodity}, mandi_src, now.date(), commodity=commodity)
    listed = crops.snapshot_crops(mandi_src.data["records"]) if mandi_src.ok and mandi_src.data["records"] else []
    labels = next((c["labels"] for c in listed if c["commodity"] == commodity),
                  {"en": commodity, "hi": commodity, "kn": commodity})
    res["crop_word"] = labels[lang]

    win_start, _ = deficit_rule.window(now.date())
    fc = await _forecast(client_forecast, place, win_start, now)
    days = fc.data.get("days", []) if fc.ok else []
    heavy = heavy_rule.evaluate(fc.data["hours"], now) if fc.ok else None
    heat = heat_rule.evaluate(days) if fc.ok else None
    dry = dry_rule.evaluate(days) if fc.ok else None

    ev = evidence.Evidence()
    evidence.add_location(ev, place, geo)
    evidence.add_mandi(ev, mandi_src, res)
    evidence.add_market_compare(ev, mandi_src, res)
    evidence.add_heavy_rain(ev, fc, heavy or {})
    evidence.add_heat(ev, fc, heat)
    evidence.add_dry_days(ev, fc, dry)
    known = {p["id"] for p in ev.points} | {r["id"] for r in ev.rules}

    sources = [mandi_src, fc]
    failed = [{"id": s.source_id, "name": s.name, "error": s.error} for s in sources if not s.ok]
    llm_error, generated_by = None, config.LLM_MODEL
    try:
        msg = prompts.build_mandi_message(config.SUPPORTED_LANGUAGES[lang], place, labels[lang], iso(now), ev.points,
                                          ev.rules, failed, _freshness(sources, now))
        raw, generated_by = await llm.mandi_analysis(msg)
    except llm.LLMError as e:
        llm_error, generated_by = str(e), "rules-fallback"
        raw = fallback.compose_mandi_analysis(lang, res, heavy, heat, dry)

    analysis = {
        "summary": str(raw.get("summary", "")).strip(),
        "sections": _clean_sections(raw.get("sections"), known),
        "missing_data": [str(m) for m in raw.get("missing_data") or [] if str(m).strip()],
        "disclaimer": str(raw.get("disclaimer") or fallback.TA[lang]["disclaimer"]).strip(),
    }
    allowed = grounding.allowed_numbers(evidence.all_values(ev, [iso(now)]))
    text = " ".join([analysis["summary"]] + [s["title"] + " " + s["text"] for s in analysis["sections"]])
    stale = [s for s in sources if s.ok and s.stale]
    fallbacks = [s for s in sources if s.ok and s.meta.get("fallback_for")]
    out = {
        "request_id": uuid.uuid4().hex[:12],
        "generated_at": iso(now),
        "elapsed_ms": round((time.monotonic() - t0) * 1000),
        "language": lang,
        "commodity": commodity,
        "labels": labels,
        "location": {"name": place["name"], "district": place.get("district"), "lat": place["lat"], "lon": place["lon"]},
        "mandi": res,
        "analysis": analysis,
        "generated_by": generated_by,
        "llm_error": llm_error,
        "unverified_numbers": grounding.unverified_numbers(text, allowed),
        "data_points": ev.points,
        "rules": ev.rules,
        "sources": [_source_view(s, now) for s in sources],
        "warnings": [f"{f['name']} unavailable: {f['error']}" for f in failed]
                    + [f"{s.name}: {s.error}" for s in stale]
                    + [f"{s.error} Fetched {iso(s.fetched_at)}." for s in fallbacks]
                    + ([f"Language model unavailable ({llm_error}); showing a rule-based summary."] if llm_error else []),
        "served_from_cache": False,
    }
    _cache.set(key, out, now, config.TTL_MANDI_ANALYSIS)
    return out
