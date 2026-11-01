"""Deterministic answer built from rule outcomes when the language model fails.

These are sentence templates only; every number placed in them comes from the
live data retrieved for this request.
"""
from .timeutil import parse_local

T = {
    "en": {
        "prefix": "Automatic summary (language model unavailable):",
        "spray_found": "Safe time to spray: {start} to {end}.",
        "spray_none": "No safe spray time in the forecast. Wait for calm, dry weather.",
        "heavy_warning": "Heavy rain is likely in the next 24 hours (up to {prob}% chance, {mm} mm total). "
                         "Postpone field work and check field drainage.",
        "heavy_ok": "No heavy rain expected in the next 24 hours.",
        "drought_risk": "Rainfall this month is {pct}% of normal. Drought risk: plan irrigation and save soil moisture with mulch.",
        "waterlogging_risk": "Rainfall this month is {pct}% of normal. Waterlogging risk: clear drains and hold irrigation.",
        "normal": "Rainfall this month is {pct}% of normal, within the usual range.",
        "high_sand": "Sandy soil: irrigate lightly but more often.",
        "high_clay": "Clay soil drains slowly: take care during heavy rain.",
        "ph": "Soil pH is {ph}, outside the usual range. Consider a soil test.",
        "missing": "{name}: data not available right now.",
        "irrigate": "Estimated water balance: the soil water deficit passes {mm} mm on {date}. Plan to irrigate then (estimate).",
        "irrigate_ok": "Estimated water balance: no irrigation needed in the next {days} days.",
        "heat": "Heat stress expected on {dates} (above {t} °C). Irrigate early morning or evening, avoid afternoon spraying.",
        "fert_delay": "Delay fertiliser: rain is likely in the next {h} hours (up to {prob}% chance), which washes nutrients away.",
        "mandi_found": "{crop} at {market} ({km} km away): Rs {modal} per quintal (min {lo}, max {hi}), arrival date {date}.",
        "mandi_latest": "{crop} at {market} ({km} km away), latest available: {date}: Rs {modal} per quintal (min {lo}, max {hi}).",
        "mandi_no_nearby": "No market within {km} km reports a price for {crop}.",
        "mandi_none": "No mandi price is available for {crop} right now.",
        "disclaimer": "Please confirm with your local Krishi Vigyan Kendra (KVK) or agriculture officer before acting.",
    },
    "hi": {
        "prefix": "स्वचालित सारांश (भाषा मॉडल उपलब्ध नहीं):",
        "spray_found": "छिड़काव के लिए सुरक्षित समय: {start} से {end} तक।",
        "spray_none": "पूर्वानुमान में छिड़काव के लिए कोई सुरक्षित समय नहीं है। शांत और सूखे मौसम का इंतज़ार करें।",
        "heavy_warning": "अगले 24 घंटों में भारी बारिश की संभावना है (अधिकतम {prob}% संभावना, कुल {mm} मिमी)। "
                         "खेत का काम टालें और पानी की निकासी जाँचें।",
        "heavy_ok": "अगले 24 घंटों में भारी बारिश की संभावना नहीं है।",
        "drought_risk": "इस महीने अब तक बारिश सामान्य का {pct}% है। सूखे का खतरा: सिंचाई की योजना बनाएं और मल्चिंग से नमी बचाएं।",
        "waterlogging_risk": "इस महीने अब तक बारिश सामान्य का {pct}% है। जलभराव का खतरा: नालियाँ साफ़ करें और सिंचाई रोकें।",
        "normal": "इस महीने अब तक बारिश सामान्य का {pct}% है, जो सामान्य सीमा में है।",
        "high_sand": "रेतीली मिट्टी: कम पानी से, लेकिन बार-बार सिंचाई करें।",
        "high_clay": "चिकनी मिट्टी में पानी धीरे निकलता है: भारी बारिश में सावधानी रखें।",
        "ph": "मिट्टी का pH {ph} है, जो सामान्य सीमा से बाहर है। मिट्टी की जाँच करवाएं।",
        "missing": "{name}: अभी डेटा उपलब्ध नहीं है।",
        "irrigate": "अनुमानित जल संतुलन: {date} को मिट्टी में पानी की कमी {mm} मिमी से ज़्यादा हो जाएगी। उसी दिन सिंचाई की योजना बनाएं (अनुमान)।",
        "irrigate_ok": "अनुमानित जल संतुलन: अगले {days} दिनों में सिंचाई की ज़रूरत नहीं।",
        "heat": "{dates} को गर्मी का तनाव संभव है ({t} °C से ज़्यादा)। सुबह जल्दी या शाम को सिंचाई करें, दोपहर में छिड़काव न करें।",
        "fert_delay": "खाद डालना टालें: अगले {h} घंटों में बारिश की संभावना है (अधिकतम {prob}%), जिससे पोषक तत्व बह जाते हैं।",
        "mandi_found": "{market} ({km} किमी दूर) में {crop} का भाव: Rs {modal} प्रति क्विंटल (न्यूनतम {lo}, अधिकतम {hi}), आवक तिथि {date}।",
        "mandi_latest": "{market} ({km} किमी दूर) में {crop} का नवीनतम उपलब्ध भाव ({date}): Rs {modal} प्रति क्विंटल (न्यूनतम {lo}, अधिकतम {hi})।",
        "mandi_no_nearby": "{km} किमी के भीतर कोई मंडी {crop} का भाव नहीं बता रही है।",
        "mandi_none": "{crop} का मंडी भाव अभी उपलब्ध नहीं है।",
        "disclaimer": "कोई भी कदम उठाने से पहले अपने स्थानीय कृषि विज्ञान केंद्र (KVK) या कृषि अधिकारी से पुष्टि करें।",
    },
    "kn": {
        "prefix": "ಸ್ವಯಂಚಾಲಿತ ಸಾರಾಂಶ (ಭಾಷಾ ಮಾದರಿ ಲಭ್ಯವಿಲ್ಲ):",
        "spray_found": "ಸಿಂಪಡಣೆಗೆ ಸುರಕ್ಷಿತ ಸಮಯ: {start} ರಿಂದ {end} ವರೆಗೆ.",
        "spray_none": "ಮುನ್ಸೂಚನೆಯಲ್ಲಿ ಸಿಂಪಡಣೆಗೆ ಸುರಕ್ಷಿತ ಸಮಯ ಇಲ್ಲ. ಗಾಳಿ ಕಡಿಮೆ ಇರುವ ಒಣ ಹವಾಮಾನಕ್ಕಾಗಿ ಕಾಯಿರಿ.",
        "heavy_warning": "ಮುಂದಿನ 24 ಗಂಟೆಗಳಲ್ಲಿ ಭಾರೀ ಮಳೆಯ ಸಾಧ್ಯತೆ ಇದೆ (ಗರಿಷ್ಠ {prob}% ಸಾಧ್ಯತೆ, ಒಟ್ಟು {mm} ಮಿ.ಮೀ). "
                         "ಹೊಲದ ಕೆಲಸ ಮುಂದೂಡಿ ಮತ್ತು ನೀರು ಹೊರಹೋಗುವ ಕಾಲುವೆಗಳನ್ನು ಪರಿಶೀಲಿಸಿ.",
        "heavy_ok": "ಮುಂದಿನ 24 ಗಂಟೆಗಳಲ್ಲಿ ಭಾರೀ ಮಳೆಯ ನಿರೀಕ್ಷೆ ಇಲ್ಲ.",
        "drought_risk": "ಈ ತಿಂಗಳು ಇಲ್ಲಿಯವರೆಗೆ ಮಳೆ ಸಾಮಾನ್ಯದ {pct}% ಮಾತ್ರ. ಬರದ ಅಪಾಯ: ನೀರಾವರಿ ಯೋಜಿಸಿ ಮತ್ತು ಹೊದಿಕೆಯಿಂದ (ಮಲ್ಚಿಂಗ್) ತೇವಾಂಶ ಉಳಿಸಿ.",
        "waterlogging_risk": "ಈ ತಿಂಗಳು ಇಲ್ಲಿಯವರೆಗೆ ಮಳೆ ಸಾಮಾನ್ಯದ {pct}% ಇದೆ. ನೀರು ನಿಲ್ಲುವ ಅಪಾಯ: ಕಾಲುವೆಗಳನ್ನು ಸ್ವಚ್ಛಗೊಳಿಸಿ ಮತ್ತು ನೀರಾವರಿ ನಿಲ್ಲಿಸಿ.",
        "normal": "ಈ ತಿಂಗಳು ಇಲ್ಲಿಯವರೆಗೆ ಮಳೆ ಸಾಮಾನ್ಯದ {pct}% ಇದೆ, ಇದು ಸಾಮಾನ್ಯ ಮಟ್ಟದಲ್ಲಿದೆ.",
        "high_sand": "ಮರಳು ಮಣ್ಣು: ಕಡಿಮೆ ನೀರನ್ನು ಹೆಚ್ಚು ಬಾರಿ ಕೊಡಿ.",
        "high_clay": "ಜೇಡಿ ಮಣ್ಣಿನಲ್ಲಿ ನೀರು ನಿಧಾನವಾಗಿ ಇಳಿಯುತ್ತದೆ: ಭಾರೀ ಮಳೆಯ ಸಮಯದಲ್ಲಿ ಎಚ್ಚರಿಕೆ ವಹಿಸಿ.",
        "ph": "ಮಣ್ಣಿನ pH {ph} ಇದೆ, ಇದು ಸಾಮಾನ್ಯ ಮಟ್ಟದಿಂದ ಹೊರಗಿದೆ. ಮಣ್ಣು ಪರೀಕ್ಷೆ ಮಾಡಿಸಿ.",
        "missing": "{name}: ಈಗ ಮಾಹಿತಿ ಲಭ್ಯವಿಲ್ಲ.",
        "irrigate": "ಅಂದಾಜು ನೀರಿನ ಲೆಕ್ಕ: {date} ರಂದು ಮಣ್ಣಿನ ನೀರಿನ ಕೊರತೆ {mm} ಮಿ.ಮೀ ದಾಟುತ್ತದೆ. ಆ ದಿನ ನೀರು ಹಾಯಿಸಲು ಯೋಜಿಸಿ (ಅಂದಾಜು).",
        "irrigate_ok": "ಅಂದಾಜು ನೀರಿನ ಲೆಕ್ಕ: ಮುಂದಿನ {days} ದಿನಗಳಲ್ಲಿ ನೀರಾವರಿ ಬೇಕಿಲ್ಲ.",
        "heat": "{dates} ರಂದು ಬಿಸಿಲಿನ ಒತ್ತಡ ಸಾಧ್ಯ ({t} °C ಮೀರಿ). ಬೆಳಿಗ್ಗೆ ಬೇಗ ಅಥವಾ ಸಂಜೆ ನೀರು ಹಾಯಿಸಿ, ಮಧ್ಯಾಹ್ನ ಸಿಂಪಡಿಸಬೇಡಿ.",
        "fert_delay": "ಗೊಬ್ಬರ ಹಾಕುವುದನ್ನು ಮುಂದೂಡಿ: ಮುಂದಿನ {h} ಗಂಟೆಗಳಲ್ಲಿ ಮಳೆಯ ಸಾಧ್ಯತೆ ಇದೆ (ಗರಿಷ್ಠ {prob}%), ಇದರಿಂದ ಪೋಷಕಾಂಶ ಕೊಚ್ಚಿಹೋಗುತ್ತದೆ.",
        "mandi_found": "{market} ({km} ಕಿ.ಮೀ ದೂರ) ಮಾರುಕಟ್ಟೆಯಲ್ಲಿ {crop} ಬೆಲೆ: ಕ್ವಿಂಟಾಲ್‌ಗೆ Rs {modal} (ಕನಿಷ್ಠ {lo}, ಗರಿಷ್ಠ {hi}), ಆವಕ ದಿನಾಂಕ {date}.",
        "mandi_latest": "{market} ({km} ಕಿ.ಮೀ ದೂರ) ಮಾರುಕಟ್ಟೆಯಲ್ಲಿ {crop} ಇತ್ತೀಚಿನ ಲಭ್ಯ ಬೆಲೆ ({date}): ಕ್ವಿಂಟಾಲ್‌ಗೆ Rs {modal} (ಕನಿಷ್ಠ {lo}, ಗರಿಷ್ಠ {hi}).",
        "mandi_no_nearby": "{km} ಕಿ.ಮೀ ಒಳಗಿನ ಯಾವುದೇ ಮಾರುಕಟ್ಟೆ {crop} ಬೆಲೆ ವರದಿ ಮಾಡಿಲ್ಲ.",
        "mandi_none": "{crop} ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಈಗ ಲಭ್ಯವಿಲ್ಲ.",
        "disclaimer": "ಯಾವುದೇ ಕ್ರಮ ಕೈಗೊಳ್ಳುವ ಮೊದಲು ನಿಮ್ಮ ಸ್ಥಳೀಯ ಕೃಷಿ ವಿಜ್ಞಾನ ಕೇಂದ್ರ (KVK) ಅಥವಾ ಕೃಷಿ ಅಧಿಕಾರಿಯೊಂದಿಗೆ ಖಚಿತಪಡಿಸಿಕೊಳ್ಳಿ.",
    },
}


def fmt_time(t: str) -> str:
    return parse_local(t).strftime("%d/%m %H:%M")


def fmt_day(d: str) -> str:
    return parse_local(d).strftime("%d/%m")


def _price(v: float | None) -> str:
    return "-" if v is None else f"{v:g}"


def compose(lang: str, results: dict, rules: list[dict], failed_sources: list[dict]) -> dict:
    """`results` holds raw rule outputs: spray, heavy_rain, deficit, soil (any may be None)."""
    t = T.get(lang, T["en"])
    recs: list[dict] = []
    headline: list[str] = []

    hr = results.get("heavy_rain")
    if hr and hr["status"] == "warning":
        s = t["heavy_warning"].format(prob=hr["max_precip_prob_pct"], mm=hr["total_precip_mm"])
        recs.append({"text": s, "evidence": ["max_rain_prob_24h", "rain_total_24h"]})
        headline.append(s)
    elif hr and hr["status"] == "ok":
        recs.append({"text": t["heavy_ok"], "evidence": ["max_rain_prob_24h", "rain_total_24h"]})

    sp = results.get("spray")
    if sp is not None:
        if sp["windows"]:
            w = sp["windows"][0]
            s = t["spray_found"].format(start=fmt_time(w["start"]), end=fmt_time(w["end"]))
            recs.append({"text": s, "evidence": ["spray_window_1"]})
        else:
            s = t["spray_none"]
            recs.append({"text": s, "evidence": ["max_wind_24h"]})
        headline.append(s)

    df = results.get("deficit")
    if df and df["status"] in ("drought_risk", "waterlogging_risk", "normal"):
        recs.append({"text": t[df["status"]].format(pct=df["percent_of_normal"]),
                     "evidence": ["rain_mtd", "rain_normal", "rain_pct_normal"]})

    so = results.get("soil")
    if so:
        for flag in so["flags"]:
            if flag in ("acidic", "alkaline"):
                recs.append({"text": t["ph"].format(ph=so["ph"]), "evidence": ["soil_ph"]})
            else:
                recs.append({"text": t[flag], "evidence": ["soil_sand" if flag == "high_sand" else "soil_clay"]})

    ht = results.get("heat")
    if ht and ht["status"] == "warning":
        s = t["heat"].format(dates=", ".join(fmt_day(d["date"]) for d in ht["hot_days"]), t=ht["thresholds"]["tmax_c"])
        recs.append({"text": s, "evidence": [f"heat_day_{i}" for i in range(1, len(ht["hot_days"]) + 1)]})

    fe = results.get("fertiliser")
    if fe and fe["status"] == "delay":
        recs.append({"text": t["fert_delay"].format(h=fe["thresholds"]["lookahead_h"], prob=fe["max_precip_prob_pct"]),
                     "evidence": ["fert_max_prob", "fert_rain_total"]})

    md = results.get("mandi")
    if md:
        ids = ["mandi_modal_price", "mandi_min_price", "mandi_max_price", "mandi_market", "mandi_distance_km",
               "mandi_arrival_date"]
        if md["status"] in ("found", "latest"):
            r, m = md["records"][0], md["market"]
            s = t[f"mandi_{md['status']}"].format(crop=md["crop_word"], market=m["name"], km=f"{m['distance_km']:g}",
                                                  modal=_price(r["modal_price"]), lo=_price(r["min_price"]),
                                                  hi=_price(r["max_price"]), date=r["arrival_date"])
            recs.insert(0, {"text": s, "evidence": ids})
            headline.insert(0, s)
        elif md["status"] == "no_nearby_market":
            s = t["mandi_no_nearby"].format(km=f"{md['max_distance_km']:g}", crop=md["crop_word"])
            recs.insert(0, {"text": s, "evidence": ["mandi_nearest_beyond_km"]})
            headline.insert(0, s)
        else:
            s = t["mandi_none"].format(crop=md["crop_word"])
            recs.insert(0, {"text": s, "evidence": []})
            headline.insert(0, s)

    ir = results.get("irrigation")
    if ir and ir["status"] == "irrigate":
        recs.append({"text": t["irrigate"].format(mm=ir["thresholds"]["deficit_mm"], date=fmt_day(ir["irrigate_on"])),
                     "evidence": ["wb_deficit_final", "wb_crop_use_total", "wb_rain_total"]})
    elif ir and ir["status"] == "ok":
        recs.append({"text": t["irrigate_ok"].format(days=len(ir["days"])),
                     "evidence": ["wb_deficit_final", "wb_crop_use_total", "wb_rain_total"]})

    missing = [t["missing"].format(name=s["name"]) for s in failed_sources]
    body = headline or [r["text"] for r in recs[:2]] or missing[:1]
    answer = " ".join([t["prefix"]] + body)

    return {
        "answer": answer,
        "recommendations": recs,
        "why": [{"text": r["summary"], "evidence": r["evidence"]} for r in rules],
        "missing_data": missing,
        "disclaimer": t["disclaimer"],
    }
