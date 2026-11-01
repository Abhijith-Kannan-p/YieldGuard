// The Mandi page. Fixtures are real /api/mandi responses generated from the saved backend fixtures by
// backend/devtools/make_web_mandi_fixtures.py (data.gov.in snapshot of 1 Nov 2026), never written by hand.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AdviceApp from "@/components/AdviceApp";
import MandiView from "@/components/MandiView";
import SiteNav from "@/components/SiteNav";
import { fill, I18N } from "@/lib/i18n";
import { adviceLink, readAdviceLink } from "@/lib/links";
import type { Lang, MandiCropsResponse, MandiPageResponse } from "@/lib/types";
import crops from "./fixtures/mandi_crops.json";
import found from "./fixtures/mandi_found.json";
import latest from "./fixtures/mandi_latest.json";
import noData from "./fixtures/mandi_no_data.json";
import noNearby from "./fixtures/mandi_no_nearby.json";

const res = (x: unknown) => x as MandiPageResponse;
const render = (r: MandiPageResponse, lang: Lang = "en") =>
  renderToStaticMarkup(<MandiView res={r} lang={lang} L={I18N[lang]} />);
const unescape = (s: string) => s.replace(/&amp;/g, "&");

describe("price card", () => {
  const r = res(found);

  it("shows the nearest market's prices, reported today", () => {
    const html = render(r);
    const rec = r.records[0];
    expect(r.status).toBe("found");
    expect(html).toContain(r.market!.name);
    expect(html).toContain(r.market!.district);
    expect(html).toContain(fill(I18N.en.kmAway, { km: String(r.market!.distance_km) }));
    expect(html).toContain(`Rs ${rec.modal_price.toLocaleString("en-IN")}`);
    expect(html).toContain(fill(I18N.en.priceRange, { min: rec.min_price!.toLocaleString("en-IN"), max: rec.max_price!.toLocaleString("en-IN") }));
    expect(html).toContain(`data-date-status="found"`);
    expect(html).toContain(fill(I18N.en.reportedToday, { date: "1 Nov" }));
  });

  it("uses the crop's name in Hindi and Kannada", () => {
    expect(render(r, "hi")).toContain(r.labels.hi);
    expect(render(r, "kn")).toContain(r.labels.kn);
    expect(r.labels).toEqual({ en: "Maize", hi: "मक्का", kn: "ಮೆಕ್ಕೆಜೋಳ" });
  });

  it("always says these are reported prices, not a forecast", () => {
    for (const x of [found, latest, noNearby, noData]) {
      for (const lang of ["en", "hi", "kn"] as Lang[]) expect(render(res(x), lang)).toContain(I18N[lang].notForecast);
    }
  });

  it("labels the source with its status and fetch time", () => {
    const html = render(r);
    expect(html).toContain(r.source.name);
    expect(html).toContain(`data-source-status="live"`);
    expect(html).toContain(I18N.en.fetched);
  });

  it("says when no other market nearby reports the crop", () => {
    expect(r.nearby).toEqual([]);
    expect(render(r)).toContain(fill(I18N.en.nearbyNone, { km: "125" }));
  });
});

describe("older arrival date", () => {
  it("says latest available, never today", () => {
    const r = res(latest);
    expect(r.status).toBe("latest");
    for (const lang of ["en", "hi", "kn"] as Lang[]) {
      const html = render(r, lang);
      expect(html).toContain(`data-date-status="latest"`);
      expect(html).toContain(fill(I18N[lang].latestAvailable, { date: "1 Nov" }));
      expect(html).not.toContain(fill(I18N[lang].reportedToday, { date: "1 Nov" }));
    }
  });
});

describe("explicit empty states", () => {
  it("no market within the limit: names the far one, shows no price", () => {
    const r = res(noNearby);
    const html = render(r);
    expect(html).toContain(`data-status="no_nearby_market"`);
    expect(html).toContain(fill(I18N.en.mandiNoNearby, { km: "125" }));
    expect(html).toContain(r.nearest_beyond!.market);
    expect(html).not.toContain("data-modal-price");
    expect(html).not.toContain("data-ask-link");
  });

  it("no data from data.gov.in", () => {
    const html = render(res(noData), "kn");
    expect(html).toContain(`data-status="no_data"`);
    expect(html).toContain(I18N.kn.mandiNoData);
    expect(html).not.toContain("data-modal-price");
  });
});

describe("ask about this price", () => {
  it("opens the advice page with the question, place, language and coordinates", () => {
    const r = res(found);
    const html = render(r, "kn");
    const href = unescape(/data-ask-link="[^"]*" href="([^"]+)"/.exec(html)![1]);
    expect(href).toBe(adviceLink({
      question: fill(I18N.kn.askPriceQuestion, { crop: r.labels.kn }), location: r.location.name, lang: "kn",
      lat: r.location.lat, lon: r.location.lon,
    }));
    const back = readAdviceLink(href.slice(href.indexOf("?")));
    expect(back).toEqual({
      location: r.location.name, question: fill(I18N.kn.askPriceQuestion, { crop: "ಮೆಕ್ಕೆಜೋಳ" }), lang: "kn",
      coords: { lat: r.location.lat, lon: r.location.lon },
    });
  });

  it("links with only location= still work, and bad coordinates are ignored", () => {
    expect(readAdviceLink("?location=Hubballi&q=Can+I+spray&lang=kn")).toEqual({
      location: "Hubballi", question: "Can I spray", lang: "kn", coords: null,
    });
    expect(readAdviceLink("?location=Hubballi&lat=abc&lon=75").coords).toBeNull();
    expect(readAdviceLink("?location=Hubballi&lat=95&lon=75").coords).toBeNull();
    expect(readAdviceLink("?question=Will+it+rain&lang=xx")).toMatchObject({ question: "Will it rain", lang: null });
    expect(adviceLink({ question: "q", location: "Dharwad", lang: "en" })).toBe("/advice/?location=Dharwad&q=q&lang=en");
  });
});

describe("crop picker data", () => {
  it("comes from the snapshot, with alias names and the API name otherwise", () => {
    const c = crops as unknown as MandiCropsResponse;
    expect(c.status).toBe("ok");
    const by = Object.fromEntries(c.crops.map((x) => [x.commodity, x]));
    expect(by["Jowar(Sorghum)"].labels).toEqual({ en: "Jowar(Sorghum)", hi: "ज्वार", kn: "ಜೋಳ" });
    expect(by["Beans"].labels).toEqual({ en: "Beans", hi: "Beans", kn: "Beans" });
  });
});

describe("navigation", () => {
  it("marks the current page", () => {
    const html = renderToStaticMarkup(<SiteNav current="/mandi/" L={I18N.hi} />);
    const current = [...html.matchAll(/<a aria-current="page"[^>]*href="([^"]+)"/g)].map((m) => m[1]);
    expect(current).toEqual(["/mandi"]); // Link drops the trailing slash when rendered outside the app
    expect(html).toContain(I18N.hi.navAdvice);
  });
});

describe("advice page after the location picker moved", () => {
  it("renders the same location input and button", () => {
    const html = renderToStaticMarkup(<AdviceApp />);
    expect(html).toMatch(/<input id="location" list="location-places" required="" maxLength="80"[^>]*value="Dharwad"/);
    expect(html).toContain(`aria-label="${I18N.en.useLocation}"`);
    expect(html).toContain(`<label for="location"`);
    expect(html).toMatch(/<a aria-current="page"[^>]*href="\/advice"/);
  });
});
