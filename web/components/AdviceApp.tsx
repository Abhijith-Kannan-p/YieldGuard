"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import ForecastChart from "./ForecastChart";
import MicButton from "./MicButton";
import { PinIcon, SpeakerIcon } from "./Icons";
import AttributionFooter from "./AttributionFooter";
import { ApiError, fetchAdvice, REQUEST_TIMEOUT_MS, searchPlaces } from "@/lib/api";
import { dataDate, fmtAge, fmtFetched, fmtSpan, fmtValue } from "@/lib/format";
import { I18N, type Labels } from "@/lib/i18n";
import type { AdviceResponse, CitedItem, DataPoint, Lang, PlaceSuggestion, Rule, SourceView } from "@/lib/types";
import * as voice from "@/lib/voice";

type LangChoice = "auto" | Lang;
type Phase = "idle" | "loading" | "done" | "error";

const LANGS: { value: LangChoice; label: (l: Labels) => string }[] = [
  { value: "auto", label: (l) => l.auto },
  { value: "en", label: () => "English" },
  { value: "hi", label: () => "हिन्दी" },
  { value: "kn", label: () => "ಕನ್ನಡ" },
];

// Rule statuses shown as amber warnings (drought, waterlogging, heavy rain, soil flags).
const WARN_STATUSES = new Set(["warning", "drought_risk", "waterlogging_risk", "flags"]);
const GOOD_STATUSES = new Set(["found", "ok", "normal"]);

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

const isLang = (v: string | null): v is Lang => v === "en" || v === "hi" || v === "kn";

export default function AdviceApp() {
  const [langChoice, setLangChoice] = useState<LangChoice>("auto");
  const [uiLang, setUiLang] = useState<Lang>("en");
  const L = I18N[uiLang];

  const [location, setLocation] = useState("Dharwad");
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [coords, setCoords] = useState<{ lat: number; lon: number; name: string } | null>(null);
  const [locHint, setLocHint] = useState("");
  const [question, setQuestion] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [statusKey, setStatusKey] = useState<keyof Labels | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AdviceResponse | null>(null);

  const online = useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true);
  const [, setVoicesTick] = useState(0);

  const resultRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const autoSubmit = useRef(false);

  const labelFor = (p: PlaceSuggestion) => (p.district ? `${p.name} (${p.district})` : p.name);

  // ---- browser-only setup: voice list, shareable links ---------------------
  useEffect(() => {
    const off = voice.onVoicesReady(() => setVoicesTick((n) => n + 1));

    // /advice/?location=Hubballi&q=Can+I+spray&lang=kn fills the form and asks.
    // The page is prerendered as static HTML, so the query string is only known after
    // hydration; copying it into state once on mount is intended.
    const qs = new URLSearchParams(window.location.search);
    const lang = qs.get("lang");
    if (isLang(lang)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLangChoice(lang);
      setUiLang(lang);
    }
    if (qs.get("location")) setLocation(qs.get("location")!);
    const q = qs.get("q") || qs.get("question");
    if (q) {
      setQuestion(q);
      autoSubmit.current = true;
    }
    return off;
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

  // ---- location suggestions (debounced, optional) -------------------------
  useEffect(() => {
    const q = location.trim();
    if (q.length < 2 || coords) return;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      searchPlaces(q, ctrl.signal)
        .then((r) => setSuggestions(r.slice(0, 8)))
        .catch(() => {}); // suggestions are a convenience; the main request reports real errors
    }, 350);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [location, coords]);

  const onLocationChange = (value: string) => {
    setLocation(value);
    const picked = suggestions.find((p) => labelFor(p) === value);
    setCoords(picked ? { lat: picked.lat, lon: picked.lon, name: picked.name } : null);
    setLocHint(picked ? `${picked.lat.toFixed(3)}, ${picked.lon.toFixed(3)}` : "");
  };

  const useMyLocation = () => {
    if (!navigator.geolocation) return;
    setLocHint("…");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = Number(pos.coords.latitude.toFixed(4));
        const lon = Number(pos.coords.longitude.toFixed(4));
        setCoords({ lat, lon, name: "My location" });
        setLocation(`My location (${lat}, ${lon})`);
        setLocHint("");
      },
      () => setLocHint(L.locDenied),
      { timeout: 10_000 },
    );
  };

  const onSpokenQuestion = (text: string, spoken: Lang | null) => {
    setQuestion(text);
    if (langChoice === "auto" && spoken) setUiLang(spoken);
  };

  const onLangChange = (v: LangChoice) => {
    setLangChoice(v);
    if (v !== "auto") setUiLang(v);
  };

  // ---- submit ------------------------------------------------------------
  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const q = question.trim();
      const loc = location.trim();
      if (!q || !loc || phase === "loading") return;

      const params = new URLSearchParams({ q, lang: langChoice });
      if (coords) {
        params.set("lat", String(coords.lat));
        params.set("lon", String(coords.lon));
        params.set("location", coords.name);
      } else {
        params.set("location", loc);
      }

      setPhase("loading");
      setError(null);
      setStatusKey("loading");
      const timers = [
        setTimeout(() => setStatusKey("thinking"), THINKING_AFTER_MS),
        setTimeout(() => setStatusKey("slow"), SLOW_AFTER_MS),
        setTimeout(() => setStatusKey("wakeUp"), WAKE_AFTER_MS),
      ];
      const ctrl = new AbortController();
      const abort = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);

      try {
        const res = await fetchAdvice(params, ctrl.signal);
        setResult(res);
        if (langChoice === "auto" && isLang(res.language)) setUiLang(res.language);
        setPhase("done");
        requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
      } catch (err) {
        const ae = err instanceof ApiError ? err : new ApiError("network", "network");
        setError(ae.kind === "timeout" ? L.timeout : ae.kind === "network" ? L.network : ae.message);
        setPhase("error");
      } finally {
        timers.forEach(clearTimeout);
        clearTimeout(abort);
        setStatusKey(null);
      }
    },
    [question, location, coords, langChoice, phase, L],
  );

  const speakAnswer = () => {
    if (!result) return;
    const a = result.answer;
    voice.speak([a.text, ...a.recommendations.map((r) => r.text), a.disclaimer].join(" "), result.language);
  };

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex w-full max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-sm text-muted hover:text-foreground">
              ← {L.back}
            </Link>
            <div>
              <h1 className="text-lg font-bold leading-tight">
                <span className="text-primary">YieldGuard</span> · {L.title}
              </h1>
              <p className="text-xs text-muted">{L.subtitle}</p>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted">{L.language}</span>
            <select
              value={langChoice}
              onChange={(e) => onLangChange(e.target.value as LangChoice)}
              className="rounded-md border border-border bg-background px-2 py-1.5"
            >
              {LANGS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label(L)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-5">
        {!online && <Banner tone="amber">{L.offline}</Banner>}

        <form ref={formRef} onSubmit={submit} className="mb-5 rounded-md border border-border bg-card p-4" autoComplete="off">
          <div className="mb-4">
            <label htmlFor="location" className="mb-1.5 block font-semibold">
              {L.location}
            </label>
            <div className="flex gap-2">
              <input
                id="location"
                list="places"
                value={location}
                onChange={(e) => onLocationChange(e.target.value)}
                required
                maxLength={80}
                className="w-full min-w-0 rounded-md border border-border bg-background px-3 py-2.5"
              />
              <button
                type="button"
                onClick={useMyLocation}
                title={L.useLocation}
                aria-label={L.useLocation}
                className="min-w-11 rounded-md border border-border bg-background px-3 text-muted hover:border-primary hover:text-primary"
              >
                <PinIcon />
              </button>
            </div>
            <datalist id="places">
              {suggestions.map((p) => (
                <option key={`${p.lat},${p.lon}`} value={labelFor(p)} />
              ))}
            </datalist>
            {locHint && <small className="mt-1 block text-muted">{locHint}</small>}
          </div>

          <div className="mb-4">
            <div className="mb-1.5 flex flex-wrap items-start justify-between gap-2">
              <label htmlFor="question" className="pt-1.5 font-semibold">
                {L.question}
              </label>
              <MicButton lang={langChoice} L={L} onText={onSpokenQuestion} />
            </div>
            <div className="flex gap-2">
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
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {L.examples.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setQuestion(ex)}
                  className="rounded-full border border-border px-3 py-1 text-sm text-muted hover:border-primary hover:text-foreground"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>

          <button
            type="submit"
            disabled={phase === "loading"}
            className="w-full rounded-md bg-primary px-4 py-3 text-base font-bold text-primary-foreground transition hover:brightness-110 disabled:cursor-progress disabled:opacity-60"
          >
            {phase === "loading" ? "…" : L.ask}
          </button>
          <p role="status" aria-live="polite" className="mt-2 min-h-6 text-sm text-muted">
            {statusKey ? (L[statusKey] as string) : ""}
          </p>
        </form>

        {phase === "loading" && <LoadingCard label={statusKey ? (L[statusKey] as string) : L.loading} />}

        {phase === "error" && error && (
          <div role="alert" className="mb-5 rounded-md border border-destructive bg-destructive-soft p-4">
            <p className="font-semibold text-destructive">{L.requestFailed}</p>
            <p className="mt-1">{error}</p>
          </div>
        )}

        {phase === "idle" && !result && (
          <div className="rounded-md border border-dashed border-border p-6 text-center">
            <p className="font-semibold">{L.emptyTitle}</p>
            <p className="mx-auto mt-2 max-w-xl text-sm text-muted">{L.emptyBody}</p>
          </div>
        )}

        {result && phase !== "loading" && (
          <div ref={resultRef} className="scroll-mt-4">
            <Result res={result} L={L} onSpeak={voice.canSpeak(result.language) ? speakAnswer : undefined} />
          </div>
        )}
      </main>

      <AttributionFooter note={L.footNote} />
    </div>
  );
}

// ---------------------------------------------------------------------------

function Result({ res, L, onSpeak }: { res: AdviceResponse; L: Labels; onSpeak?: () => void }) {
  const points = useMemo(() => new Map(res.data_points.map((p) => [p.id, p])), [res.data_points]);
  const failed = res.sources.filter((s) => s.status !== "ok");
  const stale = res.sources.filter((s) => s.status === "ok" && s.stale);
  const alerts = res.rules.filter((r) => WARN_STATUSES.has(r.status));
  const spray = res.rules.find((r) => r.id === "spray_window");
  const loc = res.location;

  return (
    <>
      {failed.map((s) => (
        <SourceFailure key={s.id} s={s} L={L} />
      ))}
      {stale.map((s) => (
        <div key={s.id} role="status" className="mb-3 rounded-md border border-amber bg-amber-soft p-3 text-sm">
          <p>
            <b className="text-amber">
              {s.name}: {L.staleTitle}
            </b>
            {s.error ? ` (${s.error})` : ""}
          </p>
          <p className="mt-0.5">
            {L.staleBody} {fmtFetched(s.fetched_at)}.
          </p>
        </div>
      ))}

      {alerts.length > 0 && (
        <section aria-label={L.alerts} className="mb-5 space-y-2">
          {alerts.map((r) => (
            <div key={r.id} className="rounded-md border border-amber bg-amber-soft p-3">
              <p className="font-semibold text-amber">
                ⚠ {L.rule[r.id] ?? r.name} · {L.status[r.status] ?? r.status}
              </p>
              <p className="mt-1 text-sm">{r.summary}</p>
              <Cites ids={r.evidence} points={points} L={L} />
            </div>
          ))}
        </section>
      )}

      <article className="mb-5 rounded-md border border-border bg-card p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-xl font-bold">{L.answer}</h2>
          {onSpeak && (
            <button
              type="button"
              onClick={onSpeak}
              className="inline-flex items-center gap-2 rounded-md border border-primary/60 px-3 py-1.5 text-sm font-semibold text-primary hover:bg-primary/10"
            >
              <SpeakerIcon />
              <span>{L.listen}</span>
            </button>
          )}
        </div>
        <p className="mt-1 text-sm text-muted">
          {loc.name}
          {loc.district ? `, ${loc.district}` : ""} · {loc.lat.toFixed(3)}, {loc.lon.toFixed(3)} · {loc.source}
          {loc.fetched_at ? ` · ${L.fetched} ${fmtFetched(loc.fetched_at)}` : ""}
        </p>
        <p className="mt-3 text-lg leading-relaxed">{res.answer.text}</p>

        {res.answer.recommendations.length > 0 && (
          <>
            <h3 className="mt-5 font-semibold">{L.recommendations}</h3>
            <ol className="mt-2 list-decimal space-y-3 pl-5">
              {res.answer.recommendations.map((r, i) => (
                <CitedLi key={i} item={r} points={points} L={L} />
              ))}
            </ol>
          </>
        )}

        <details open className="mt-5 rounded-md border border-border bg-background/40 p-3">
          <summary className="cursor-pointer font-semibold">{L.why}</summary>
          {res.answer.why.length > 0 && (
            <ul className="mt-2 list-disc space-y-3 pl-5">
              {res.answer.why.map((r, i) => (
                <CitedLi key={i} item={r} points={points} L={L} />
              ))}
            </ul>
          )}
          <h4 className="mt-4 text-sm font-semibold text-muted">{L.whyRules}</h4>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {res.rules.map((r) => (
              <RuleCard key={r.id} r={r} points={points} L={L} />
            ))}
          </div>
        </details>

        {res.answer.missing_data.length > 0 && (
          <p className="mt-4 text-sm text-muted">
            {L.missing} {res.answer.missing_data.join("; ")}
          </p>
        )}
        {res.unverified_numbers.length > 0 && (
          <p className="mt-3 rounded-md border border-amber bg-amber-soft p-2 text-sm">
            {L.unverified} {res.unverified_numbers.join(", ")}
          </p>
        )}
        {res.data_age && res.data_age.length > 0 && (
          <div className="mt-4 text-sm">
            <p className="font-semibold text-muted">{L.dataAge}</p>
            <ul className="mt-1 space-y-0.5">
              {res.data_age.map((d) => (
                <li key={d.source} className={d.stale ? "text-amber" : "text-muted"}>
                  {d.source}: {L.fetched} {fmtFetched(d.fetched_at)} ({fmtAge(d.age_minutes, L.ageUnits)}
                  {" · "}
                  {d.stale ? L.staleTag : d.cached ? L.cached : L.live})
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="mt-4 rounded-md border border-primary/40 bg-primary/10 p-3 font-semibold">{res.answer.disclaimer}</p>
        <p className="mt-3 text-xs text-muted">
          {L.generatedBy}: {res.generated_by === "rules-fallback" ? L.fallbackNote : res.generated_by} ·{" "}
          {fmtFetched(res.generated_at)} · {res.elapsed_ms} ms · id {res.request_id}
        </p>
      </article>

      {res.forecast_hourly && res.forecast_hourly.hours.length > 0 && (
        <article className="mb-5 rounded-md border border-border bg-card p-4">
          <h2 className="font-bold">{L.forecast}</h2>
          <p className="mt-1 text-sm text-muted">{L.chartHelp}</p>
          <div className="mt-3 overflow-x-auto">
            <ForecastChart
              hours={res.forecast_hourly.hours}
              windows={res.spray_windows}
              maxWind={spray?.thresholds.max_wind_kmh as number | undefined}
              maxRainProb={spray?.thresholds.max_precip_prob_pct as number | undefined}
            />
          </div>
          <p className="mt-2 text-xs text-muted">
            {res.forecast_hourly.source} · {fmtSpan(res.forecast_hourly.hours[0].time)} –{" "}
            {fmtSpan(res.forecast_hourly.hours[res.forecast_hourly.hours.length - 1].time)} · {L.fetched}{" "}
            {fmtFetched(res.forecast_hourly.fetched_at)}
          </p>
        </article>
      )}

      <article className="mb-5 rounded-md border border-border bg-card p-4">
        <h2 className="font-bold">{L.data}</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-muted">
                {[L.colItem, L.colValue, L.colFor, L.colSource, L.colFetched].map((h) => (
                  <th key={h} className="whitespace-nowrap border-b border-border px-2 py-1.5 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {res.data_points.map((p) => (
                <tr key={p.id} className="align-top">
                  <td className="border-b border-border px-2 py-1.5">{p.label}</td>
                  <td className="border-b border-border px-2 py-1.5 font-semibold tabular-nums">{fmtValue(p)}</td>
                  <td className="border-b border-border px-2 py-1.5">{dataDate(p, L)}</td>
                  <td className="border-b border-border px-2 py-1.5">{p.source}</td>
                  <td className="border-b border-border px-2 py-1.5 whitespace-nowrap">
                    {fmtFetched(p.fetched_at)}
                    {p.cached ? ` (${L.cached})` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>

      <article className="mb-5 rounded-md border border-border bg-card p-4">
        <h2 className="font-bold">{L.sources}</h2>
        <ul className="mt-2 divide-y divide-border">
          {res.sources.map((s) => (
            <li key={s.id} className="py-2 text-sm">
              <span
                className={`mr-2 inline-block h-2.5 w-2.5 rounded-full ${
                  s.status !== "ok" ? "bg-destructive" : s.stale ? "bg-amber" : "bg-primary"
                }`}
                aria-hidden="true"
              />
              <b>{s.name}</b>
              {s.status === "ok" ? (
                <span className="text-muted">
                  {" "}
                  · {L.fetched} {fmtFetched(s.fetched_at)}
                  {s.stale ? ` (${L.staleTag})` : s.cached ? ` (${L.cached})` : ""}
                  {s.stale && s.error && <span className="text-amber"> · {s.error}</span>}
                </span>
              ) : (
                <span className="text-destructive">
                  {" "}
                  · {L.failed}: {s.error}
                </span>
              )}
              {s.attribution && <div className="mt-0.5 text-xs text-muted">{s.attribution}</div>}
            </li>
          ))}
        </ul>
      </article>
    </>
  );
}

function SourceFailure({ s, L }: { s: SourceView; L: Labels }) {
  const part =
    s.id === "forecast"
      ? L.partForecast
      : s.id === "rain_mtd" || s.id === "rain_baseline"
        ? L.partRain
        : s.id === "soil"
          ? L.partSoil
          : L.partGeo;
  return (
    <div role="alert" className="mb-3 rounded-md border border-destructive bg-destructive-soft p-3 text-sm">
      <p>
        <b className="text-destructive">
          {s.name} {L.sourceDown}
        </b>
        {s.error ? ` (${s.error})` : ""}
      </p>
      <p className="mt-0.5">
        {L.missingParts} {part}
      </p>
    </div>
  );
}

function RuleCard({ r, points, L }: { r: Rule; points: Map<string, DataPoint>; L: Labels }) {
  const tone = WARN_STATUSES.has(r.status)
    ? "border-l-amber"
    : GOOD_STATUSES.has(r.status)
      ? "border-l-primary"
      : "border-l-muted";
  const pill = WARN_STATUSES.has(r.status)
    ? "bg-amber-soft text-amber"
    : GOOD_STATUSES.has(r.status)
      ? "bg-primary/15 text-primary"
      : "bg-border text-muted";
  return (
    <div className={`rounded-md border border-border border-l-4 ${tone} bg-card p-3`}>
      <div className="flex items-start justify-between gap-2">
        <h5 className="text-sm font-semibold">{L.rule[r.id] ?? r.name}</h5>
        <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-bold ${pill}`}>
          {L.status[r.status] ?? r.status.replace(/_/g, " ")}
        </span>
      </div>
      <p className="mt-1 text-sm">{r.summary}</p>
      <Cites ids={r.evidence} points={points} L={L} />
    </div>
  );
}

function CitedLi({ item, points, L }: { item: CitedItem; points: Map<string, DataPoint>; L: Labels }) {
  return (
    <li>
      <div>{item.text}</div>
      {item.evidence.length ? (
        <Cites ids={item.evidence} points={points} L={L} />
      ) : (
        <div className="mt-1 text-xs text-amber">{L.noCite}</div>
      )}
    </li>
  );
}

/** Citation chips: value, data date, source and fetch time for each data point. */
function Cites({ ids, points, L }: { ids: string[]; points: Map<string, DataPoint>; L: Labels }) {
  const list = ids.map((id) => points.get(id)).filter((p): p is DataPoint => !!p);
  if (!list.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {list.map((p) => (
        <span key={p.id} className="rounded border border-border bg-background px-1.5 py-0.5 text-xs text-muted">
          <b className="font-semibold text-foreground">
            {p.label}: {fmtValue(p)}
          </b>{" "}
          · {dataDate(p, L)} · {p.source} · {L.fetched} {fmtFetched(p.fetched_at)}
        </span>
      ))}
    </div>
  );
}

function Banner({ tone, children }: { tone: "amber"; children: React.ReactNode }) {
  return (
    <div className={`mb-4 rounded-md border p-3 text-sm ${tone === "amber" ? "border-amber bg-amber-soft" : ""}`}>
      {children}
    </div>
  );
}

function LoadingCard({ label }: { label: string }) {
  return (
    <div className="mb-5 animate-pulse rounded-md border border-border bg-card p-4" aria-hidden="true">
      <p className="text-sm text-muted">{label}</p>
      <div className="mt-3 h-4 w-3/4 rounded bg-border" />
      <div className="mt-2 h-4 w-2/3 rounded bg-border" />
      <div className="mt-2 h-4 w-1/2 rounded bg-border" />
    </div>
  );
}
