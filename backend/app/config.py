"""All tunable constants live here. Change thresholds without touching the logic.

Secrets (API keys) are NOT stored here - they come from environment variables.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (one level above backend/) if present.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

TIMEZONE = "Asia/Kolkata"
DEFAULT_LOCATION = "Dharwad"
REGION_NAME = "Karnataka"  # geocoding results are restricted to this state
COUNTRY_CODE = "IN"

# ---------------------------------------------------------------------------
# Data source endpoints
# ---------------------------------------------------------------------------
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
# Same SoilGrids maps through ISRIC's WCS map service: used when the REST API above fails (it is often 503).
SOILGRIDS_WCS_URL = "https://maps.isric.org/mapserv"
SOIL_WCS_HALF_WINDOW_DEG = 0.025  # read a ~5 km square around the point; masked (urban) pixels -> nearest valid one
# Mandi prices: Agmarknet daily prices on data.gov.in (latest day only; the arrival_date filter is ignored).
MANDI_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
DATAGOV_API_KEY = os.getenv("DATAGOV_API_KEY", "").strip()
# data.gov.in's gateway hangs and returns 502 for a generic client User-Agent; this one gets a quick 200.
MANDI_HEADERS = {"User-Agent": "YieldGuard/1.0 (hackathon project)", "Accept": "*/*"}

# Fallbacks (see sources/metno.py and baseline.py)
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
# MET Norway requires a User-Agent that identifies the app and a contact (email or URL). Set it in the
# environment, never in code: METNO_CONTACT=you@example.org. Without it the fallback is not used.
METNO_CONTACT = os.getenv("METNO_CONTACT", "").strip()
METNO_FALLBACK_STATUSES = {429, 500, 502, 503, 504}  # Open-Meteo failures that switch to MET Norway
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_POWER_TIMEOUT_S = 60.0       # 26 years of daily data; background build only, never during a question
NASA_POWER_FILL = -999.0          # NASA POWER's missing-value marker

FORECAST_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "wind_speed_10m",
]
# One forecast request returns all of these (see sources/forecast.py):
FORECAST_HOURS = 72                # hourly data from the current hour: spray windows, 72-hour strip, rain rules
FORECAST_DAILY_VARS = [            # daily data: month-to-date rain, irrigation planner, heat alert
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "temperature_2m_max",
]
FORECAST_DAILY_DAYS = 7            # daily forecast days (today + 6) for the irrigation planner and heat alert

# Forecast fetched in the visitor's browser and posted with the question (sources/browser_forecast.py).
# The server checks it before any rule uses it.
BROWSER_FORECAST_MAX_AGE_S = 15 * 60     # the browser keeps its copy 10 min; allow a little clock skew
BROWSER_FORECAST_MAX_AHEAD_S = 5 * 60    # a fetch time further in the future than this is rejected
BROWSER_FORECAST_MAX_GRID_OFFSET_DEG = 0.2  # Open-Meteo's grid point must be this close to the place
BROWSER_FORECAST_PLAUSIBLE = {           # (min, max) for every value; None (missing) is allowed
    "temperature_2m": (-20.0, 60.0),
    "temperature_2m_max": (-20.0, 60.0),
    "wind_speed_10m": (0.0, 300.0),
    "precipitation_probability": (0.0, 100.0),
    "relative_humidity_2m": (0.0, 100.0),
    "precipitation": (0.0, 500.0),
    "precipitation_sum": (0.0, 2000.0),
    "et0_fao_evapotranspiration": (0.0, 30.0),
}

SOIL_PROPERTIES = ["clay", "sand", "phh2o", "soc"]
SOIL_DEPTH = "0-5cm"
SOIL_VALUE = "mean"
# SoilGrids masks urban pixels (null values). If the exact point is null we try
# these offsets (degrees, ~2-3 km) one at a time and report the distance used.
SOIL_FALLBACK_OFFSETS = [(0.02, 0.0), (-0.02, 0.0), (0.0, 0.02), (0.0, -0.02)]
SOIL_TOTAL_BUDGET_S = 20.0  # stop probing nearby points after this long

# ---------------------------------------------------------------------------
# Network behaviour
# ---------------------------------------------------------------------------
HTTP_TIMEOUT_S = 8.0          # per call, per the brief
HTTP_RETRIES = 1              # retry once on timeout / 5xx / connection error (never on 429)
LLM_TIMEOUT_S = 20.0           # per attempt; a second attempt uses LLM_FALLBACK_MODEL
LLM_RETRIES = 1

# Open-Meteo's free tier is limited per IP address (600 calls/min, 5,000/h, 10,000/day) and
# weights each call by its length (about days / 14). On shared hosting the IP is shared too.
OPEN_METEO_MAX_CONCURRENT = 1   # Open-Meteo calls are sent one at a time
OTHER_MAX_CONCURRENT = 4        # other providers (SoilGrids)
RATE_LIMIT_BACKOFF_S = 60       # after an Open-Meteo HTTP 429: no Open-Meteo call for at least this long...
RATE_LIMIT_BACKOFF_MAX_S = 6 * 3600  # ...or Retry-After if longer, capped here. (Not applied to SoilGrids/Gemini.)

# Rainfall baseline: ONE archive request per district for the whole period, built in the
# background (never during a question) and saved to BASELINE_FILE.
BASELINE_TIMEOUT_S = 30.0       # the 26-year request is large (~7 s typical)
BASELINE_BUILD_SPACING_S = 70   # pause between background builds so big requests fall in different minutes
BASELINE_RETRY_AFTER_S = 10 * 60  # after a failed build, wait this long before trying that district again
BASELINE_MIN_YEARS = 10         # fewer usable years than this -> the build counts as failed

# ---------------------------------------------------------------------------
# Cache TTLs (seconds). Every cached item stores its original fetch time.
# ---------------------------------------------------------------------------
CACHE_COORD_DECIMALS = 2      # cache key precision for lat/lon (~1 km)
TTL_GEOCODE = 7 * 24 * 3600
TTL_FORECAST = 60 * 60        # forecast + recent past rain (one request), per location
TTL_BASELINE = 30 * 24 * 3600 # rebuild a district's baseline in the background after this
TTL_SOIL = 7 * 24 * 3600      # per coordinate pair (rounded to 2 decimals); older copies are still used on a 503
TTL_TODAY = 60 * 60           # landing-page "Today in your field" summary, per location
TTL_MANDI = 6 * 3600          # all Karnataka mandi prices (one snapshot a day)

# Saved data, loaded at startup so a restart does not refetch it. On hosts with an ephemeral
# disk (Render's free plan) the files last until the next deploy or restart.
# data/ holds only the rainfall baseline; other caches live in .cache/.
DATA_DIR = Path(os.getenv("YIELDGUARD_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
BASELINE_FILE = DATA_DIR / "baselines.json"
CACHE_DIR = Path(os.getenv("YIELDGUARD_CACHE_DIR", Path(__file__).resolve().parents[1] / ".cache"))
SOIL_CACHE_FILE = CACHE_DIR / "soil_cache.json"

# If a live refresh fails (rate limit, outage), the last good response may be shown instead,
# labelled as such and with its original fetch time, as long as it is no older than this.
STALE_MAX_AGE_S = {
    "geocode": 30 * 24 * 3600,
    "forecast": 12 * 3600,      # a 3-day forecast from 12 h ago still covers the next 60 h
    "soil": 90 * 24 * 3600,
    "mandi": 48 * 3600,          # a saved snapshot still shows its own arrival dates
}

# ---------------------------------------------------------------------------
# RULE: spray window
# ---------------------------------------------------------------------------
SPRAY_MAX_WIND_KMH = 10.0          # wind_speed_10m must be below this
SPRAY_MAX_PRECIP_PROB_PCT = 20.0   # precipitation_probability must be below this
SPRAY_MAX_PRECIP_MM = 0.0          # precipitation must not exceed this (i.e. no rain)
SPRAY_MIN_HOURS = 3                # consecutive qualifying hours
SPRAY_MAX_WINDOWS = 3              # return the earliest N windows
# Only consider daylight hours [start, end). Set to None to allow any hour.
SPRAY_ALLOWED_HOURS = (6, 19)

# ---------------------------------------------------------------------------
# RULE: heavy rain warning (next 24 h)
# ---------------------------------------------------------------------------
HEAVY_RAIN_LOOKAHEAD_H = 24        # hours of forecast checked
HEAVY_RAIN_PROB_PCT = 70.0         # any hour above this -> warning
HEAVY_RAIN_TOTAL_MM = 40.0         # 24 h total above this -> warning

# ---------------------------------------------------------------------------
# RULE: rainfall deficit (month to date vs long-run average)
# ---------------------------------------------------------------------------
BASELINE_START_YEAR = 2000
BASELINE_END_YEAR = None           # None -> last complete calendar year
DEFICIT_DROUGHT_PCT = 60.0         # below this % of normal -> drought risk
DEFICIT_WATERLOG_PCT = 150.0       # above this % of normal -> waterlogging risk
DEFICIT_MIN_BASELINE_MM = 5.0      # if normal is below this, % is unreliable (dry season)

# ---------------------------------------------------------------------------
# RULE: soil
# ---------------------------------------------------------------------------
SOIL_SAND_HIGH_PCT = 60.0          # sand above this % -> lighter, more frequent irrigation
SOIL_CLAY_HIGH_PCT = 40.0          # clay above this % -> caution during heavy rain (slow drainage)
SOIL_PH_LOW = 5.5                  # pH below this -> mention it and suggest a soil test
SOIL_PH_HIGH = 8.5                 # pH above this -> mention it and suggest a soil test

# ---------------------------------------------------------------------------
# RULE: irrigation planner (daily water balance, next FORECAST_DAILY_DAYS days) - an estimate
#   deficit(day) = max(0, deficit(day before) + ET0 x CROP_FACTOR - rain), starting at 0 today
# ---------------------------------------------------------------------------
CROP_FACTOR = 0.85                 # Kc: crop water use as a fraction of reference ET0 (generic field crop, mid-season)
IRRIGATION_DEFICIT_MM = 25.0       # suggest irrigating on the first day the running deficit exceeds this (mm)

# ---------------------------------------------------------------------------
# RULE: heat stress (daily maximum temperature, next FORECAST_DAILY_DAYS days)
# ---------------------------------------------------------------------------
HEAT_THRESHOLD_C = 35.0            # flag any day whose temperature_2m_max is above this (deg C)

# ---------------------------------------------------------------------------
# RULE: fertiliser timing (next 48 h) - rain soon after application leaches nutrients
# ---------------------------------------------------------------------------
FERTILISER_LOOKAHEAD_H = 48        # hours of forecast checked
FERTILISER_RAIN_PROB_PCT = 70.0    # any hour above this rain probability -> delay fertiliser
FERTILISER_RAIN_TOTAL_MM = 40.0    # total forecast rain above this (mm) -> delay fertiliser

# Mandi prices: nearest market within MANDI_MAX_DISTANCE_KM that reports the farmer's crop.
MANDI_PAGE_SIZE = 1000            # records per data.gov.in request; pages follow "total"
MANDI_MAX_RECORDS = 5000          # stop paging after this many records
MANDI_TIMEOUT_S = 30.0            # per request: data.gov.in can be slow
MANDI_WAIT_S = 10.0               # a question waits at most this long; a slower fetch finishes in the background
MANDI_RETRY_AFTER_S = 5 * 60      # after a failed fetch, no new attempt for this long
MANDI_MAX_DISTANCE_KM = 125.0     # markets farther than this are never used
MANDI_MAX_GEOCODES = 12           # new market-name lookups per question (cached lookups are free)
MANDI_MAX_VARIETIES = 3           # varieties of the crop shown for the chosen market
# data.gov.in and Open-Meteo name some places differently (Ramanagara is listed as Closepet); names only, no coordinates.
MARKET_GEOCODE_NAMES = {"Ramanagara": "Closepet"}

# Crop words a farmer may type -> fragments of Agmarknet commodity names (case-insensitive).
# "exclude": commodity names containing these are other products (e.g. dal). Longest word wins,
# so "ಮೆಕ್ಕೆಜೋಳ" (maize) is not read as "ಜೋಳ" (jowar).
CROP_ALIASES = {
    "jowar": {"words": ["jowar", "sorghum", "ज्वार", "ಜೋಳ", "ಬಿಳಿಜೋಳ"], "commodity": ["jowar", "sorghum"]},
    "maize": {"words": ["maize", "corn", "मक्का", "ಮೆಕ್ಕೆಜೋಳ", "ಮೆಕ್ಕೆ ಜೋಳ"], "commodity": ["maize"]},
    "ragi": {"words": ["ragi", "finger millet", "रागी", "मडुआ", "ರಾಗಿ"], "commodity": ["ragi"]},
    "paddy": {"words": ["paddy", "धान", "ಭತ್ತ"], "commodity": ["paddy"]},
    "rice": {"words": ["rice", "चावल", "ಅಕ್ಕಿ"], "commodity": ["rice"], "exclude": ["paddy"]},
    "wheat": {"words": ["wheat", "गेहूं", "गेहूँ", "ಗೋಧಿ"], "commodity": ["wheat"], "exclude": ["atta"]},
    "bengal_gram": {"words": ["bengal gram", "chana", "chickpea", "gram", "चना", "ಕಡಲೆ"],
                    "commodity": ["bengal gram"], "exclude": ["dal"]},
    "tur": {"words": ["tur", "toor", "arhar", "red gram", "pigeon pea", "अरहर", "तुअर", "तूर", "ತೊಗರಿ"],
            "commodity": ["arhar", "tur"], "exclude": ["dal"]},
    "green_gram": {"words": ["green gram", "moong", "मूंग", "ಹೆಸರುಕಾಳು"], "commodity": ["green gram"],
                   "exclude": ["dal"]},
    "groundnut": {"words": ["groundnut", "ground nut", "peanut", "मूंगफली", "ಶೇಂಗಾ", "ಕಡಲೆಕಾಯಿ"],
                  "commodity": ["groundnut", "ground nut"]},
    "soyabean": {"words": ["soyabean", "soybean", "soya", "सोयाबीन", "ಸೋಯಾಬೀನ್", "ಸೋಯಾ"], "commodity": ["soyabean"]},
    "sunflower": {"words": ["sunflower", "सूरजमुखी", "ಸೂರ್ಯಕಾಂತಿ"], "commodity": ["sunflower"]},
    "cotton": {"words": ["cotton", "कपास", "ಹತ್ತಿ"], "commodity": ["cotton"]},
    "onion": {"words": ["onion", "प्याज", "ಈರುಳ್ಳಿ"], "commodity": ["onion"]},
    "tomato": {"words": ["tomato", "टमाटर", "ಟೊಮೆಟೊ", "ಟೊಮ್ಯಾಟೊ", "ಟೊಮೇಟೊ"], "commodity": ["tomato"]},
    "potato": {"words": ["potato", "आलू", "ಆಲೂಗಡ್ಡೆ"], "commodity": ["potato"]},
}

# ---------------------------------------------------------------------------
# Language model
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Flash-Lite is fast (~2 s) and less often overloaded on the free tier; Flash is the backup.
# GEMINI_MODEL is the documented name; LLM_MODEL is kept for older .env files.
LLM_MODEL = os.getenv("GEMINI_MODEL") or os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
if not LLM_MODEL.startswith("gemini"):  # ignore stale values such as an old Claude model name
    LLM_MODEL = "gemini-3.5-flash-lite"
# Used once if the main model is rate-limited (free tier) or temporarily down.
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "gemini-3.8-flash")
LLM_THINKING_LEVEL = os.getenv("LLM_THINKING_LEVEL", "low")  # minimal | low | medium | high
LLM_MAX_TOKENS = 8192  # includes the model's thinking tokens

SUPPORTED_LANGUAGES = {"en": "English", "hi": "Hindi", "kn": "Kannada"}

# ---------------------------------------------------------------------------
# Follow-up questions: the last answer's data is kept in server memory per session
# (cookie SESSION_COOKIE), never in a database. Follow-ups reuse it without new API calls.
# ---------------------------------------------------------------------------
SESSION_COOKIE = "yg_session"
SESSION_TTL_S = 30 * 60            # a session (and its stored answer data) expires after 30 min without use
SESSION_MAX = 2000                 # most sessions kept in memory; the least recently used are dropped
FOLLOWUP_LIMIT = 10                # follow-up questions allowed per session...
FOLLOWUP_WINDOW_S = 30 * 60        # ...within this rolling window
FOLLOWUP_MAX_DATA_AGE_S = 60 * 60  # stored forecast older than this -> ask the farmer to refresh instead of answering
# Origins allowed to call the API with the session cookie from another port (Next.js dev server only;
# in production the page and API share one origin).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
                if o.strip()]

# Voice input: the browser records up to TRANSCRIBE_MAX_SECONDS and uploads 16 kHz mono WAV
# (32 kB per second), which Gemini transcribes.
TRANSCRIBE_MAX_SECONDS = 30
TRANSCRIBE_MAX_BYTES = 2_500_000

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Attribution shown in the UI and API responses
# ---------------------------------------------------------------------------
ATTRIBUTION = {
    "open-meteo": "Weather data by Open-Meteo.com (CC BY 4.0)",
    "soilgrids": "SoilGrids v2.0 by ISRIC - World Soil Information (CC BY 4.0)",
    "datagov": "Mandi prices: Agmarknet via data.gov.in (Government Open Data License - India)",
}
