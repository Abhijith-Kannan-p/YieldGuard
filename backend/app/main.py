import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import baseline, config, llm, today
from .advisor import AdviceError, advise
from .http import close_client
from .sources import geocode
from .timeutil import iso, now_local

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("yieldguard")

# Next.js static export (web/ -> `npm run build` -> web/out), served from this same app.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "web" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not llm.available():
        log.warning("GEMINI_API_KEY not set - answers will use the rule-based fallback")
    baseline.store.load()
    # Build the default district's rainfall baseline in the background if none is stored yet.
    prebuild = asyncio.create_task(baseline.store.prebuild_default())
    yield
    prebuild.cancel()
    await close_client()


app = FastAPI(title="YieldGuard - Multilingual Agritech Risk Advisor", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


@app.exception_handler(AdviceError)
async def advice_error_handler(request: Request, exc: AdviceError):
    return JSONResponse(status_code=exc.http_status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": {
        "code": "internal_error", "message": "Something went wrong on our side. Please try again."}})


@app.get("/api/advice")
async def get_advice(
    q: str = Query(..., description="The farmer's question, in English, Hindi or Kannada"),
    location: str | None = Query(None, description="Place name in Karnataka (default: Dharwad)"),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    lang: str | None = Query("auto", description="en | hi | kn | auto"),
):
    return await advise(q, location=location, lat=lat, lon=lon, lang=lang)


@app.post("/api/transcribe")
async def transcribe(request: Request, lang: str | None = Query("auto")):
    """Speech to text for the question box. Body: 16-bit PCM WAV recorded in the browser."""
    audio = await request.body()
    if len(audio) > config.TRANSCRIBE_MAX_BYTES:
        raise AdviceError("audio_too_long",
                          f"Recording is too long. Please keep it under {config.TRANSCRIBE_MAX_SECONDS} seconds.", 413)
    if len(audio) < 1000 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise AdviceError("bad_audio", "No usable recording was received. Please try again.", 422)
    try:
        raw, model = await llm.transcribe(audio, lang)
    except llm.LLMError as e:
        raise AdviceError("transcription_failed", f"Could not turn speech into text ({e}). Please type your question.",
                          503)
    text = str(raw.get("text", "")).strip()
    language = raw.get("language") if raw.get("language") in config.SUPPORTED_LANGUAGES else None
    return {"text": text, "language": language, "model": model, "transcribed_at": iso(now_local())}


@app.get("/api/today")
async def get_today(
    location: str | None = Query(None, description="Place name in Karnataka (default: Dharwad)"),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
):
    """Short live summary for the landing card and saved fields. Cached per location for one hour."""
    return await today.summary(location, lat, lon)


@app.get("/api/locations")
async def search_locations(q: str = Query(..., min_length=2, max_length=80)):
    res = await geocode.search(q)
    if not res.ok:
        raise AdviceError("geocoding_failed", f"Location search is unavailable right now ({res.error}).", 503)
    return {"results": res.data, "source": res.name,
            "fetched_at": iso(res.fetched_at) if res.fetched_at else None, "cached": res.cached}


@app.get("/api/rules")
async def rules():
    """The thresholds currently in use, straight from config.py."""
    return {
        "spray_window": {
            "max_wind_kmh": config.SPRAY_MAX_WIND_KMH,
            "max_precip_prob_pct": config.SPRAY_MAX_PRECIP_PROB_PCT,
            "max_precip_mm": config.SPRAY_MAX_PRECIP_MM,
            "min_consecutive_hours": config.SPRAY_MIN_HOURS,
            "max_windows": config.SPRAY_MAX_WINDOWS,
            "allowed_hours": config.SPRAY_ALLOWED_HOURS,
        },
        "heavy_rain": {
            "lookahead_h": config.HEAVY_RAIN_LOOKAHEAD_H,
            "prob_pct": config.HEAVY_RAIN_PROB_PCT,
            "total_mm": config.HEAVY_RAIN_TOTAL_MM,
        },
        "rain_deficit": {
            "baseline_start_year": config.BASELINE_START_YEAR,
            "drought_below_pct": config.DEFICIT_DROUGHT_PCT,
            "waterlog_above_pct": config.DEFICIT_WATERLOG_PCT,
            "min_baseline_mm": config.DEFICIT_MIN_BASELINE_MM,
        },
        "soil": {
            "sand_high_pct": config.SOIL_SAND_HIGH_PCT,
            "clay_high_pct": config.SOIL_CLAY_HIGH_PCT,
            "ph_low": config.SOIL_PH_LOW,
            "ph_high": config.SOIL_PH_HIGH,
        },
    }


@app.get("/api/health")
async def health():
    """Liveness and configuration only. Calls no external service."""
    return {"status": "ok", "time": iso(now_local()), "llm_configured": llm.available(),
            "llm_model": config.LLM_MODEL, "llm_fallback_model": config.LLM_FALLBACK_MODEL,
            "rainfall_baselines": baseline.store.status()}


@app.get("/advice", include_in_schema=False)
async def advice_alias(
    question: str | None = Query(None),
    q: str | None = Query(None),
    location: str | None = Query(None),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    lang: str | None = Query("auto"),
):
    """GET /advice?location=...&question=...&lang=en|hi|kn returns JSON (same as /api/advice).
    Without a question it serves the advice page, so /advice works in a browser too."""
    if question is not None or q is not None:
        return await advise(question or q or "", location=location, lat=lat, lon=lon, lang=lang)
    page = FRONTEND_DIR / "advice" / "index.html"
    if page.is_file():
        return FileResponse(page)
    return _no_frontend()


def _no_frontend():
    return HTMLResponse("<h1>YieldGuard API</h1><p>The web frontend is not built. Run <code>npm run build</code> "
                        "in <code>web/</code>, or use <a href='/docs'>/docs</a>.</p>", status_code=503)


if (FRONTEND_DIR / "index.html").is_file():
    # Mounted last so the /api routes above take precedence. html=True serves /advice/ -> advice/index.html
    # and 404.html for unknown paths.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="web")
else:
    log.warning("frontend build not found at %s - serving the API only", FRONTEND_DIR)

    @app.get("/", include_in_schema=False)
    async def index():
        return _no_frontend()
