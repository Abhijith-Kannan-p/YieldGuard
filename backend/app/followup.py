"""Follow-up questions answered from the data stored with the previous answer.

No weather or soil API is called here: the context saved in the session (see context_from)
is the only data. Gemini must cite the fields or rules it used; an answer that cites nothing
from the stored data is treated as "not covered", whatever the model says.
"""
import math
import uuid
from datetime import datetime

from . import config, grounding, language, llm, prompts, sessions
from .advisor import AdviceError
from .timeutil import iso, now_local

NOT_COVERED = {
    "en": "The data from your last answer does not cover this question. Ask a new question, or check with your "
          "local Krishi Vigyan Kendra (KVK) or agriculture officer.",
    "hi": "आपके पिछले जवाब का डेटा इस सवाल को कवर नहीं करता। नया सवाल पूछें, या अपने स्थानीय कृषि विज्ञान केंद्र (KVK) "
          "या कृषि अधिकारी से पूछें।",
    "kn": "ನಿಮ್ಮ ಹಿಂದಿನ ಉತ್ತರದ ಮಾಹಿತಿ ಈ ಪ್ರಶ್ನೆಗೆ ಸಾಕಾಗುವುದಿಲ್ಲ. ಹೊಸ ಪ್ರಶ್ನೆ ಕೇಳಿ, ಅಥವಾ ನಿಮ್ಮ ಸ್ಥಳೀಯ ಕೃಷಿ ವಿಜ್ಞಾನ ಕೇಂದ್ರ (KVK) "
          "ಅಥವಾ ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಕೇಳಿ.",
}
DISCLAIMER = {
    "en": "Please confirm with your local Krishi Vigyan Kendra (KVK) or agriculture officer before acting.",
    "hi": "कोई भी कदम उठाने से पहले अपने स्थानीय कृषि विज्ञान केंद्र (KVK) या कृषि अधिकारी से पुष्टि करें।",
    "kn": "ಯಾವುದೇ ಕ್ರಮ ಕೈಗೊಳ್ಳುವ ಮೊದಲು ನಿಮ್ಮ ಸ್ಥಳೀಯ ಕೃಷಿ ವಿಜ್ಞಾನ ಕೇಂದ್ರ (KVK) ಅಥವಾ ಕೃಷಿ ಅಧಿಕಾರಿಯೊಂದಿಗೆ ಖಚಿತಪಡಿಸಿಕೊಳ್ಳಿ.",
}
HOUR_FIELDS = ("temperature_2m", "relative_humidity_2m", "precipitation_probability", "precipitation", "wind_speed_10m")
THREAD_KEEP = 5  # earlier follow-ups passed back to the model for context


def context_from(result: dict) -> dict:
    """What a session keeps from a full answer: everything the answer was built on, with sources and times."""
    fh = result.get("forecast_hourly") or {}
    fd = result.get("forecast_daily") or {}
    forecast_fetched = fh.get("fetched_at") or fd.get("fetched_at")
    return {
        "request_id": result["request_id"],
        "question": result["question"],
        "language": result["language"],
        "answer_text": result["answer"]["text"],
        "generated_at": result["generated_at"],
        "location": {k: result["location"].get(k) for k in ("name", "district", "lat", "lon", "source", "fetched_at")},
        "data_points": [{k: p[k] for k in ("id", "label", "value", "unit", "valid_time", "source_id", "source",
                                            "fetched_at")} for p in result["data_points"]],
        "rules": [{k: r[k] for k in ("id", "name", "status", "summary", "thresholds", "evidence")} for r in result["rules"]],
        "forecast_source": fh.get("source") or fd.get("source"),
        "forecast_fetched_at": forecast_fetched,
        "forecast_hours": [{"id": f"hour:{h['time']}", "time": h["time"], **{k: h.get(k) for k in HOUR_FIELDS}}
                           for h in fh.get("hours", [])],
        "forecast_days": [{"id": f"day:{d['date']}", **d} for d in fd.get("days", [])],
        "failed_sources": [{"name": s["name"], "error": s["error"]} for s in result["sources"] if s["status"] != "ok"],
        "sources": result["sources"],
        # Age of the stored data is measured from the forecast fetch (the time-sensitive part).
        "data_fetched_at": forecast_fetched or result["generated_at"],
        "thread": [],
    }


def _evidence_index(ctx: dict) -> dict[str, dict]:
    """Every id the model may cite, shaped like a data point so the page can show source and times."""
    idx = {p["id"]: p for p in ctx["data_points"]}
    for r in ctx["rules"]:
        idx[f"rule:{r['id']}"] = {"id": f"rule:{r['id']}", "label": f"Rule: {r['name']}", "value": r["status"],
                                  "unit": "", "valid_time": None, "source_id": "rules",
                                  "source": "YieldGuard rules (config.py)", "fetched_at": ctx["generated_at"]}
    for h in ctx["forecast_hours"]:
        value = (f"wind {h['wind_speed_10m']} km/h, rain chance {h['precipitation_probability']}%, "
                 f"rain {h['precipitation']} mm, {h['temperature_2m']} °C")
        idx[h["id"]] = {"id": h["id"], "label": "Forecast hour", "value": value, "unit": "", "valid_time": h["time"],
                        "source_id": "forecast", "source": ctx["forecast_source"],
                        "fetched_at": ctx["forecast_fetched_at"]}
    for d in ctx["forecast_days"]:
        value = (f"max {d.get('temperature_2m_max')} °C, rain {d.get('precipitation_sum')} mm, "
                 f"ET0 {d.get('et0_fao_evapotranspiration')} mm")
        idx[d["id"]] = {"id": d["id"], "label": "Forecast day", "value": value, "unit": "", "valid_time": d["date"],
                        "source_id": "forecast", "source": ctx["forecast_source"],
                        "fetched_at": ctx["forecast_fetched_at"]}
    return idx


def _allowed_values(ctx: dict, now_iso: str) -> list:
    vals: list = [now_iso, ctx["generated_at"], ctx["data_fetched_at"]]
    for p in ctx["data_points"]:
        vals += [p["value"], p["valid_time"], p["fetched_at"]]
    for r in ctx["rules"]:
        vals += [v for v in r["thresholds"].values() if not isinstance(v, (list, dict))]
        vals += [x for v in r["thresholds"].values() if isinstance(v, list) for x in v]
    for h in ctx["forecast_hours"]:
        vals += [h["time"], *(h.get(k) for k in HOUR_FIELDS)]
    for d in ctx["forecast_days"]:
        vals += list(d.values())
    vals += [config.FORECAST_HOURS, config.FORECAST_DAILY_DAYS, config.FERTILISER_LOOKAHEAD_H]
    return vals


def _minutes_since(ts: str, now: datetime) -> int:
    return max(0, math.floor((now - datetime.fromisoformat(ts)).total_seconds() / 60))


async def answer(session: sessions.Session | None, question: str, lang: str | None = None) -> dict:
    question = (question or "").strip()
    if not question:
        raise AdviceError("empty_question", "Please type a follow-up question.", 422)
    if len(question) > 1000:
        raise AdviceError("question_too_long", "Please keep the question under 1000 characters.", 422)
    if session is None or session.context is None:
        raise AdviceError("no_session",
                          "No earlier answer was found for this browser session (sessions last 30 minutes). "
                          "Ask a full question first.", 409)

    ctx, now = session.context, now_local()
    used, wait_s = sessions.followup_allowance(session)
    if used >= config.FOLLOWUP_LIMIT:
        raise AdviceError("followup_limit",
                          f"You have asked {config.FOLLOWUP_LIMIT} follow-up questions in the last "
                          f"{config.FOLLOWUP_WINDOW_S // 60} minutes. Try again in {max(1, math.ceil(wait_s / 60))} "
                          f"minutes, or ask a new full question.", 429)
    age_min = _minutes_since(ctx["data_fetched_at"], now)
    if age_min * 60 > config.FOLLOWUP_MAX_DATA_AGE_S:
        raise AdviceError("data_stale",
                          f"The data behind this answer was fetched {age_min} minutes ago, at "
                          f"{ctx['data_fetched_at'][11:16]} IST. Refresh the data before asking more.", 409)

    lang = language.resolve(lang or "auto", question)
    sessions.record_followup(session)

    msg = prompts.build_followup_message(question, config.SUPPORTED_LANGUAGES[lang], ctx, iso(now), ctx["thread"])
    try:
        raw, model = await llm.followup(msg)
    except llm.LLMError as e:
        raise AdviceError("llm_unavailable",
                          f"Follow-up questions need the language model, which is unavailable right now ({e}). "
                          f"Your earlier answer and its data are unchanged.", 503)

    index = _evidence_index(ctx)
    why = []
    for it in raw.get("why") or []:
        if isinstance(it, dict) and str(it.get("text", "")).strip():
            ev = [e for e in it.get("evidence") or [] if e in index]
            why.append({"text": str(it["text"]).strip(), "evidence": ev})
    cited = sorted({e for w in why for e in w["evidence"]})
    # Grounding guard: an answer that cites nothing from the stored data is not covered by it.
    covered = bool(raw.get("covered")) and bool(cited)
    text = str(raw.get("answer", "")).strip()

    allowed = grounding.allowed_numbers(_allowed_values(ctx, iso(now)))
    unverified = grounding.unverified_numbers(" ".join([text] + [w["text"] for w in why]), allowed)

    ctx["thread"] = (ctx["thread"] + [{"question": question, "answer": text}])[-THREAD_KEEP:]
    used_now, _ = sessions.followup_allowance(session)
    return {
        "followup_id": uuid.uuid4().hex[:12],
        "question": question,
        "language": lang,
        "covered": covered,
        "not_covered_message": None if covered else NOT_COVERED[lang],
        "answer": {
            "text": text,
            "why": why,
            "missing_data": [str(m) for m in raw.get("missing_data") or [] if str(m).strip()],
            "disclaimer": str(raw.get("disclaimer") or DISCLAIMER[lang]).strip(),
        },
        "evidence_points": [{**index[e], "cached": True} for e in cited],  # all from the stored copy
        "unverified_numbers": unverified,
        "generated_by": model,
        "generated_at": iso(now),
        "based_on_request_id": ctx["request_id"],
        "data_fetched_at": ctx["data_fetched_at"],
        "data_age_minutes": age_min,
        "followups_used": used_now,
        "followups_limit": config.FOLLOWUP_LIMIT,
        "sources": ctx["sources"],
    }
