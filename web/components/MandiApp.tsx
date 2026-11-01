"use client";

import { useEffect, useState } from "react";
import AttributionFooter from "./AttributionFooter";
import LocationPicker, { type PickedPlace } from "./LocationPicker";
import MandiView, { SourceLine } from "./MandiView";
import SiteNav from "./SiteNav";
import { ApiError, fetchMandi, fetchMandiCrops, REQUEST_TIMEOUT_MS } from "@/lib/api";
import { I18N } from "@/lib/i18n";
import { loadFields, loadSelectedField, type SavedField } from "@/lib/storage";
import type { Lang, MandiCropsResponse, MandiPageResponse } from "@/lib/types";

const LANGS: { value: Lang; label: string }[] = [
  { value: "en", label: "English" },
  { value: "hi", label: "हिन्दी" },
  { value: "kn", label: "ಕನ್ನಡ" },
];

type Crops = { s: "loading" } | { s: "ok"; d: MandiCropsResponse } | { s: "error"; msg: string };
type Prices = { s: "idle" } | { s: "loading" } | { s: "ok"; d: MandiPageResponse } | { s: "error"; msg: string };

/** Mandi prices without asking a question: place + crop -> nearest reporting market and the others nearby. */
export default function MandiApp() {
  const [lang, setLang] = useState<Lang>("en");
  const L = I18N[lang];
  const [location, setLocation] = useState("Dharwad");
  const [coords, setCoords] = useState<PickedPlace | null>(null);
  const [fields, setFields] = useState<SavedField[]>([]);
  const [crop, setCrop] = useState("");
  const [crops, setCrops] = useState<Crops>({ s: "loading" });
  const [prices, setPrices] = useState<Prices>({ s: "idle" });

  useEffect(() => {
    // Saved fields are only readable after hydration (the page is prerendered as static HTML).
    const saved = loadFields();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFields(saved);
    const field = saved.find((f) => f.id === loadSelectedField());
    if (field) {
      setLocation(field.name);
      setCoords({ lat: field.lat, lon: field.lon, name: field.name });
    }
    const ctrl = new AbortController();
    fetchMandiCrops(ctrl.signal)
      .then((d) => setCrops({ s: "ok", d }))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setCrops({ s: "error", msg: e instanceof ApiError && e.kind === "server" ? e.message : "" });
      });
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const onLocationChange = (value: string, picked: PickedPlace | null) => {
    setLocation(value);
    setCoords(picked);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!crop || !location.trim()) return;
    setPrices({ s: "loading" });
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
    try {
      const where = coords ? { lat: coords.lat, lon: coords.lon, location: coords.name } : { location: location.trim() };
      setPrices({ s: "ok", d: await fetchMandi(where, crop, ctrl.signal) });
    } catch (err) {
      const ae = err instanceof ApiError ? err : new ApiError("network", "network");
      setPrices({ s: "error", msg: ae.kind === "timeout" ? L.timeout : ae.kind === "network" ? L.network : ae.message });
    } finally {
      clearTimeout(timer);
    }
  };

  const list = crops.s === "ok" ? crops.d.crops : [];
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <SiteNav current="/mandi/" L={L} />
            <div>
              <h1 className="text-xl font-bold leading-tight">
                <span className="text-primary">YieldGuard</span> · {L.mandiTitle}
              </h1>
              <p className="text-sm text-muted-foreground">{L.mandiSubtitle}</p>
            </div>
          </div>
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">{L.language}</span>
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value as Lang)}
              className="min-h-11 rounded-md border border-border bg-background px-2"
            >
              {LANGS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-4 px-4 py-5 lg:grid-cols-12">
        <aside className="grid min-w-0 content-start gap-4 lg:col-span-4 xl:col-span-3">
          <form onSubmit={submit} className="rounded-md border border-border bg-card p-4" autoComplete="off">
            <LocationPicker id="mandi-location" value={location} hasCoords={!!coords} onChange={onLocationChange} L={L} />
            {fields.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {fields.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => onLocationChange(f.name, { lat: f.lat, lon: f.lon, name: f.name })}
                    className="min-h-11 rounded-full border border-border px-3 text-muted-foreground hover:border-primary hover:text-foreground"
                  >
                    {f.name}
                  </button>
                ))}
              </div>
            )}

            <label htmlFor="mandi-crop" className="mb-1.5 mt-4 block font-semibold">{L.crop}</label>
            <select
              id="mandi-crop"
              required
              value={crop}
              disabled={list.length === 0}
              onChange={(e) => setCrop(e.target.value)}
              className="min-h-11 w-full min-w-0 rounded-md border border-border bg-background px-2"
            >
              <option value="">{L.cropChoose}</option>
              {list.map((c) => <option key={c.commodity} value={c.commodity}>{c.labels[lang]}</option>)}
            </select>
            {crops.s === "loading" && <p className="mt-1 text-sm text-muted-foreground">{L.cropsLoading}</p>}
            {crops.s === "error" && (
              <p role="alert" className="mt-1 text-sm text-destructive-text">{L.cropsUnavailable} {crops.msg}</p>
            )}
            {crops.s === "ok" && crops.d.status !== "ok" && (
              <p role="status" data-crops-status={crops.d.status} className="mt-1 text-sm text-warning">
                {crops.d.status === "no_data" ? L.cropsNone : L.cropsUnavailable}
              </p>
            )}

            <button
              type="submit"
              disabled={prices.s === "loading" || !crop}
              className="mt-4 min-h-12 w-full rounded-md bg-primary px-4 text-lg font-bold text-primary-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              {prices.s === "loading" ? "…" : L.showPrices}
            </button>
          </form>
          {crops.s === "ok" && <SourceLine s={crops.d.source} L={L} />}
        </aside>

        <section className="grid min-w-0 content-start gap-4 lg:col-span-8 xl:col-span-9" aria-live="polite">
          {prices.s === "idle" && (
            <div className="rounded-md border border-dashed border-border p-6 text-center">
              <p className="text-lg font-semibold">{L.mandiPickCrop}</p>
              <p className="mx-auto mt-2 max-w-xl text-muted-foreground">{L.notForecast}</p>
            </div>
          )}
          {prices.s === "loading" && <div className="h-48 animate-pulse rounded-md bg-card" aria-hidden="true" />}
          {prices.s === "error" && (
            <div role="alert" className="rounded-md border border-destructive bg-destructive-soft p-4">
              <p className="font-semibold text-destructive-text">{L.mandiRequestFailed}</p>
              <p className="mt-1">{prices.msg}</p>
            </div>
          )}
          {prices.s === "ok" && <MandiView res={prices.d} lang={lang} L={L} />}
        </section>
      </main>

      <AttributionFooter note={crops.s === "ok" ? crops.d.attribution : undefined} />
    </div>
  );
}
