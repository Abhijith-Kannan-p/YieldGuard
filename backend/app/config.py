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

FORECAST_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "wind_speed_10m",
]
FORECAST_DAYS = 3

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
ARCHIVE_TIMEOUT_S = 25.0      # the 25-year baseline is one large request (~7 s typical)
HTTP_RETRIES = 1              # retry once on timeout / 5xx / 429 / connection error
LLM_TIMEOUT_S = 20.0           # per attempt; a second attempt uses LLM_FALLBACK_MODEL
LLM_RETRIES = 1

# ---------------------------------------------------------------------------
# Cache TTLs (seconds). Every cached item stores its original fetch time.
# ---------------------------------------------------------------------------
TTL_GEOCODE = 7 * 24 * 3600
TTL_FORECAST = 3600
TTL_MONTH_TO_DATE = 3600
TTL_BASELINE = 7 * 24 * 3600
TTL_SOIL = 30 * 24 * 3600
CACHE_COORD_DECIMALS = 2      # cache key precision for lat/lon (~1 km)

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
HEAVY_RAIN_LOOKAHEAD_H = 24
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
SOIL_SAND_HIGH_PCT = 60.0
SOIL_CLAY_HIGH_PCT = 40.0
SOIL_PH_LOW = 5.5
SOIL_PH_HIGH = 8.5

# ---------------------------------------------------------------------------
# Language model
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Flash-Lite is fast (~2 s) and less often overloaded on the free tier; Flash is the backup.
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
if not LLM_MODEL.startswith("gemini"):  # ignore stale values such as an old Claude model name
    LLM_MODEL = "gemini-3.5-flash-lite"
# Used once if the main model is rate-limited (free tier) or temporarily down.
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "gemini-3.8-flash")
LLM_THINKING_LEVEL = os.getenv("LLM_THINKING_LEVEL", "low")  # minimal | low | medium | high
LLM_MAX_TOKENS = 8192  # includes the model's thinking tokens

SUPPORTED_LANGUAGES = {"en": "English", "hi": "Hindi", "kn": "Kannada"}

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Attribution shown in the UI and API responses
# ---------------------------------------------------------------------------
ATTRIBUTION = {
    "open-meteo": "Weather data by Open-Meteo.com (CC BY 4.0)",
    "soilgrids": "SoilGrids v2.0 by ISRIC - World Soil Information (CC BY 4.0)",
}
