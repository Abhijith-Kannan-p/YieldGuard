// The answer must render its sections in a fixed order. The fixture is a real /api/advice response
// for Dharwad saved under tests/fixtures (tests only; the app never imports it).
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AdviceResult from "@/components/AdviceResult";
import { I18N } from "@/lib/i18n";
import type { AdviceResponse } from "@/lib/types";
import fixture from "./fixtures/advice_dharwad.json";

const L = I18N.en;
const res = fixture as unknown as AdviceResponse;
const render = (r: AdviceResponse) => renderToStaticMarkup(<AdviceResult res={r} L={L} />);
const sections = (html: string) => [...html.matchAll(/data-section="(\w+)"/g)].map((m) => m[1]);

describe("answer layout", () => {
  it("renders the summary bar, then the now row, then the rest, ending with the data table", () => {
    const order = sections(render(res));
    expect(order).toEqual(["summary", "now", "strip", "alerts", "advice", "why", "sources"]);
    expect(order.indexOf("summary")).toBeLessThan(order.indexOf("now"));
    expect(order.indexOf("now")).toBeLessThan(order.indexOf("sources"));
  });

  it("shows three now cards with units, and a dash plus 'not available' when a value is missing", () => {
    const html = render(res);
    for (const label of [L.tileTemp, L.tileRain, L.tileWind]) expect(html).toContain(`aria-label="${label}"`);
    const noWind = { ...res, data_points: res.data_points.filter((p) => p.id !== "now_wind") };
    const missing = render(noWind);
    expect(missing).toContain("–");
    expect(missing).toContain(L.notAvailable);
  });

  it("keeps 'Why this advice' collapsed and lists every source with its status", () => {
    const html = render(res);
    expect(html).toMatch(/<details data-section="why"(?![^>]*\bopen\b)[^>]*>/);
    for (const s of res.sources) expect(html).toContain(s.name);
    expect(html).toContain(L.statusUnavailable); // SoilGrids failed when this response was saved
  });

  it("names the browser fetch in the sources table and says which forecast path was used", () => {
    const fc = { ...res.sources.find((s) => s.id === "forecast")!, name: "Open-Meteo (fetched in your browser)" };
    const html = render({ ...res, forecast_path: "browser", sources: res.sources.map((s) => (s.id === "forecast" ? fc : s)) });
    expect(html).toContain("Open-Meteo (fetched in your browser)");
    expect(html).toContain('data-forecast-path="browser"');
    expect(html).toContain(L.forecastPath.browser);
    expect(render({ ...res, forecast_path: "metno" })).toContain(L.forecastPath.metno);
  });

  it("labels every fourth hour of the strip", () => {
    const html = render(res);
    const first = res.forecast_hourly!.hours;
    expect(html).toContain(first[0].time.slice(11, 16));
    expect(html).toContain(first[4].time.slice(11, 16));
  });
});

describe("sentence splitting", () => {
  it("does not split inside decimal numbers", async () => {
    const { sentences, firstSentence } = await import("@/components/AnswerSections");
    const text = "No safe spray window. The highest wind is 15.1 km/h at 09:30. Wait for calm weather.";
    expect(sentences(text)).toEqual(["No safe spray window.", "The highest wind is 15.1 km/h at 09:30.", "Wait for calm weather."]);
    expect(firstSentence("Rain chance is 86.5% tomorrow. Delay spraying.")).toBe("Rain chance is 86.5% tomorrow.");
  });
});
