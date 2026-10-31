// Shape of GET /api/advice (see backend/app/advisor.py).

export type Lang = "en" | "hi" | "kn";

export interface DataPoint {
  id: string;
  label: string;
  value: number | string | null;
  unit: string;
  valid_time: string | null;
  source_id: string;
  source: string;
  fetched_at: string | null;
  cached: boolean;
}

export interface Rule {
  id: "spray_window" | "heavy_rain" | "rain_deficit" | "soil" | string;
  name: string;
  status: string;
  summary: string;
  thresholds: Record<string, unknown>;
  evidence: string[];
}

export interface CitedItem {
  text: string;
  evidence: string[];
}

export interface SourceView {
  id: string;
  name: string;
  url: string;
  status: string;
  fetched_at: string | null;
  cached: boolean;
  stale?: boolean; // live refresh failed; data is the last good response (fetched_at is its original time)
  age_minutes?: number | null;
  error: string | null;
  attribution: string | null;
}

export interface ForecastHour {
  time: string;
  temperature_2m: number | null;
  relative_humidity_2m: number | null;
  precipitation_probability: number | null;
  precipitation: number | null;
  wind_speed_10m: number | null;
}

export interface SprayWindow {
  start: string;
  end: string;
  hours: number;
  max_wind_kmh: number;
  max_precip_prob_pct: number;
}

export interface AdviceResponse {
  request_id: string;
  generated_at: string;
  elapsed_ms: number;
  question: string;
  language: Lang;
  location: {
    name: string;
    district: string | null;
    state: string;
    lat: number;
    lon: number;
    source: string;
    fetched_at: string | null;
  };
  answer: {
    text: string;
    recommendations: CitedItem[];
    why: CitedItem[];
    missing_data: string[];
    disclaimer: string;
  };
  generated_by: string;
  llm_error: string | null;
  unverified_numbers: string[];
  data_points: DataPoint[];
  rules: Rule[];
  spray_windows: SprayWindow[];
  forecast_hourly: {
    source: string;
    fetched_at: string;
    units: Record<string, string>;
    hours: ForecastHour[];
  } | null;
  sources: SourceView[];
  warnings: string[];
  forecast_daily?: { source: string; fetched_at: string; units: Record<string, string>; days: DailyRow[] } | null;
  water_balance?: WaterBalance | null;
  heat?: HeatResult | null;
  fertiliser?: FertiliserResult | null;
  fixture_mode?: boolean; // only set by the local-development fixture server (USE_FIXTURES=1)
  data_age?: { source: string; fetched_at: string | null; age_minutes: number | null; cached: boolean; stale: boolean }[];
  attribution: string[];
}

export interface PlaceSuggestion {
  name: string;
  district: string | null;
  lat: number;
  lon: number;
}

export interface DailyRow {
  date: string;
  precipitation_sum: number | null;
  et0_fao_evapotranspiration: number | null;
  temperature_2m_max: number | null;
}

export interface WaterBalance {
  status: "irrigate" | "ok" | "unknown";
  irrigate_on: string | null;
  days: { date: string; et0_mm: number; crop_use_mm: number; rain_mm: number; deficit_mm: number; over_threshold: boolean }[];
  final_deficit_mm: number | null;
  total_crop_use_mm: number | null;
  total_rain_mm: number | null;
  incomplete_from: string | null;
  thresholds: { crop_factor: number; deficit_mm: number; days: number };
}

export interface HeatResult {
  status: "warning" | "ok" | "unknown";
  hot_days: { date: string; tmax_c: number }[];
  max_tmax_c: number | null;
  max_tmax_date: string | null;
  thresholds: { tmax_c: number; days: number };
}

export interface FertiliserResult {
  status: "delay" | "ok" | "unknown";
  max_precip_prob_pct: number | null;
  max_precip_prob_time: string | null;
  total_precip_mm: number | null;
  window_start: string | null;
  window_end: string | null;
  thresholds: { prob_pct: number; total_mm: number; lookahead_h: number };
}

export interface TodaySource {
  name: string;
  status: string;
  fetched_at: string | null;
  cached: boolean;
  stale: boolean;
  error: string | null;
}

/** GET /api/today: short live summary for the landing card and saved fields. */
export interface TodaySummary {
  location: { name: string; district: string | null; lat: number; lon: number };
  computed_at: string;
  refresh_after_s: number;
  served_from_cache: boolean;
  sources: { forecast: TodaySource; soil: TodaySource; baseline: TodaySource };
  spray: { next: SprayWindow | null; hours_checked: number } | null;
  rain_24h: {
    max_prob_pct: number | null;
    max_prob_time: string | null;
    total_mm: number | null;
    window_start: string | null;
    window_end: string | null;
    status: string;
  } | null;
  soil: { sand_pct: number | null; clay_pct: number | null; ph: number | null; flags: string[]; offset_km: number | null } | null;
  warnings: { id: string; time: string | null; value: number | null; unit: string }[];
}

/** POST /api/followup */
export interface FollowupResponse {
  followup_id: string;
  question: string;
  language: Lang;
  covered: boolean;
  not_covered_message: string | null;
  answer: { text: string; why: CitedItem[]; missing_data: string[]; disclaimer: string };
  evidence_points: DataPoint[];
  unverified_numbers: string[];
  generated_by: string;
  generated_at: string;
  based_on_request_id: string;
  data_fetched_at: string;
  data_age_minutes: number;
  followups_used: number;
  followups_limit: number;
}
