// The live forecast is fetched here, in the visitor's browser, so Open-Meteo counts the request against the
// visitor's own address rather than the server's shared one (which was getting HTTP 429). The JSON is posted
// with the question; the server checks it before any rule uses it (backend/app/sources/browser_forecast.py).
// Same request as backend/app/sources/forecast.py: keep the two in step.

export const FORECAST_URL = "https://api.open-meteo.com/v1/forecast";
export const SOURCE_NAME = "Open-Meteo (browser)";
export const FETCH_TIMEOUT_MS = 8_000;
export const CACHE_TTL_MS = 10 * 60_000; // one request per place per 10 minutes, at most

const TIMEZONE = "Asia/Kolkata";
const HOURLY = ["temperature_2m", "relative_humidity_2m", "precipitation_probability", "precipitation", "wind_speed_10m"];
const DAILY = ["precipitation_sum", "et0_fao_evapotranspiration", "temperature_2m_max"];
const FORECAST_HOURS = 72;
const FORECAST_DAYS = 7;

export type BrowserForecast =
  | { ok: true; data: unknown; fetched_at: string; source: string; cached: boolean }
  | { ok: false; status: number | null; error: string; source: string };

export interface ForecastDeps {
  fetch?: typeof fetch;
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  now?: () => Date;
}

/** Today's date in Asia/Kolkata, YYYY-MM-DD. */
export function localDate(now: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TIMEZONE }).format(now);
}

/** Days of past daily rain to request: back to the start of the rainfall-deficit window
 *  (the 1st of this month, or of last month on the 1st), as in backend rules/deficit.py. */
export function pastDays(today: string): number {
  const [y, m, d] = today.split("-").map(Number);
  return d !== 1 ? d - 1 : new Date(Date.UTC(y, m - 1, 0)).getUTCDate();
}

const round2 = (v: number) => Math.round(v * 100) / 100;

/** localStorage key: coordinates rounded to two decimals (about 1 km), plus the local date. */
export function cacheKey(lat: number, lon: number, today: string): string {
  return `yg.forecast.${today}.${round2(lat).toFixed(2)},${round2(lon).toFixed(2)}`;
}

export function forecastUrl(lat: number, lon: number, today: string): string {
  const p = new URLSearchParams({
    latitude: String(round2(lat)),
    longitude: String(round2(lon)),
    hourly: HOURLY.join(","),
    daily: DAILY.join(","),
    timezone: TIMEZONE,
    forecast_hours: String(FORECAST_HOURS + 1), // Open-Meteo's "current hour" can trail ours by one
    past_hours: "0",
    forecast_days: String(FORECAST_DAYS),
    past_days: String(pastDays(today)),
  });
  return `${FORECAST_URL}?${p}`;
}

function defaultStorage(): ForecastDeps["storage"] {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null; // storage blocked (private mode, site data off)
  }
}

/** One Open-Meteo request (or the 10-minute copy). Never throws and never retries: a failure is
 *  returned as { ok: false, status } and the server then uses MET Norway. */
export async function fetchForecast(lat: number, lon: number, deps: ForecastDeps = {}): Promise<BrowserForecast> {
  const doFetch = deps.fetch ?? fetch;
  const storage = deps.storage === undefined ? defaultStorage() : deps.storage;
  const now = deps.now ?? (() => new Date());
  const today = localDate(now());
  const key = cacheKey(lat, lon, today);

  try {
    const saved = storage?.getItem(key);
    if (saved) {
      const entry = JSON.parse(saved) as { data: unknown; fetched_at: string };
      if (now().getTime() - Date.parse(entry.fetched_at) < CACHE_TTL_MS) {
        return { ok: true, data: entry.data, fetched_at: entry.fetched_at, source: SOURCE_NAME, cached: true };
      }
    }
  } catch {
    /* unreadable copy: fetch again */
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const r = await doFetch(forecastUrl(lat, lon, today), { signal: ctrl.signal });
    if (!r.ok) return { ok: false, status: r.status, error: `HTTP ${r.status}`, source: SOURCE_NAME };
    const data: unknown = await r.json();
    const fetched_at = now().toISOString();
    try {
      storage?.setItem(key, JSON.stringify({ data, fetched_at }));
    } catch {
      /* storage full or blocked: the answer still works */
    }
    return { ok: true, data, fetched_at, source: SOURCE_NAME, cached: false };
  } catch (err) {
    const timedOut = (err as Error).name === "AbortError";
    return { ok: false, status: null, error: timedOut ? "timed out after 8 s" : "network error", source: SOURCE_NAME };
  } finally {
    clearTimeout(timer);
  }
}
