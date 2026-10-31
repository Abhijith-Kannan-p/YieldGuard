// The fixed sections of an answer, top to bottom: summary bar, now row, alerts, advice,
// why table, data and sources. (The 72-hour strip lives in HourStrip.tsx.)
import { SpeakerIcon } from "./Icons";
import { IrrigationTable } from "./FieldPlanner";
import { dataDate, fmtAge, fmtFetched, fmtSpan, fmtValue } from "@/lib/format";
import type { Labels } from "@/lib/i18n";
import type { AdviceResponse, CitedItem, DataPoint, Rule, SourceView } from "@/lib/types";

// Amber: drought, waterlogging, heat, heavy rain, fertiliser delay, soil flags.
export const WARN_STATUSES = new Set(["warning", "drought_risk", "waterlogging_risk", "flags", "delay"]);
const GOOD_STATUSES = new Set(["found", "ok", "normal", "irrigate"]);

const SECTION = "rounded-md border border-border bg-card p-4 lg:col-span-12";

/** First sentence of the answer, for the summary bar. */
export function firstSentence(text: string): string {
  const m = text.match(/^.*?[.!?।](\s|$)/u);
  return (m ? m[0] : text).trim();
}

/** Splits the answer into short sentences, one per line. */
export function sentences(text: string): string[] {
  // Split only where the punctuation is followed by a space, so "15.1 km/h" stays whole.
  return text.split(/(?<=[.!?।])\s+/u).map((s) => s.trim()).filter(Boolean);
}

export function overallStatus(res: AdviceResponse): "ok" | "warning" | "missing" {
  if (res.sources.some((s) => s.status !== "ok")) return "missing";
  if (res.rules.some((r) => WARN_STATUSES.has(r.status)) || res.sources.some((s) => s.stale || s.fallback_for))
    return "warning";
  return "ok";
}

// ---- 1. Summary bar ---------------------------------------------------------
export function SummaryBar({ res, L }: { res: AdviceResponse; L: Labels }) {
  const status = overallStatus(res);
  const badge = {
    ok: ["bg-primary text-primary-foreground", L.badgeOk],
    warning: ["bg-warning text-warning-foreground", L.badgeWarning],
    missing: ["bg-destructive text-destructive-foreground", L.badgeMissing],
  }[status];
  const loc = res.location;
  const fetched = res.forecast_hourly?.fetched_at ?? res.generated_at;
  return (
    <section data-section="summary" aria-label="Summary" className={`${SECTION} grid gap-2 sm:grid-cols-[auto_1fr] sm:items-start`}>
      <span className={`justify-self-start rounded-md px-3 py-1 font-bold ${badge[0]}`}>{badge[1]}</span>
      <div className="min-w-0">
        <p className="text-lg font-semibold leading-snug">{firstSentence(res.answer.text)}</p>
        <p className="mt-1 text-muted-foreground">
          {loc.name}
          {loc.district ? `, ${loc.district}` : ""} · {L.fetched} {fmtFetched(fetched)}
        </p>
      </div>
    </section>
  );
}

// ---- 2. Now row -------------------------------------------------------------
export function NowRow({ points, L }: { points: Map<string, DataPoint>; L: Labels }) {
  const cards: [string, DataPoint | undefined, string][] = [
    [L.tileTemp, points.get("now_temp"), "°C"],
    [L.tileRain, points.get("max_rain_prob_24h"), "%"],
    [L.tileWind, points.get("now_wind"), "km/h"],
  ];
  return (
    <>
      {cards.map(([label, p, unit], i) => (
        <section
          key={label}
          data-section={i === 0 ? "now" : undefined}
          aria-label={label}
          className="rounded-md border border-border bg-card p-4 lg:col-span-4"
        >
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-muted-foreground">{label}</h3>
            {p && p.value != null ? (
              <p className="stat-number text-right text-4xl font-bold">
                {String(p.value)}
                <span className="ml-1 text-lg font-semibold text-muted-foreground">{unit}</span>
              </p>
            ) : (
              <p className="text-right">
                <span className="stat-number block text-4xl font-bold text-muted-foreground">–</span>
                <span className="text-muted-foreground">{L.notAvailable}</span>
              </p>
            )}
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {p ? `${dataDate(p, L)} · ${p.source} · ${L.fetched} ${fmtFetched(p.fetched_at)}` : L.notAvailable}
          </p>
        </section>
      ))}
    </>
  );
}

// ---- 4. Alerts --------------------------------------------------------------
type Alert = { tone: "warning" | "error"; date: string; name: string; text: string };

function ruleDate(r: Rule, points: Map<string, DataPoint>): string {
  for (const id of r.evidence) {
    const p = points.get(id);
    if (p?.valid_time) return fmtSpan(p.valid_time);
  }
  return "";
}

export function collectAlerts(res: AdviceResponse, points: Map<string, DataPoint>, L: Labels): Alert[] {
  const when = fmtFetched(res.generated_at);
  const errors: Alert[] = res.sources
    .filter((s) => s.status !== "ok")
    .map((s) => ({ tone: "error", date: when, name: `${s.name} ${L.sourceDown}`, text: `${L.missingParts} ${partFor(s, L)}${s.error ? ` (${s.error})` : ""}` }));
  const dataWarnings: Alert[] = res.sources
    .filter((s) => s.status === "ok" && (s.stale || s.fallback_for))
    .map((s) => ({
      tone: "warning",
      date: fmtFetched(s.fetched_at),
      name: s.stale ? `${s.name}: ${L.staleTitle}` : s.name,
      text: s.note ?? s.error ?? "",
    }));
  const rules: Alert[] = res.rules
    .filter((r) => WARN_STATUSES.has(r.status))
    .map((r) => ({ tone: "warning", date: ruleDate(r, points), name: `${L.rule[r.id] ?? r.name} · ${L.status[r.status] ?? r.status}`, text: firstSentence(r.summary) }));
  return [...errors, ...dataWarnings, ...rules];
}

function partFor(s: SourceView, L: Labels): string {
  if (s.id === "forecast") return L.partForecast;
  if (s.id === "rain_mtd" || s.id === "rain_baseline") return L.partRain;
  if (s.id === "soil") return L.partSoil;
  return L.partGeo;
}

export function Alerts({ alerts, L }: { alerts: Alert[]; L: Labels }) {
  return (
    <section data-section="alerts" aria-label={L.alertsTitle} className={SECTION}>
      <h2 className="text-lg font-bold">{L.alertsTitle}</h2>
      {alerts.length === 0 ? (
        <p className="mt-2 text-muted-foreground">{L.noAlerts}</p>
      ) : (
        <ul className="mt-2 grid gap-2">
          {alerts.map((a, i) => (
            <li
              key={i}
              role={a.tone === "error" ? "alert" : undefined}
              className={`grid gap-x-3 rounded-md border px-3 py-2 sm:grid-cols-[11rem_minmax(0,14rem)_1fr] ${
                a.tone === "error" ? "border-destructive bg-destructive-soft" : "border-warning bg-warning-soft"
              }`}
            >
              <span className="text-muted-foreground">{a.date || "–"}</span>
              <span className={`font-semibold ${a.tone === "error" ? "text-destructive-text" : "text-warning"}`}>
                {a.tone === "error" ? "✕" : "⚠"} {a.name}
              </span>
              <span>{a.text}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---- 5. Advice --------------------------------------------------------------
export function AdviceBlock({ res, points, L, onSpeak }: {
  res: AdviceResponse; points: Map<string, DataPoint>; L: Labels; onSpeak?: () => void;
}) {
  return (
    <section data-section="advice" aria-label={L.answer} className={SECTION}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-bold">{L.answer}</h2>
        {onSpeak && (
          <button
            type="button"
            onClick={onSpeak}
            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-primary/60 px-3 font-semibold text-primary hover:bg-accent/20"
          >
            <SpeakerIcon />
            <span>{L.listen}</span>
          </button>
        )}
      </div>
      <div className="mt-2 space-y-1 text-lg leading-relaxed">
        {sentences(res.answer.text).map((s, i) => <p key={i}>{s}</p>)}
      </div>
      {res.answer.recommendations.length > 0 && (
        <>
          <h3 className="mt-4 font-semibold">{L.recommendations}</h3>
          <ol className="mt-2 grid gap-2">
            {res.answer.recommendations.map((r, i) => (
              <li key={i} className="grid grid-cols-[2rem_1fr] gap-x-2">
                <span className="stat-number text-right font-bold text-primary">{i + 1}.</span>
                <div>
                  <p>{r.text}</p>
                  <CiteLine item={r} points={points} L={L} />
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
      {res.answer.missing_data.length > 0 && <p className="mt-3 text-muted-foreground">{L.missing} {res.answer.missing_data.join("; ")}</p>}
      {res.unverified_numbers.length > 0 && (
        <p className="mt-3 rounded-md border border-warning bg-warning-soft p-2">{L.unverified} {res.unverified_numbers.join(", ")}</p>
      )}
      <p className="mt-4 rounded-md border border-primary/40 bg-muted p-3 font-semibold">{res.answer.disclaimer}</p>
      <p className="mt-2 text-sm text-muted-foreground">
        {L.generatedBy}: {res.generated_by === "rules-fallback" ? L.fallbackNote : res.generated_by} · {fmtFetched(res.generated_at)} ·{" "}
        {res.elapsed_ms} ms · id {res.request_id}
      </p>
    </section>
  );
}

/** One compact line per cited value: value, data date, source and fetch time. */
function CiteLine({ item, points, L }: { item: CitedItem; points: Map<string, DataPoint>; L: Labels }) {
  const list = item.evidence.map((id) => points.get(id)).filter((p): p is DataPoint => !!p);
  if (!list.length) return <p className="text-sm text-warning">{L.noCite}</p>;
  return (
    <ul className="mt-0.5 text-sm text-muted-foreground">
      {list.map((p) => (
        <li key={p.id}>
          <b className="font-semibold text-foreground">{p.label}: {fmtValue(p)}</b> · {dataDate(p, L)} · {p.source} · {L.fetched}{" "}
          {fmtFetched(p.fetched_at)}
        </li>
      ))}
    </ul>
  );
}

// ---- 6. Why this advice (collapsed) ------------------------------------------
export function WhyTable({ res, points, L }: { res: AdviceResponse; points: Map<string, DataPoint>; L: Labels }) {
  return (
    <details data-section="why" className={SECTION}>
      <summary className="min-h-11 cursor-pointer text-lg font-bold">{L.why}</summary>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[40rem] border-collapse text-left align-top">
          <thead>
            <tr className="text-sm text-muted-foreground">
              <th className="w-[22%] border-b border-border px-2 py-2 font-semibold">{L.colRule}</th>
              <th className="w-[43%] border-b border-border px-2 py-2 font-semibold">{L.colInput}</th>
              <th className="border-b border-border px-2 py-2 font-semibold">{L.colResult}</th>
            </tr>
          </thead>
          <tbody>
            {res.rules.map((r) => {
              const warn = WARN_STATUSES.has(r.status);
              const good = GOOD_STATUSES.has(r.status);
              const inputs = r.evidence.map((id) => points.get(id)).filter((p): p is DataPoint => !!p);
              return (
                <tr key={r.id} className="align-top">
                  <td className="border-b border-border px-2 py-2 font-semibold">{L.rule[r.id] ?? r.name}</td>
                  <td className="border-b border-border px-2 py-2">
                    {inputs.length === 0 ? (
                      <span className="text-muted-foreground">– {L.notAvailable}</span>
                    ) : (
                      <ul className="grid gap-1">
                        {inputs.map((p) => (
                          <li key={p.id} className="grid grid-cols-[1fr_auto] gap-x-3">
                            <span>
                              {p.label}
                              <span className="block text-sm text-muted-foreground">
                                {dataDate(p, L)} · {p.source} · {L.fetched} {fmtFetched(p.fetched_at)}
                              </span>
                            </span>
                            <span className="text-right font-semibold tabular-nums">{fmtValue(p)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td className="border-b border-border px-2 py-2">
                    <span className={`mb-1 inline-block rounded-full px-2 py-0.5 text-sm font-bold ${
                      warn ? "bg-warning-soft text-warning" : good ? "bg-muted text-primary" : "bg-muted text-muted-foreground"
                    }`}>
                      {L.status[r.status] ?? r.status.replace(/_/g, " ")}
                    </span>
                    <span className="block">{r.summary}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <IrrigationTable res={res} L={L} />
    </details>
  );
}

// ---- 7. Data and sources ------------------------------------------------------
export function SourcesTable({ res, L }: { res: AdviceResponse; L: Labels }) {
  const ageOf = (s: SourceView) => (s.age_minutes != null ? ` (${fmtAge(s.age_minutes, L.ageUnits)})` : "");
  return (
    <section data-section="sources" aria-label={L.sourcesTitle} className={SECTION}>
      <h2 className="text-lg font-bold">{L.sourcesTitle}</h2>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[40rem] border-collapse text-left">
          <thead>
            <tr className="text-sm text-muted-foreground">
              <th className="border-b border-border px-2 py-2 font-semibold">{L.colSource}</th>
              <th className="border-b border-border px-2 py-2 font-semibold">{L.colSupplied}</th>
              <th className="border-b border-border px-2 py-2 text-right font-semibold">{L.colFetched}</th>
              <th className="border-b border-border px-2 py-2 font-semibold">{L.colStatus}</th>
            </tr>
          </thead>
          <tbody>
            {res.sources.map((s) => {
              const [label, cls] =
                s.status !== "ok"
                  ? [L.statusUnavailable, "text-destructive-text"]
                  : s.stale
                    ? [L.statusSaved, "text-warning"]
                    : s.fallback_for
                      ? [L.statusFallback, "text-warning"]
                      : s.cached
                        ? [L.statusCached, "text-muted-foreground"]
                        : [L.statusLive, "text-primary"];
              return (
                <tr key={s.id} className="align-top">
                  <td className="border-b border-border px-2 py-2 font-semibold">{s.name}</td>
                  <td className="border-b border-border px-2 py-2">{L.supplied[s.id] ?? s.id}</td>
                  <td className="border-b border-border px-2 py-2 text-right tabular-nums whitespace-nowrap">
                    {s.fetched_at ? `${fmtFetched(s.fetched_at)}${ageOf(s)}` : "–"}
                  </td>
                  <td className={`border-b border-border px-2 py-2 font-semibold ${cls}`}>
                    {label}
                    {s.status !== "ok" && s.error && <span className="block text-sm font-normal">{s.error}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        Open-Meteo.com (CC BY 4.0) · ISRIC SoilGrids v2.0 (CC BY 4.0) · MET Norway (CC BY 4.0, used only as a fallback) ·
        NASA POWER (used only if the archive baseline is unavailable)
      </p>
    </section>
  );
}
