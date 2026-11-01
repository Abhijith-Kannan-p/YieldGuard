// The browser-side forecast fetch: one Open-Meteo request per question, a 10-minute copy per place,
// and a 429 handed to the server (which uses MET Norway) without a second Open-Meteo call.
import { describe, expect, it, vi } from "vitest";
import { postAdvice } from "@/lib/api";
import { cacheKey, fetchForecast, forecastUrl, pastDays, SOURCE_NAME } from "@/lib/forecastClient";

const NOW = new Date("2026-10-31T11:50:00Z"); // 17:20 in Asia/Kolkata
const PAYLOAD = { latitude: 15.43, longitude: 75.04, timezone: "Asia/Kolkata", hourly: {}, daily: {} };

function memoryStorage() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("forecast request", () => {
  it("asks for the same fields as the server, at two-decimal coordinates", () => {
    const u = new URL(forecastUrl(15.46005, 75.00778, "2026-10-31"));
    expect(u.origin + u.pathname).toBe("https://api.open-meteo.com/v1/forecast");
    expect(Object.fromEntries(u.searchParams)).toEqual({
      latitude: "15.46",
      longitude: "75.01",
      hourly: "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,wind_speed_10m",
      daily: "precipitation_sum,et0_fao_evapotranspiration,temperature_2m_max",
      timezone: "Asia/Kolkata",
      forecast_hours: "73",
      past_hours: "0",
      forecast_days: "7",
      past_days: "30",
    });
  });

  it("goes back to the start of the rainfall window (last month on the 1st)", () => {
    expect(pastDays("2026-10-31")).toBe(30);
    expect(pastDays("2026-10-02")).toBe(1);
    expect(pastDays("2026-11-01")).toBe(31);
    expect(pastDays("2026-03-01")).toBe(28);
  });
});

describe("fetchForecast", () => {
  it("returns the JSON with the fetch time and source name, and keeps a 10-minute copy", async () => {
    const storage = memoryStorage();
    const fetchMock = vi.fn(async () => json(200, PAYLOAD));
    let now = NOW;
    const deps = { fetch: fetchMock as unknown as typeof fetch, storage, now: () => now };

    const first = await fetchForecast(15.46005, 75.00778, deps);
    expect(first).toEqual({ ok: true, data: PAYLOAD, fetched_at: NOW.toISOString(), source: SOURCE_NAME, cached: false });
    expect(storage.m.has(cacheKey(15.46, 75.01, "2026-10-31"))).toBe(true);

    now = new Date(NOW.getTime() + 9 * 60_000);
    const again = await fetchForecast(15.4612, 75.0049, deps); // rounds to the same place
    expect(again).toMatchObject({ ok: true, cached: true, fetched_at: NOW.toISOString() });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    now = new Date(NOW.getTime() + 11 * 60_000);
    await fetchForecast(15.46005, 75.00778, deps);
    expect(fetchMock).toHaveBeenCalledTimes(2); // copy expired
  });

  it("reports a network failure or timeout without throwing", async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const res = await fetchForecast(15.46, 75.01, { fetch: fetchMock as unknown as typeof fetch, storage: null, now: () => NOW });
    expect(res).toEqual({ ok: false, status: null, error: "network error", source: SOURCE_NAME });
  });

  it("on HTTP 429 makes one Open-Meteo call, caches nothing, and the server falls back to MET Norway", async () => {
    const storage = memoryStorage();
    const calls: string[] = [];
    let posted: { forecast?: unknown } = {};
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(url);
      if (url.startsWith("https://api.open-meteo.com/")) return json(429, { error: true, reason: "Minutely API request limit exceeded." });
      posted = JSON.parse(String(init?.body));
      return json(200, { forecast_path: "metno", sources: [{ id: "forecast", name: "MET Norway fallback (Locationforecast 2.0)", fallback_for: "Open-Meteo" }] });
    });
    vi.stubGlobal("fetch", fetchMock);
    try {
      const forecast = await fetchForecast(15.46, 75.01, { storage, now: () => NOW });
      expect(forecast).toEqual({ ok: false, status: 429, error: "HTTP 429", source: SOURCE_NAME });
      expect(storage.m.size).toBe(0);

      const res = await postAdvice(
        { question: "Can I spray?", location: "Dharwad", lang: "en", forecast },
        new AbortController().signal,
      );
      expect(posted.forecast).toEqual(forecast);
      expect(res.forecast_path).toBe("metno");
      expect(calls.filter((u) => u.includes("open-meteo.com"))).toHaveLength(1); // no second Open-Meteo call
      expect(calls.filter((u) => u.endsWith("/api/advice"))).toHaveLength(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
