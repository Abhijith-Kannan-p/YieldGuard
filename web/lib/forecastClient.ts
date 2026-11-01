// The live forecast is fetched here, in the visitor's browser, so Open-Meteo counts the request against the
// visitor's own address rather than the server's shared one (which was getting HTTP 429). The JSON is posted
// with the question; the server checks it before any rule uses it (backend/app/sources/browser_forecast.py).
//
// Open-Meteo weights a request by the days it covers (about days / 14), so this is two light requests
// instead of one heavy one:
// - the forecast (73 hours, 7 days, no past days): one per question, kept 10 minutes;
// - the daily rain since the start of the rainfall-deficit window: once per place per day, kept until
//   midnight (past rain does not change).
// Same fields as backend/app/sources/forecast.py: keep the two in step.

export const FORECAST_URL = "https://api.open-meteo.com/v1/forecast";
export const SOURCE_NAME = "Open-Meteo (browser)";
export const FETCH_TIMEOUT_MS = 8_000;
export const CACHE_TTL_MS = 10 * 60_000; // one forecast request per place per 10 minutes, at most

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

const iso = (y: number, m: number, d: number) => new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);

/** The rainfall-deficit window, as in backend rules/deficit.py: the 1st of this month to yesterday,
 *  or the whole of last month on the 1st. */
export function rainWindow(today: string): { start: string; end: string } {
  const [y, m, d] = today.split("-").map(Number);
  return d !== 1 ? { start: iso(y, m, 1), end: iso(y, m, d - 1) } : { start: iso(y, m - 1, 1), end: iso(y, m, 0) };
}

const round2 = (v: number) => Math.round(v * 100) / 100;
const place = (lat: number, lon: number) => `${round2(lat).toFixed(2)},${round2(lon).toFixed(2)}`;

/** localStorage keys: coordinates rounded to two decimals (about 1 km), plus the local date. */
export const cacheKey = (lat: number, lon: number, today: string) => `yg.forecast.${today}.${place(lat, lon)}`;
export const pastRainKey = (lat: number, lon: number, today: string) => `yg.pastrain.${today}.${place(lat, lon)}`;

export function forecastUrl(lat: number, lon: number): string {
  const p = new URLSearchParams({
    latitude: String(round2(lat)),
    longitude: String(round2(lon)),
    hourly: HOURLY.join(","),
    daily: DAILY.join(","),
    timezone: TIMEZONE,
    forecast_hours: String(FORECAST_HOURS + 1), // Open-Meteo's "current hour" can trail ours by one
    past_hours: "0",
    forecast_days: String(FORECAST_DAYS),
    past_days: "0",
  });
  return `${FORECAST_URL}?${p}`;
}

export function pastRainUrl(lat: number, lon: number, today: string): string {
  const { start, end } = rainWindow(today);
  const p = new URLSearchParams({
    latitude: String(round2(lat)),
    longitude: String(round2(lon)),
    daily: "precipitation_sum",
    timezone: TIMEZONE,
    start_date: start,
    end_date: end,
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

/** One Open-Meteo request, or the saved copy while `ttlMs` has not passed. Never throws and never retries:
 *  a failure is returned as { ok: false, status }. */
async function cachedGet(url: string, key: string, ttlMs: number, deps: ForecastDeps): Promise<BrowserForecast> {
  const doFetch = deps.fetch ?? fetch;
  const storage = deps.storage === undefined ? defaultStorage() : deps.storage;
  const now = deps.now ?? (() => new Date());

  try {
    const saved = storage?.getItem(key);
    if (saved) {
      const entry = JSON.parse(saved) as { data: unknown; fetched_at: string };
      if (now().getTime() - Date.parse(entry.fetched_at) < ttlMs) {
        return { ok: true, data: entry.data, fetched_at: entry.fetched_at, source: SOURCE_NAME, cached: true };
      }
    }
  } catch {
    /* unreadable copy: fetch again */
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const r = await doFetch(url, { signal: ctrl.signal });
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

/** The forecast: one request per question (or the 10-minute copy). On failure the server uses MET Norway. */
export function fetchForecast(lat: number, lon: number, deps: ForecastDeps = {}): Promise<BrowserForecast> {
  const today = localDate((deps.now ?? (() => new Date()))());
  return cachedGet(forecastUrl(lat, lon), cacheKey(lat, lon, today), CACHE_TTL_MS, deps);
}

/** Daily rain over the deficit window: once per place per day. The key holds the date, so the copy is
 *  replaced after midnight. On failure month-to-date rain is reported missing. */
export function fetchPastRain(lat: number, lon: number, deps: ForecastDeps = {}): Promise<BrowserForecast> {
  const today = localDate((deps.now ?? (() => new Date()))());
  return cachedGet(pastRainUrl(lat, lon, today), pastRainKey(lat, lon, today), 24 * 3600_000, deps);
}
