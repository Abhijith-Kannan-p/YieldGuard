import type { AdviceResponse, PlaceSuggestion, TodaySummary } from "./types";

// In production the page is served by the FastAPI backend, so API calls are same-origin.
// During `next dev` (port 3000) the backend runs separately on port 8000.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

export const REQUEST_TIMEOUT_MS = 90_000;

export class ApiError extends Error {
  constructor(
    public kind: "server" | "network" | "timeout",
    message: string,
    public status?: number,
    public code?: string, // backend error code, e.g. "geocoding_failed", "location_not_found"
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${API_BASE}${path}`, { signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw new ApiError("timeout", "timeout");
    throw new ApiError("network", "network");
  }
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    /* non-JSON error page (e.g. proxy error while the server wakes up) */
  }
  if (!r.ok) {
    const err = (body as { error?: { message?: string; code?: string } } | null)?.error;
    throw new ApiError("server", err?.message || `Server error (${r.status}). Please try again.`, r.status, err?.code);
  }
  return body as T;
}

export function fetchAdvice(params: URLSearchParams, signal: AbortSignal): Promise<AdviceResponse> {
  return getJson<AdviceResponse>(`/api/advice?${params}`, signal);
}

/** Landing card and saved-field status. The server caches each location for one hour. */
export function fetchToday(where: { location?: string; lat?: number; lon?: number }, signal: AbortSignal) {
  const p = new URLSearchParams();
  if (where.lat != null && where.lon != null) {
    p.set("lat", String(where.lat));
    p.set("lon", String(where.lon));
  }
  if (where.location) p.set("location", where.location);
  return getJson<TodaySummary>(`/api/today?${p}`, signal);
}

export async function searchPlaces(q: string, signal: AbortSignal): Promise<PlaceSuggestion[]> {
  const r = await fetch(`${API_BASE}/api/locations?q=${encodeURIComponent(q)}`, { signal });
  if (!r.ok) return [];
  const data = (await r.json()) as { results: PlaceSuggestion[] };
  return data.results ?? [];
}

export interface Transcript {
  text: string;
  language: "en" | "hi" | "kn" | null;
  model: string;
  transcribed_at: string;
}

/** Sends a WAV recording to the backend for speech-to-text. Throws ApiError with a readable message. */
export async function transcribe(wav: Blob, lang: string, signal: AbortSignal): Promise<Transcript> {
  let r: Response;
  try {
    r = await fetch(`${API_BASE}/api/transcribe?lang=${encodeURIComponent(lang)}`, {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wav,
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw new ApiError("timeout", "timeout");
    throw new ApiError("network", "network");
  }
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    /* non-JSON error page */
  }
  if (!r.ok) {
    const msg = (body as { error?: { message?: string } } | null)?.error?.message;
    throw new ApiError("server", msg || `Server error (${r.status}).`, r.status);
  }
  return body as Transcript;
}
