"""Fixture mode for LOCAL DEVELOPMENT ONLY: serve the app from saved real API responses.

Start it with USE_FIXTURES=1 (run.ps1 / run.sh pick this module instead of app.main):

    cd backend
    USE_FIXTURES=1 uvicorn devtools.fixture_server:app --reload --port 8000

Why this lives outside backend/app:
- The deployed app (render.yaml start command: `uvicorn app.main:app`) never imports this
  module, so fixture mode cannot be switched on in production by any environment variable.
- This module also refuses to start on Render (RENDER is set there) or unless USE_FIXTURES=1.

What it does:
- Replaces every Open-Meteo and SoilGrids call with the saved responses in tests/fixtures
  (Dharwad only; other places are reported as not found).
- Freezes the clock at the time the forecast fixture was captured, so the saved forecast is
  "current" and spray windows, heavy-rain and month-to-date rain line up with it.
- Labels every source "SAVED TEST RESPONSE", adds "fixture_mode": true to every answer and an
  X-YieldGuard-Data: saved-test-responses header to every response; the page shows a red banner. Gemini is still called live if GEMINI_API_KEY is set.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

if os.getenv("RENDER") or os.getenv("USE_FIXTURES") != "1":
    raise RuntimeError(
        "Fixture mode is for local development only: set USE_FIXTURES=1, and never run it on Render. "
        "The deployed app uses app.main:app with live data."
    )

from fastapi import Request  # noqa: E402

from app import advisor, baseline, http, main  # noqa: E402
from app.sources import forecast, geocode, rainfall, soil  # noqa: E402

log = logging.getLogger("yieldguard.fixtures")

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
LABEL = " [SAVED TEST RESPONSE]"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


MANIFEST = _load("manifest.json")
CAPTURED_AT = datetime.fromisoformat(MANIFEST["forecast_full_dharwad.json"]["captured_at"])
_GEOCODE = _load("geocode_dharwad.json")
_FORECAST = _load("forecast_full_dharwad.json")
_ARCHIVE = _load("archive_dharwad_2000_2025.json")
_SOIL = _load("soil_dharwad_nearby.json")


def _archive_slice(start: str, end: str) -> dict:
    daily = _ARCHIVE["daily"]
    keep = [i for i, t in enumerate(daily["time"]) if start <= t <= end]
    return {**_ARCHIVE, "daily": {"time": [daily["time"][i] for i in keep],
                                  "precipitation_sum": [daily["precipitation_sum"][i] for i in keep]}}


async def fake_get_json(url: str, params, **_kw):
    """Same contract as app.http.get_json, answered from saved responses."""
    p = dict(params) if not isinstance(params, dict) else params
    if url == geocode.config.GEOCODING_URL:
        name = str(p.get("name", "")).strip().lower()
        hits = [r for r in _GEOCODE.get("results", []) if r["name"].lower().startswith(name)]
        result = {**_GEOCODE, "results": hits}
    elif url == forecast.config.FORECAST_URL:
        result = _FORECAST
    elif url == rainfall.config.ARCHIVE_URL:
        result = _archive_slice(p["start_date"], p["end_date"])
    elif url == soil.config.SOILGRIDS_URL:
        result = _SOIL
    else:
        raise http.FetchError(f"no saved response for {url}")
    log.info("fixture %s %s", url.split("/")[2], {k: p[k] for k in ("name", "start_date", "end_date") if k in p})
    return result


def _frozen_now():
    return CAPTURED_AT


# Every module imported these names directly, so patch each module's reference.
for mod in (geocode, forecast, rainfall, soil):
    mod.get_json = fake_get_json
for mod in (advisor, http, main):
    mod.now_local = _frozen_now
for mod, attr in ((geocode, "NAME"), (forecast, "NAME"), (rainfall, "MTD_NAME"), (rainfall, "BASELINE_NAME"),
                  (baseline, "BASELINE_NAME"), (soil, "NAME")):
    setattr(mod, attr, getattr(mod, attr) + LABEL)

# Saved-response data goes to .cache/, never into the real data/ files.
_CACHE = FIXTURES.parents[1] / ".cache"


class _InlineBaselineStore(baseline.BaselineStore):
    """Builds a missing baseline straight away from the saved archive response (no background queue)."""

    async def get(self, place, today):
        if baseline.district_key(place) not in self.entries:
            await self.build(place)
        return await super().get(place, today)


baseline.get_json = fake_get_json
baseline.now_local = _frozen_now
baseline.store = _InlineBaselineStore(_CACHE / "fixture-baselines.json", autostart=False)
soil.soil_store = soil.FileCache(_CACHE / "fixture-soil.json")

app = main.app


@app.middleware("http")
async def _mark_fixture_mode(request: Request, call_next):
    """Every response (pages and API) carries a header saying the data is saved, not live."""
    response = await call_next(request)
    response.headers["X-YieldGuard-Data"] = "saved-test-responses"
    return response


_advise = advisor.advise


async def _advise_labelled(*args, **kwargs):
    # The clock is frozen at capture time, so a forecast the browser fetched live would fail the
    # freshness checks: use the saved forecast and rain instead.
    kwargs.pop("client_forecast", None)
    kwargs.pop("client_past_rain", None)
    res = await _advise(*args, **kwargs)
    res["fixture_mode"] = True
    res["warnings"].insert(0, f"FIXTURE MODE: saved test responses captured {CAPTURED_AT.isoformat()}, not live data.")
    return res


advisor.advise = _advise_labelled
main.advise = _advise_labelled

log.warning("USE_FIXTURES=1: serving SAVED TEST RESPONSES captured %s (Dharwad only). Not for deployment.",
            CAPTURED_AT.isoformat())
