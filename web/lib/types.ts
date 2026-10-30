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
  data_age?: { source: string; fetched_at: string | null; age_minutes: number | null; cached: boolean; stale: boolean }[];
  attribution: string[];
}

export interface PlaceSuggestion {
  name: string;
  district: string | null;
  lat: number;
  lon: number;
}
