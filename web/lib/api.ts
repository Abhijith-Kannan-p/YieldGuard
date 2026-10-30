import type { AdviceResponse, PlaceSuggestion } from "./types";

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
  ) {
    super(message);
  }
}

export async function fetchAdvice(params: URLSearchParams, signal: AbortSignal): Promise<AdviceResponse> {
  let r: Response;
  try {
    r = await fetch(`${API_BASE}/api/advice?${params}`, { signal });
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
    const msg = (body as { error?: { message?: string } } | null)?.error?.message;
    throw new ApiError("server", msg || `Server error (${r.status}). Please try again.`, r.status);
  }
  return body as AdviceResponse;
}

export async function searchPlaces(q: string, signal: AbortSignal): Promise<PlaceSuggestion[]> {
  const r = await fetch(`${API_BASE}/api/locations?q=${encodeURIComponent(q)}`, { signal });
  if (!r.ok) return [];
  const data = (await r.json()) as { results: PlaceSuggestion[] };
  return data.results ?? [];
}
