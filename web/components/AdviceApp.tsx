"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import AdviceResult from "./AdviceResult";
import AttributionFooter from "./AttributionFooter";
import FollowUps from "./FollowUps";
import LocationPicker, { type PickedPlace } from "./LocationPicker";
import MicButton from "./MicButton";
import SavedFields from "./SavedFields";
import ShareBar from "./ShareBar";
import SiteNav from "./SiteNav";
import { ApiError, postAdvice, REQUEST_TIMEOUT_MS, searchPlaces } from "@/lib/api";
import { fetchForecast, fetchPastRain, SOURCE_NAME, type BrowserForecast } from "@/lib/forecastClient";
import { fmtAge, fmtFetched, minutesSince } from "@/lib/format";
import { fill, I18N, type Labels } from "@/lib/i18n";
import { readAdviceLink } from "@/lib/links";
import {
  fieldId, loadFields, loadLastAnswer, loadSelectedField, MAX_FIELDS, placeKey, saveFields, saveLastAnswer,
  saveSelectedField, type LastAnswer, type SavedField,
} from "@/lib/storage";
import type { AdviceResponse, Lang } from "@/lib/types";
import * as speech from "@/lib/speech";

type LangChoice = "auto" | Lang;
type Phase = "idle" | "loading" | "done" | "error";
type Where = { name: string; lat?: number; lon?: number };

const LANGS: { value: LangChoice; label: (l: Labels) => string }[] = [
  { value: "auto", label: (l) => l.auto },
  { value: "en", label: () => "English" },
  { value: "hi", label: () => "हिन्दी" },
  { value: "kn", label: () => "ಕನ್ನಡ" },
];

const SLOW_AFTER_MS = 9_000;
const THINKING_AFTER_MS = 4_000;
const WAKE_AFTER_MS = 20_000;

const subscribeOnline = (cb: () => void) => {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => {
    window.removeEventListener("online", cb);
    window.removeEventListener("offline", cb);
  };
};
const subscribeNothing = () => () => {};

function storageWorks(): boolean {
  try {
    window.localStorage.setItem("yg.test", "1");
    window.localStorage.removeItem("yg.test");
    return true;
  } catch {
    return false;
  }
}

const isLang = (v: string | null): v is Lang => v === "en" || v === "hi" || v === "kn";

function keysFor(w: Where): string[] {
  const keys = [placeKey({ name: w.name })];
  if (w.lat != null && w.lon != null) keys.push(placeKey({ lat: w.lat, lon: w.lon }));
  return keys;
}

/** Which source the failed request depended on, for the last-known banner. */
function failedSourceName(err: ApiError, L: Labels): string {
  if (err.code === "geocoding_failed") return "Open-Meteo Geocoding API";
  if (err.kind === "network" || err.kind === "timeout") return L.serverName;
  return `YieldGuard server${err.status ? ` (HTTP ${err.status})` : ""}`;
}

export default function AdviceApp() {
  const [langChoice, setLangChoice] = useState<LangChoice>("auto");
  const [uiLang, setUiLang] = useState<Lang>("en");
  const L = I18N[uiLang];

  const [location, setLocation] = useState("Dharwad");
  const [coords, setCoords] = useState<PickedPlace | null>(null);
  const [question, setQuestion] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [statusKey, setStatusKey] = useState<keyof Labels | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AdviceResponse | null>(null);
  const [lastKnown, setLastKnown] = useState<{ entry: LastAnswer; failed: string[] } | null>(null);

  const [fields, setFields] = useState<SavedField[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const storageOk = useSyncExternalStore(subscribeNothing, storageWorks, () => true);

  const online = useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true);

  const resultRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const autoSubmit = useRef(false);
  const lastAsk = useRef<{ where: Where; q: string } | null>(null); // for "Refresh data"

  // ---- browser-only setup: saved fields, voice list, shareable links --------
  useEffect(() => {
    // The page is prerendered as static HTML; device storage and the query string are only
    // readable after hydration, so copying them into state once on mount is intended.
    const saved = loadFields();
    const sel = loadSelectedField();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFields(saved);
    const field = saved.find((f) => f.id === sel);
    if (field) {
      setSelectedId(field.id);
      setLocation(field.name);
      setCoords({ lat: field.lat, lon: field.lon, name: field.name });
    }

    // /advice/?location=Hubballi&q=Can+I+spray&lang=kn fills the form and asks; &lat=..&lon=.. keep coordinates.
    const link = readAdviceLink(window.location.search);
    if (link.lang) {
      setLangChoice(link.lang);
      setUiLang(link.lang);
    }
    if (link.location || link.coords) {
      const name = link.location ?? `${link.coords!.lat}, ${link.coords!.lon}`;
      setLocation(name);
      setCoords(link.coords ? { ...link.coords, name } : null);
      setSelectedId(null);
    }
    const q = link.question;
    if (q) {
      setQuestion(q);
      autoSubmit.current = true;
    }
  }, []);

  useEffect(() => {
    if (autoSubmit.current && question) {
      autoSubmit.current = false;
      formRef.current?.requestSubmit();
    }
  }, [question]);

  useEffect(() => {
    document.documentElement.lang = uiLang;
  }, [uiLang]);

  // Typing, picking a suggestion or "Use my location": a new place that is not a saved field.
  const onLocationChange = (value: string, picked: PickedPlace | null) => {
    setLocation(value);
    setSelectedId(null);
    setCoords(picked);
  };

  const onSpokenQuestion = (text: string, spoken: Lang | null) => {
    setQuestion(text);
    if (langChoice === "auto" && spoken) setUiLang(spoken);
  };

  const onLangChange = (v: LangChoice) => {
    setLangChoice(v);
    if (v !== "auto") setUiLang(v);
  };

  // ---- ask -----------------------------------------------------------------
  const ask = useCallback(
    async (where: Where, q: string) => {
      if (!q || !where.name || phase === "loading") return;
      speech.stop(); // a new question stops any answer being read aloud
      lastAsk.current = { where, q };

      setPhase("loading");
      setError(null);
      setLastKnown(null);
      setStatusKey("loading");
      const timers = [
        setTimeout(() => setStatusKey("thinking"), THINKING_AFTER_MS),
        setTimeout(() => setStatusKey("slow"), SLOW_AFTER_MS),
        setTimeout(() => setStatusKey("wakeUp"), WAKE_AFTER_MS),
      ];
      const ctrl = new AbortController();
      const abort = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
      const keys = keysFor(where);

      try {
        // The forecast is fetched here in the browser (one request per question, or the 10-minute copy), with the
        // month's past rain (once per place per day), then posted with the question. A typed place name is
        // looked up first, as the server would.
        let at: { lat: number; lon: number } | null =
          where.lat != null && where.lon != null ? { lat: where.lat, lon: where.lon } : null;
        if (!at) at = (await searchPlaces(where.name, ctrl.signal).catch(() => []))[0] ?? null;
        const notFound: BrowserForecast = { ok: false, status: null, error: "place not found in the browser", source: SOURCE_NAME };
        const [forecast, pastRain] = at
          ? await Promise.all([fetchForecast(at.lat, at.lon), fetchPastRain(at.lat, at.lon)])
          : [notFound, notFound];
        const body = {
          question: q, location: where.name, lat: where.lat, lon: where.lon, lang: langChoice, forecast, past_rain: pastRain,
        };
        const res = await postAdvice(body, ctrl.signal).catch((e: unknown) => {
          if (!(e instanceof ApiError && (e.code === "invalid_forecast" || e.code === "invalid_past_rain"))) throw e;
          // The server rejected what the browser fetched (e.g. the device clock is wrong): ask once more
          // without the rejected part. A rejected forecast means MET Norway is used. No second Open-Meteo call.
          const failed: BrowserForecast = { ok: false, status: null, error: `rejected: ${e.message}`.slice(0, 250), source: SOURCE_NAME };
          const retry = e.code === "invalid_forecast" ? { ...body, forecast: failed } : { ...body, past_rain: failed };
          return postAdvice(retry, ctrl.signal);
        });
        const allKeys = [...keys, placeKey({ lat: res.location.lat, lon: res.location.lon })];
        const failedNow = res.sources.filter((s) => s.status !== "ok");
        const prev = loadLastAnswer(allKeys);
        if (failedNow.length === 0 || !prev) {
          saveLastAnswer(allKeys, res); // complete answers always; a partial one only if nothing is saved yet
        }
        // Some sources failed: also show the last saved answer if it has data for any of them.
        const covers = prev && failedNow.some((f) => prev.res.sources.find((s) => s.id === f.id)?.status === "ok");
        if (failedNow.length > 0 && covers) setLastKnown({ entry: prev, failed: failedNow.map((f) => f.name) });
        setResult(res);
        if (langChoice === "auto" && isLang(res.language)) setUiLang(res.language);
        setPhase("done");
        requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
      } catch (err) {
        const ae = err instanceof ApiError ? err : new ApiError("network", "network");
        setError(ae.kind === "timeout" ? L.timeout : ae.kind === "network" ? L.network : ae.message);
        const prev = ae.code === "location_not_found" ? null : loadLastAnswer(keys);
        setLastKnown(prev ? { entry: prev, failed: [failedSourceName(ae, L)] } : null);
        setResult(null);
        setPhase("error");
      } finally {
        timers.forEach(clearTimeout);
        clearTimeout(abort);
        setStatusKey(null);
      }
    },
    [phase, langChoice, L],
  );

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const where: Where = coords ? { name: coords.name, lat: coords.lat, lon: coords.lon } : { name: location.trim() };
    void ask(where, question.trim());
  };

  // ---- saved fields ----------------------------------------------------------
  const selectField = (f: SavedField) => {
    setSelectedId(f.id);
    saveSelectedField(f.id);
    setLocation(f.name);
    setCoords({ lat: f.lat, lon: f.lon, name: f.name });
    if (question.trim()) void ask({ name: f.name, lat: f.lat, lon: f.lon }, question.trim());
  };

  const removeField = (f: SavedField) => {
    const next = fields.filter((x) => x.id !== f.id);
    setFields(next);
    saveFields(next);
    if (selectedId === f.id) {
      setSelectedId(null);
      saveSelectedField(null);
    }
  };

  const saveCurrent = () => {
    if (!result || fields.length >= MAX_FIELDS) return;
    const { lat, lon, name, district } = result.location;
    const id = fieldId(lat, lon);
    if (fields.some((f) => f.id === id)) {
      selectField(fields.find((f) => f.id === id)!);
      return;
    }
    const f: SavedField = { id, name: district ? `${name}, ${district}` : name, lat, lon };
    const next = [...fields, f];
    setFields(next);
    saveFields(next);
    setSelectedId(id);
    saveSelectedField(id);
  };

  const canSaveCurrent = !!result && !fields.some((f) => f.id === fieldId(result.location.lat, result.location.lon));

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <SiteNav current="/advice/" L={L} />
            <div>
              <h1 className="text-xl font-bold leading-tight">
                <span className="text-primary">YieldGuard</span> · {L.title}
              </h1>
              <p className="text-sm text-muted-foreground">{L.subtitle}</p>
            </div>
          </div>
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">{L.language}</span>
            <select
              value={langChoice}
              onChange={(e) => onLangChange(e.target.value as LangChoice)}
              className="min-h-11 rounded-md border border-border bg-background px-2"
            >
              {LANGS.map((o) => (
                <option key={o.value} value={o.value}>{o.label(L)}</option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {/* 12-column grid on desktop (form 4/12, answer 8/12; 3/9 on wide screens), one column on phones. */}
      <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-4 px-4 py-5 lg:grid-cols-12">
        <aside className="grid min-w-0 grid-cols-1 content-start gap-4 lg:col-span-4 xl:col-span-3">
          {!online && <div className="rounded-md border border-warning bg-warning-soft p-3">{L.offline}</div>}

          <form ref={formRef} onSubmit={submit} className="rounded-md border border-border bg-card p-4" autoComplete="off">
            <LocationPicker value={location} hasCoords={!!coords} onChange={onLocationChange} L={L} />

            <div className="mb-1.5 mt-4 flex flex-wrap items-start justify-between gap-2">
              <label htmlFor="question" className="pt-2 font-semibold">{L.question}</label>
              <MicButton lang={langChoice} L={L} onText={onSpokenQuestion} />
            </div>
            <textarea
              id="question"
              rows={3}
              maxLength={1000}
              required
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={L.questionPlaceholder}
              className="w-full min-w-0 resize-y rounded-md border border-border bg-background px-3 py-2.5"
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {L.examples.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setQuestion(ex)}
                  className="min-h-11 rounded-full border border-border px-3 text-left text-muted-foreground hover:border-primary hover:text-foreground"
                >
                  {ex}
                </button>
              ))}
            </div>

            <button
              type="submit"
              disabled={phase === "loading"}
              className="mt-4 min-h-12 w-full rounded-md bg-primary px-4 text-lg font-bold text-primary-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-progress disabled:opacity-60"
            >
              {phase === "loading" ? "…" : L.ask}
            </button>
            <p role="status" aria-live="polite" className="mt-2 min-h-6 text-muted-foreground">
              {statusKey ? (L[statusKey] as string) : ""}
            </p>
          </form>

          <SavedFields
            fields={fields}
            selectedId={selectedId}
            storageOk={storageOk}
            canSave={canSaveCurrent}
            onSelect={selectField}
            onRemove={removeField}
            onSaveCurrent={saveCurrent}
            L={L}
          />
        </aside>

        <section ref={resultRef} className="grid min-w-0 grid-cols-1 content-start gap-4 scroll-mt-4 lg:col-span-8 xl:col-span-9" aria-live="polite">
          {phase === "loading" && <LoadingCard label={statusKey ? (L[statusKey] as string) : L.loading} />}

          {phase === "error" && error && (
            <div role="alert" className="rounded-md border border-destructive bg-destructive-soft p-4">
              <p className="font-semibold text-destructive-text">{L.requestFailed}</p>
              <p className="mt-1">{error}</p>
            </div>
          )}

          {phase === "idle" && !result && (
            <div className="rounded-md border border-dashed border-border p-6 text-center">
              <p className="text-lg font-semibold">{L.emptyTitle}</p>
              <p className="mx-auto mt-2 max-w-xl text-muted-foreground">{L.emptyBody}</p>
            </div>
          )}

          {phase === "error" && lastKnown && (
            <LastKnown lk={lastKnown} L={L} />
          )}

          {result && phase === "done" && (
            <>
              {lastKnown && <LastKnown lk={lastKnown} L={L} />}
              <AdviceResult res={result} L={L} />
              {/* 8. Share buttons and the follow-up box, at the bottom */}
              <section aria-label={L.shareTitle} className="rounded-md border border-border bg-card p-4">
                <h2 className="text-lg font-bold">{L.shareTitle}</h2>
                <ShareBar res={result} L={L} />
              </section>
              <FollowUps
                key={result.request_id}
                res={result}
                L={L}
                lang={langChoice}
                onRefresh={() => lastAsk.current && void ask(lastAsk.current.where, lastAsk.current.q)}
              />
            </>
          )}
        </section>
      </main>

      <AttributionFooter note={L.footNote} />
    </div>
  );
}

/** The last complete answer saved on this device for the same place, labelled with its age. */
function LastKnown({ lk, L }: { lk: { entry: LastAnswer; failed: string[] }; L: Labels }) {
  const age = fmtAge(minutesSince(lk.entry.savedAt), L.ageUnits);
  return (
    <section aria-label={L.lastKnownTitle} className="rounded-md border-2 border-warning p-3">
      <div className="mb-3 rounded-md bg-warning-soft p-3">
        <p className="text-lg font-bold text-warning">
          {L.lastKnownTitle} · {fill(L.lastUpdated, { age })}
        </p>
        <p className="mt-1">
          {L.liveFailedNow} <b>{lk.failed.join(", ")}</b>
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {L.fetched} {fmtFetched(lk.entry.res.generated_at)} · {lk.entry.res.location.name}
        </p>
      </div>
      <details open>
        <summary className="min-h-11 cursor-pointer font-semibold">{L.showLastKnown}</summary>
        <div className="mt-3">
          <AdviceResult res={lk.entry.res} L={L} />
        </div>
      </details>
    </section>
  );
}

function LoadingCard({ label }: { label: string }) {
  return (
    <div className="grid gap-3" aria-hidden="true">
      <p className="text-muted-foreground">{label}</p>
      <div className="grid animate-pulse grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <div key={i} className="h-28 rounded-md bg-card" />)}
      </div>
      <div className="h-48 animate-pulse rounded-md bg-card" />
    </div>
  );
}
