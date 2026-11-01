import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import baseline, config, followup, llm, mandi_analysis, mandi_page, sessions, today
from .advisor import AdviceError, advise
from .http import close_client
from .sources import geocode
from .timeutil import iso, now_local

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs every request URL at INFO, and data.gov.in URLs carry the API key; app.http logs each call without it.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
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
# Same-origin in production. The Next.js dev server (another port) needs credentials for the session cookie,
# which rules out "*", so allowed origins are listed in config.CORS_ORIGINS.
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["*"])


def _remember_answer(request: Request, response: Response, result: dict) -> None:
    """Keep this answer's data in the in-memory session so follow-ups can reuse it without new API calls."""
    s = sessions.get_or_create(request.cookies.get(config.SESSION_COOKIE))
    sessions.save_answer(s, followup.context_from(result))
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(config.SESSION_COOKIE, s.id, max_age=config.SESSION_TTL_S, httponly=True,
                        samesite="lax", secure=secure, path="/")


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
    request: Request,
    response: Response,
    q: str = Query(..., description="The farmer's question, in English, Hindi or Kannada"),
    location: str | None = Query(None, description="Place name in Karnataka (default: Dharwad)"),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    lang: str | None = Query("auto", description="en | hi | kn | auto"),
):
    result = await advise(q, location=location, lat=lat, lon=lon, lang=lang)
    _remember_answer(request, response, result)
    return result


class BrowserForecastIn(BaseModel):
    """What the page's forecast fetch returned (web/lib/forecastClient.ts). Checked in sources/browser_forecast.py."""
    ok: bool
    data: dict | None = None          # the Open-Meteo response, when ok
    fetched_at: str | None = None     # when the browser fetched it (ISO 8601 with time zone)
    cached: bool = False              # served from the browser's 10-minute copy
    status: int | None = None         # HTTP status of a failed fetch (e.g. 429)
    error: str | None = Field(None, max_length=300)


class AdviceIn(BaseModel):
    question: str = Field(..., max_length=2000)
    location: str | None = Field(None, max_length=200)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    lang: str | None = "auto"
    forecast: BrowserForecastIn
    past_rain: BrowserForecastIn | None = None  # daily rain over the deficit window, fetched once a day


@app.post("/api/advice")
async def post_advice(body: AdviceIn, request: Request, response: Response):
    """The advice page's request: the question plus the forecast and past rain fetched in the visitor's browser,
    so the server makes no Open-Meteo call. If the forecast fetch failed, MET Norway is used instead."""
    result = await advise(body.question, location=body.location, lat=body.lat, lon=body.lon, lang=body.lang,
                          client_forecast=body.forecast.model_dump(),
                          client_past_rain=body.past_rain.model_dump() if body.past_rain else None)
    _remember_answer(request, response, result)
    return result


class FollowupIn(BaseModel):
    question: str = Field(..., max_length=2000)
    lang: str | None = "auto"


@app.post("/api/followup")
async def post_followup(body: FollowupIn, request: Request):
    """Answer a follow-up from the data stored with this session's last answer. Calls no weather or soil API."""
    s = sessions.get(request.cookies.get(config.SESSION_COOKIE))
    return await followup.answer(s, body.question, body.lang)


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


@app.get("/api/mandi/crops")
async def get_mandi_crops():
    """Commodities in the current Karnataka mandi snapshot (data.gov.in), for the Mandi page's crop picker."""
    return await mandi_page.crop_list()


@app.get("/api/mandi")
async def get_mandi(
    crop: str = Query(..., min_length=1, max_length=120, description="Agmarknet commodity name, from /api/mandi/crops"),
    location: str | None = Query(None, description="Place name in Karnataka (default: Dharwad)"),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
):
    """Today's reported price at the nearest market reporting this crop, and the other markets nearby. No LLM."""
    return await mandi_page.prices(location, lat, lon, crop.strip())


class MandiAnalysisIn(BaseModel):
    crop: str = Field(..., min_length=1, max_length=120)  # exact Agmarknet name, from /api/mandi/crops
    location: str | None = Field(None, max_length=200)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    lang: str = "en"
    forecast: BrowserForecastIn  # fetched in the browser, as on the advice page


@app.post("/api/mandi/analysis")
async def post_mandi_analysis(body: MandiAnalysisIn):
    """The Mandi page's analysis of one crop: prices, nearby markets and weather timing, cited and number-checked."""
    return await mandi_analysis.analyse(body.crop.strip(), body.location, body.lat, body.lon, body.lang,
                                        body.forecast.model_dump())


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
    request: Request,
    response: Response,
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
        result = await advise(question or q or "", location=location, lat=lat, lon=lon, lang=lang)
        _remember_answer(request, response, result)
        return result
    page = FRONTEND_DIR / "advice" / "index.html"
    if page.is_file():
        return FileResponse(page)
    return _no_frontend()


class ExportFiles(StaticFiles):
    """Static files for the Next.js export. Link prefetches ask for segment data as
    /advice/__next.advice.__PAGE__.txt while the export writes /advice/__next.advice/__PAGE__.txt,
    so a missing __next.* file is retried with its last dot turned into a folder separator."""

    @staticmethod
    def _nested(path: str) -> str | None:
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if not name.startswith("__next.") or not name.endswith(".txt"):
            return None
        folder, _, leaf = name[: -len(".txt")].rpartition(".")
        if not folder or not leaf:
            return None
        return path[: len(path) - len(name)] + f"{folder}/{leaf}.txt"

    async def get_response(self, path: str, scope):
        from starlette.exceptions import HTTPException as StarletteHTTPException

        nested = self._nested(path)
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            # Without a 404.html, a missing file raises; with html=True and 404.html it is served instead.
            if e.status_code != 404 or nested is None:
                raise
            return await super().get_response(nested, scope)
        if response.status_code == 404 and nested is not None:
            return await super().get_response(nested, scope)
        return response


def _no_frontend():
    return HTMLResponse("<h1>YieldGuard API</h1><p>The web frontend is not built. Run <code>npm run build</code> "
                        "in <code>web/</code>, or use <a href='/docs'>/docs</a>.</p>", status_code=503)


if (FRONTEND_DIR / "index.html").is_file():
    # Mounted last so the /api routes above take precedence. html=True serves /advice/ -> advice/index.html
    # and 404.html for unknown paths.
    app.mount("/", ExportFiles(directory=FRONTEND_DIR, html=True), name="web")
else:
    log.warning("frontend build not found at %s - serving the API only", FRONTEND_DIR)

    @app.get("/", include_in_schema=False)
    async def index():
        return _no_frontend()
