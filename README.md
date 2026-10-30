# YieldGuard – Multilingual Agritech Risk Advisor

YieldGuard gives Karnataka farmers plain-language, crop-level protective advice from **live** weather, rainfall-history and soil data, in **English, Hindi or Kannada**.

Type a village or town, ask a question in your language, and get:

- **Spray windows**: the next safe hours to spray, based on wind and rain.
- **Heavy-rain warnings** for the next 24 hours.
- **Rainfall vs normal**: this month's rain compared with the 2000–2025 average for the same dates (drought or waterlogging risk).
- **Soil-aware tips** from SoilGrids topsoil sand, clay and pH at your coordinates.
- A **"why" section** that shows every data point used, with its **source and fetch time**, and the rule that was applied.

> Built for the Climate, Resource Infrastructure & Global Supply Resilience buildathon (problem: Multilingual Agritech & Resource Advisory Assistant).

**Live app:** `<add your Render URL here>`

---

## How it works

```mermaid
flowchart LR
    U[Farmer<br/>browser] -->|"/" landing, /advice page<br/>static Next.js export| API[FastAPI backend]
    U -->|GET /api/advice<br/>location + question| API
    API --> G[Open-Meteo<br/>Geocoding]
    API -->|parallel| F[Open-Meteo<br/>Forecast 72 h]
    API -->|parallel| M[Open-Meteo<br/>recent daily rain]
    API -->|parallel| A[Open-Meteo Archive<br/>2000-2025 daily rain]
    API -->|parallel| S[ISRIC SoilGrids<br/>0-5 cm]
    F & M & A & S --> C[(TTL cache<br/>stores fetch time)]
    C --> R[Rules engine<br/>config.py thresholds]
    R --> E[Evidence registry<br/>value + source + time]
    E --> L[Google Gemini<br/>grounded JSON answer]
    L --> V[Number check<br/>every number traced to data]
    E -.LLM down.-> FB[Rule-based answer<br/>EN / HI / KN templates]
    V --> U
    FB --> U
```

1. **Resolve location** with Open-Meteo Geocoding, restricted to Karnataka (or use browser GPS coordinates).
2. **Fetch in parallel**: the 72-hour forecast, month-to-date rainfall, the rainfall baseline (one small archive request per year, 2000 to last year, for the compared month only), and SoilGrids topsoil. Each call has an 8 s timeout and one retry. Responses are cached with their original fetch time.
3. **Apply rules** from [`backend/app/config.py`](backend/app/config.py) (spray window, heavy rain, rainfall deficit, soil).
4. **Build the evidence registry**: every number gets an id, label, value, unit, the time it refers to, its source and its fetch time.
5. **Language model** (Google Gemini, `gemini-3.5-flash-lite`, retrying once on `gemini-3.8-flash` if it is rate-limited, overloaded or slow) gets only that evidence plus the rule outcomes and must return structured JSON whose recommendations cite evidence ids. Unknown ids are removed.
6. **Grounding check**: every number in the answer is matched against the retrieved data. Any number that can't be matched is shown to the user as "check these numbers".
7. **Failure handling**: if a source fails, the answer says which one and which parts are missing. If a live refresh fails but an earlier good response for the same place is cached (forecast up to 12 h old, month-to-date rain up to 24 h), that response is used and clearly labelled "live refresh failed, showing data fetched at …". If the language model fails, a deterministic rule-based answer is returned in the user's language.

### Open-Meteo rate limits

Open-Meteo's free tier allows 600 calls per minute, 5,000 per hour and 10,000 per day **per IP address**, and weights each call by its length (about days ÷ 14). Hosting platforms such as Render share outbound IPs between apps, so other apps' traffic counts too. YieldGuard keeps its usage low:

- **One forecast request per place**: the 72-hour forecast and this month's past daily rain come from one call (`past_days`). Cached for 60 minutes per location (coordinates rounded to 2 decimals).
- **Rainfall baseline built once per district and month**: one small archive request per year (about 57 weighted calls instead of about 680 for a single 26-year request), cached for 30 days and saved to `backend/.cache/baseline.json` so a restart does not refetch it. On Render's free plan the disk is reset on each deploy or restart, so it is rebuilt once after that.
- **One Open-Meteo call at a time**, and identical requests that arrive together share one call.
- **HTTP 429 is never retried straight away.** No Open-Meteo call is sent for `Retry-After` seconds, or at least 60 s, and the last good data is shown instead, labelled with its fetch time.
- **Every external call is logged** with provider, path, location, status and duration, for example `fetch open-meteo /v1/forecast latitude=15.46 longitude=75.01 past_days=30 -> 200 in 858 ms`; skipped calls are logged as `skip ... rate-limit backoff`.
- The answer panel lists **how old each piece of data is** (live, cached, or saved copy), and the language model is told to say so when a saved copy is used.

### Project layout

```
backend/
  app/
    config.py        all thresholds, URLs, timeouts, cache TTLs
    http.py          fetch with timeout + 1 retry, caching, SourceResult
    cache.py         TTL cache that keeps fetch time
    sources/         geocode, forecast, rainfall (MTD + baseline), soil
    rules/           spray, heavy_rain, deficit, soil
    evidence.py      data points + rule outcomes with source and time
    prompts.py       system prompt + JSON output schema
    llm.py           Gemini call (JSON schema output, fallback model on rate limit)
    fallback.py      rule-based answer in EN / HI / KN
    grounding.py     numbers-in-answer verification
    language.py      script-based language detection
    advisor.py       orchestration for one request
    main.py          FastAPI app and routes, serves the built frontend (web/out)
  tests/             71 tests; fixtures are real API responses (tests only, never imported by app/)
web/                 Next.js (App Router, TypeScript, Tailwind), built as a static export
  app/page.tsx         landing page (shader background, TextRoll title, "Get advice")
  app/advice/page.tsx  advice page
  components/          ShaderBackground, TextRoll, AdviceApp, ForecastChart, AttributionFooter
  lib/                 API client, types, EN/HI/KN labels, formatting, voice
render.yaml          deployment blueprint (no secrets)
```

---

## Data sources and attribution

| Data | Source | Notes |
|---|---|---|
| Place → coordinates | [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api) | Filtered to Karnataka, larger towns first |
| 72-hour hourly forecast | [Open-Meteo Forecast API](https://open-meteo.com/en/docs) | `temperature_2m, relative_humidity_2m, precipitation_probability, precipitation, wind_speed_10m`, `timezone=Asia/Kolkata`, `forecast_days=3` |
| Month-to-date rainfall | Open-Meteo Forecast API (`start_date`/`end_date`, `daily=precipitation_sum`) | Recent days without the archive's ~5-day lag |
| Long-run rainfall baseline | [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) | 2000 to last full year, same calendar dates; one request per year for the compared month; cached 7 days |
| Topsoil properties | [ISRIC SoilGrids v2.0](https://rest.isric.org/soilgrids/v2.0/docs) | `clay, sand, phh2o, soc`, `depth=0-5cm`, `value=mean`; cached 30 days |
| Answer writing | [Google Gemini API](https://ai.google.dev/) | Uses only the data above. Free tier: prompts may be used by Google to improve its products, so only public weather/soil data and the question are sent. |
| Voice questions (optional) | Google Gemini API (audio input) | Only when the farmer taps **Speak**. The recording is sent to Gemini for transcription and is not stored by YieldGuard. Same free-tier caveat as above. |

**Third-party code:** [Paper Shaders](https://github.com/paper-design/shaders) (Apache-2.0) for the landing background, [Motion](https://motion.dev) (MIT) for the title animation.

**Attribution:** Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Soil data: SoilGrids v2.0, [ISRIC – World Soil Information](https://www.isric.org/), CC BY 4.0.

**SoilGrids unit conversion:** values are stored as integers scaled by `d_factor` (read from each response): clay and sand g/kg ÷ 10 → %, pH × 10 ÷ 10 → pH, SOC dg/kg ÷ 10 → g/kg.

**Urban pixels:** SoilGrids masks built-up areas (for example, Dharwad city centre returns `null`). We then query points about 2 km away, one at a time to respect ISRIC's fair-use limit, and show the distance used ("2.2 km from the location").

**Rainfall caveat:** month-to-date rain comes from the forecast model's recent analysis and the baseline from ERA5 reanalysis. Both are gridded model estimates, not rain-gauge readings.

---

## Advisory rules

All thresholds are in [`backend/app/config.py`](backend/app/config.py) and also served live at `GET /api/rules`.

| Rule | Condition | Advice |
|---|---|---|
| Spray window | `wind_speed_10m < 10 km/h` AND `precipitation_probability < 20%` AND `precipitation = 0`, for **≥ 3 consecutive hours**, daylight 06:00–19:00 only (`SPRAY_ALLOWED_HOURS`, set `None` to allow any hour). Missing values count as unsafe. | Earliest 1–3 windows |
| Heavy rain | Next 24 h: any hour `precipitation_probability > 70%` OR total rain `> 40 mm` | Postpone field work, check drainage |
| Rainfall deficit | Month-to-date rain (1st to yesterday) as % of the 2000–2025 mean for the same dates. On the 1st, the previous full month is used. | `< 60%` drought risk, `> 150%` waterlogging risk. If normal rain is below 5 mm (dry season), no % is given. |
| Soil | sand `> 60%`; clay `> 40%`; pH `< 5.5` or `> 8.5` | Lighter, more frequent irrigation; caution in heavy rain; get a soil test |

---

## Frontend

- **Framework:** Next.js 16 (App Router, TypeScript, Tailwind CSS v4) with `output: "export"`. `npm run build` writes plain HTML/JS/CSS to `web/out`, which FastAPI serves, so the site and the API share one URL and need no CORS setup.
- **Theme "Sage Garden"** (tokens in [`web/app/globals.css`](web/app/globals.css)): primary `#7d9a86`, background `#111111`, card `#1a1a1a`, border `#2a2a2a`, muted text `#a3a8a4` (7.8:1 on the background), amber `#d97706` for drought, waterlogging, heavy-rain and soil warnings, red `#ef4444` only for errors and failed sources. Radius `0.5rem`. All text colours pass WCAG AA.
- **Landing (`/`):** a static mesh-gradient WebGL background ([`ShaderBackground.tsx`](web/components/ShaderBackground.tsx), built on [Paper Shaders](https://github.com/paper-design/shaders), Apache-2.0), the title animated once per page load with [`TextRoll.tsx`](web/components/TextRoll.tsx) (using [`motion`](https://motion.dev)), the tagline "From sky to soil, every season", and a "Get advice" button.
- **Voice input:** tap **Speak**, say the question, tap **Stop** (auto-stops after 30 s). The browser records with `MediaRecorder`, shows the input level, rejects silent recordings locally ("check that the right microphone is selected"), converts the audio to 16 kHz mono WAV, and posts it to `/api/transcribe`, where Gemini transcribes it in English, Hindi (Devanagari) or Kannada (Kannada script). The text goes into the question box so the farmer can check it before asking. This replaced the browser's `SpeechRecognition`, which sends audio to Google from Chrome only, fails in Brave and Opera, and has patchy Kannada support.
- **Advice (`/advice/`):** location (default Dharwad, with Karnataka place suggestions and GPS), question, language (Auto / English / हिन्दी / ಕನ್ನಡ), a **Speak** button for voice questions, and a **Listen** button that reads the answer aloud when the browser has a voice for that language. It shows loading, empty and error states, a red notice for each failed source saying which part of the answer is missing, amber warnings, the answer with a "Why this advice" section, the rules applied, a 72-hour chart, a table with value, data date, source and fetch time for every number, and the attribution footer.

## Run locally

Requirements: Python 3.11+ and Node.js 20.9+.

```bash
cp .env.example .env          # then put your key in .env (never commit it)
# Windows
.\run.ps1
# macOS / Linux
./run.sh
```

The run scripts build the frontend once (if `web/out` is missing) and start the API. Open http://localhost:8000.

For frontend work with hot reload, keep the API running on port 8000 and in another terminal run `cd web && npm run dev`, then open http://localhost:3000. In development the page calls the API on `http://localhost:8000`. Get a free Gemini key at https://aistudio.google.com/app/apikey. Without `GEMINI_API_KEY` the app still works and uses the rule-based answer.

Run the tests:

```bash
cd backend
../.venv/Scripts/python -m pytest -q     # Windows
../.venv/bin/python -m pytest -q         # macOS / Linux
```

Demo link format: `/advice/?location=Hubballi&q=Can+I+spray+tomorrow%3F&lang=kn` fills the form and runs the query.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/advice?q=…&location=…&lang=auto\|en\|hi\|kn` (or `&lat=…&lon=…`) | Full answer with data points, rules, sources, timestamps |
| `GET /advice?location=…&question=…&lang=en\|hi\|kn` | Same JSON as `/api/advice`. Without `question`, `/advice` serves the advice page. |
| `POST /api/transcribe?lang=auto\|en\|hi\|kn` | Body: 16-bit PCM WAV (max 30 s). Returns `{text, language, model, transcribed_at}` |
| `GET /api/locations?q=…` | Karnataka place search |
| `GET /api/rules` | Thresholds in use |
| `GET /api/health` | Status, and whether the LLM key is configured (never the key itself) |

Errors return JSON `{"error": {"code", "message"}}`: `404 location_not_found`, `503 geocoding_failed`, `422` for empty questions or coordinates outside Karnataka.

---

## Deploy (Render)

1. Push this repository to GitHub.
2. In Render, create a **Blueprint** from the repo (it reads `render.yaml`), or a Web Service with:
   - Build: `pip install -r backend/requirements.txt && cd web && npm ci && npm run build`
   - Start: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. In the Render dashboard, set **`GEMINI_API_KEY`**. It is never stored in the repository.
4. Open `/api/health` on the live URL and check that `llm_configured` is `true`, then open `/` and `/advice/`.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes (for LLM answers) | – | Google Gemini key. Without it, the rule-based answer is used. |
| `GEMINI_MODEL` | No | `gemini-3.5-flash-lite` | Main Gemini model (`LLM_MODEL` is also accepted) |
| `LLM_FALLBACK_MODEL` | No | `gemini-3.8-flash` | Used once if the main model is rate-limited or down |
| `LLM_THINKING_LEVEL` | No | `low` | `minimal`, `low`, `medium` or `high` |
| `LOG_LEVEL` | No | `INFO` | Server log level |
| `PYTHON_VERSION`, `NODE_VERSION` | Render only | `3.12.8`, `22.12.0` | Set in `render.yaml` |
| `NEXT_PUBLIC_API_BASE` | No | same origin | Only for hosting the frontend separately from the API |

## Security

- No API keys in code. `.env` is in `.gitignore`; `.env.example` holds placeholders only.
- The farmer's question is passed to the model as data inside tags, and the system prompt tells the model to ignore instructions inside it.
- The UI renders all text through React (escaped by default; no `dangerouslySetInnerHTML`).

## Roadmap

- Mandi sell-or-hold advice, once an official data.gov.in / Agmarknet API key and resource ID are available.
- Crop calendar awareness (sowing dates, growth stage).
- SMS / WhatsApp delivery for farmers without smartphones.
- District-level Soil Health Card data as a labelled background layer.
- Rain-gauge (IMD/KSNDMC) observations for month-to-date rainfall.

## Team

`<add team names>`
