"use client";

import { useMemo } from "react";
import FieldPlanner from "./FieldPlanner";
import HourStrip from "./HourStrip";
import { SpeakerIcon } from "./Icons";
import ShareBar from "./ShareBar";
import SourceFooter from "./SourceFooter";
import StatTiles from "./StatTiles";
import { dataDate, fmtAge, fmtFetched, fmtValue } from "@/lib/format";
import type { Labels } from "@/lib/i18n";
import type { AdviceResponse, CitedItem, DataPoint, Rule, SourceView } from "@/lib/types";

// Amber: drought, waterlogging, heat, heavy rain (and fertiliser delay, which is heavy-rain driven), soil flags.
export const WARN_STATUSES = new Set(["warning", "drought_risk", "waterlogging_risk", "flags", "delay"]);
const GOOD_STATUSES = new Set(["found", "ok", "normal", "irrigate"]);

/** One full answer, laid out as a field-status dashboard. */
export default function AdviceResult({
  res, L, onSpeak, showShare = true,
}: {
  res: AdviceResponse;
  L: Labels;
  onSpeak?: () => void;
  showShare?: boolean;
}) {
  const points = useMemo(() => new Map(res.data_points.map((p) => [p.id, p])), [res.data_points]);
  const failed = res.sources.filter((s) => s.status !== "ok");
  const stale = res.sources.filter((s) => s.status === "ok" && s.stale);
  const alerts = res.rules.filter((r) => WARN_STATUSES.has(r.status));
  const spray = res.rules.find((r) => r.id === "spray_window");
  const heavy = res.rules.find((r) => r.id === "heavy_rain");
  const loc = res.location;

  return (
    <div className="grid grid-cols-1 gap-4">
      {res.fixture_mode && (
        <div role="alert" className="rounded-md border-2 border-destructive bg-destructive-soft p-3 font-bold">
          {L.fixtureBanner}
        </div>
      )}
      {failed.map((s) => <SourceFailure key={s.id} s={s} L={L} />)}
      {stale.map((s) => (
        <div key={s.id} role="status" className="rounded-md border border-warning bg-warning-soft p-3">
          <b className="text-warning">{s.name}: {L.staleTitle}</b>
          {s.error ? ` (${s.error})` : ""}
          <span className="block">{L.staleBody} {fmtFetched(s.fetched_at)}.</span>
        </div>
      ))}

      <p className="text-muted-foreground">
        <b className="text-foreground">{loc.name}{loc.district ? `, ${loc.district}` : ""}</b> · {loc.lat.toFixed(3)},{" "}
        {loc.lon.toFixed(3)} · {loc.source}
        {loc.fetched_at ? ` · ${L.fetched} ${fmtFetched(loc.fetched_at)}` : ""}
      </p>

      <StatTiles points={points} rainWarnPct={heavy?.thresholds.prob_pct as number | undefined} L={L} />

      {alerts.length > 0 && (
        <section aria-label={L.alerts} className="grid gap-2 md:grid-cols-2">
          {alerts.map((r) => (
            <div key={r.id} className="rounded-md border border-warning bg-warning-soft p-3">
              <p className="font-semibold text-warning">⚠ {L.rule[r.id] ?? r.name} · {L.status[r.status] ?? r.status}</p>
              <p className="mt-1">{r.summary}</p>
              <Cites ids={r.evidence.slice(0, 3)} points={points} L={L} />
            </div>
          ))}
        </section>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <article className="rounded-md border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-xl font-bold">{L.answer}</h2>
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
          <p className="mt-2 text-lg leading-relaxed">{res.answer.text}</p>

          {res.answer.recommendations.length > 0 && (
            <>
              <h3 className="mt-4 font-semibold">{L.recommendations}</h3>
              <ol className="mt-2 list-decimal space-y-3 pl-5">
                {res.answer.recommendations.map((r, i) => <CitedLi key={i} item={r} points={points} L={L} />)}
              </ol>
            </>
          )}
          {res.answer.missing_data.length > 0 && (
            <p className="mt-3 text-muted-foreground">{L.missing} {res.answer.missing_data.join("; ")}</p>
          )}
          {res.unverified_numbers.length > 0 && (
            <p className="mt-3 rounded-md border border-warning bg-warning-soft p-2">{L.unverified} {res.unverified_numbers.join(", ")}</p>
          )}
          <p className="mt-4 rounded-md border border-primary/40 bg-muted p-3 font-semibold">{res.answer.disclaimer}</p>
          {showShare && <ShareBar res={res} L={L} />}
          <p className="mt-3 text-sm text-muted-foreground">
            {L.generatedBy}: {res.generated_by === "rules-fallback" ? L.fallbackNote : res.generated_by} ·{" "}
            {fmtFetched(res.generated_at)} · {res.elapsed_ms} ms · id {res.request_id}
          </p>
        </article>

        <details open className="rounded-md border border-border bg-card p-4">
          <summary className="min-h-11 cursor-pointer text-xl font-bold">{L.why}</summary>
          {res.answer.why.length > 0 && (
            <ul className="mt-2 list-disc space-y-3 pl-5">
              {res.answer.why.map((r, i) => <CitedLi key={i} item={r} points={points} L={L} />)}
            </ul>
          )}
          <h3 className="mt-4 font-semibold text-muted-foreground">{L.whyRules}</h3>
          <div className="mt-2 grid gap-2">
            {res.rules.map((r) => <RuleCard key={r.id} r={r} points={points} L={L} />)}
          </div>
          {res.data_age && res.data_age.length > 0 && (
            <div className="mt-4">
              <p className="font-semibold text-muted-foreground">{L.dataAge}</p>
              <ul className="mt-1 space-y-0.5 text-sm">
                {res.data_age.map((d) => (
                  <li key={d.source} className={d.stale ? "text-warning" : "text-muted-foreground"}>
                    {d.source}: {L.fetched} {fmtFetched(d.fetched_at)} ({fmtAge(d.age_minutes, L.ageUnits)} ·{" "}
                    {d.stale ? L.staleTag : d.cached ? L.cached : L.live})
                  </li>
                ))}
              </ul>
            </div>
          )}
        </details>
      </div>

      {res.forecast_hourly && res.forecast_hourly.hours.length > 0 && (
        <HourStrip
          hours={res.forecast_hourly.hours}
          windows={res.spray_windows}
          maxWind={(spray?.thresholds.max_wind_kmh as number) ?? 10}
          maxProb={(spray?.thresholds.max_precip_prob_pct as number) ?? 20}
          source={res.forecast_hourly.source}
          fetchedAt={res.forecast_hourly.fetched_at}
          L={L}
        />
      )}

      <FieldPlanner res={res} L={L} />

      <details className="rounded-md border border-border bg-card p-4">
        <summary className="min-h-11 cursor-pointer text-lg font-bold">{L.data}</summary>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-left text-sm text-muted-foreground">
                {[L.colItem, L.colValue, L.colFor, L.colSource, L.colFetched].map((h) => (
                  <th key={h} className="whitespace-nowrap border-b border-border px-2 py-1.5 font-semibold">{h}</th>
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
                  <td className="whitespace-nowrap border-b border-border px-2 py-1.5">
                    {fmtFetched(p.fetched_at)}
                    {p.cached ? ` (${L.cached})` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <SourceFooter sources={res.sources} L={L} />
    </div>
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
    <div role="alert" className="rounded-md border border-destructive bg-destructive-soft p-3">
      <p>
        <b className="text-destructive-text">{s.name} {L.sourceDown}</b>
        {s.error ? ` (${s.error})` : ""}
      </p>
      <p className="mt-0.5">{L.missingParts} {part}</p>
    </div>
  );
}

function RuleCard({ r, points, L }: { r: Rule; points: Map<string, DataPoint>; L: Labels }) {
  const warn = WARN_STATUSES.has(r.status);
  const good = GOOD_STATUSES.has(r.status);
  return (
    <div className={`rounded-md border border-l-4 border-border ${warn ? "border-l-warning" : good ? "border-l-primary" : "border-l-muted-foreground"} bg-muted p-3`}>
      <div className="flex items-start justify-between gap-2">
        <h4 className="font-semibold">{L.rule[r.id] ?? r.name}</h4>
        <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-sm font-bold ${
          warn ? "bg-warning-soft text-warning" : good ? "bg-muted text-primary" : "bg-border text-muted-foreground"
        }`}>
          {L.status[r.status] ?? r.status.replace(/_/g, " ")}
        </span>
      </div>
      <p className="mt-1">{r.summary}</p>
      <Cites ids={r.evidence} points={points} L={L} />
    </div>
  );
}

function CitedLi({ item, points, L }: { item: CitedItem; points: Map<string, DataPoint>; L: Labels }) {
  return (
    <li>
      <div>{item.text}</div>
      {item.evidence.length ? <Cites ids={item.evidence} points={points} L={L} /> : <div className="mt-1 text-sm text-warning">{L.noCite}</div>}
    </li>
  );
}

/** Citation chips: value, data date, source and fetch time for each data point. */
export function Cites({ ids, points, L }: { ids: string[]; points: Map<string, DataPoint>; L: Labels }) {
  const list = ids.map((id) => points.get(id)).filter((p): p is DataPoint => !!p);
  if (!list.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {list.map((p) => (
        <span key={p.id} className="rounded border border-border bg-background px-1.5 py-0.5 text-sm text-muted-foreground">
          <b className="font-semibold text-foreground">{p.label}: {fmtValue(p)}</b> · {dataDate(p, L)} · {p.source} · {L.fetched}{" "}
          {fmtFetched(p.fetched_at)}
        </span>
      ))}
    </div>
  );
}
