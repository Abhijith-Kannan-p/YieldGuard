"use client";

import { useState } from "react";
import { fmtFetched, fmtLocal } from "@/lib/format";
import type { Labels } from "@/lib/i18n";
import type { ForecastHour, SprayWindow } from "@/lib/types";

type Safety = "safe" | "risk" | "missing";

/** Same weather test as the spray-window rule: wind, rain chance and rain below the thresholds. */
function classify(h: ForecastHour, maxWind: number, maxProb: number): Safety {
  if (h.wind_speed_10m == null || h.precipitation_probability == null || h.precipitation == null) return "missing";
  return h.wind_speed_10m < maxWind && h.precipitation_probability < maxProb && h.precipitation <= 0 ? "safe" : "risk";
}

const CELL: Record<Safety, string> = {
  safe: "bg-primary text-primary-foreground border-primary",
  risk: "bg-amber-soft text-foreground border-amber",
  missing: "bg-destructive-soft text-destructive border-destructive",
};

/** 72 hour cells coloured by spraying safety. Tap a cell to see its values. */
export default function HourStrip({
  hours, windows, maxWind, maxProb, source, fetchedAt, L,
}: {
  hours: ForecastHour[];
  windows: SprayWindow[];
  maxWind: number;
  maxProb: number;
  source: string;
  fetchedAt: string;
  L: Labels;
}) {
  const [sel, setSel] = useState(0);
  const inWindow = (t: string) => windows.some((w) => w.start <= t && t <= w.end);
  const h = hours[Math.min(sel, hours.length - 1)];

  return (
    <section className="rounded-md border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold">{L.stripTitle}</h2>
        <p className="text-sm text-muted">{L.stripHelp}</p>
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-sm">
        <Legend cls={CELL.safe} label={`${L.legendSafe} (< ${maxWind} km/h, < ${maxProb}%)`} />
        <Legend cls={CELL.risk} label={L.legendRisk} />
        <Legend cls={CELL.missing} label={L.legendMissing} />
      </div>

      <div className="-mx-1 mt-3 overflow-x-auto pb-2" role="listbox" aria-label={L.stripTitle}>
        <div className="flex gap-1 px-1">
          {hours.map((x, i) => {
            const s = classify(x, maxWind, maxProb);
            const hr = x.time.slice(11, 13);
            const newDay = i === 0 || hr === "00";
            return (
              <div key={x.time} className="flex flex-col items-center">
                <span className="h-6 whitespace-nowrap text-sm font-semibold text-muted">{newDay ? fmtLocal(x.time.slice(0, 10)) : ""}</span>
                <button
                  type="button"
                  role="option"
                  aria-selected={i === sel}
                  aria-label={`${fmtLocal(x.time)}: ${s === "safe" ? L.legendSafe : s === "risk" ? L.legendRisk : L.legendMissing}`}
                  onClick={() => setSel(i)}
                  className={`relative flex h-14 w-11 flex-col items-center justify-center rounded border text-sm font-semibold ${CELL[s]} ${
                    i === sel ? "ring-2 ring-foreground ring-offset-2 ring-offset-card" : ""
                  }`}
                >
                  {hr}
                  {inWindow(x.time) && <span className="absolute top-1 h-1 w-5 rounded bg-primary-foreground/70" aria-hidden="true" />}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {h && (
        <div className="mt-3 rounded-md border border-border bg-card-raised p-3" aria-live="polite">
          <p className="font-semibold">
            {fmtLocal(h.time)}
            {inWindow(h.time) && <span className="ml-2 rounded bg-primary-soft px-2 py-0.5 text-sm text-primary">{L.inWindow}</span>}
          </p>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-5">
            <Val k={L.wind} v={h.wind_speed_10m} u="km/h" />
            <Val k={L.rainChance} v={h.precipitation_probability} u="%" />
            <Val k={L.rainMm} v={h.precipitation} u="mm" />
            <Val k={L.temp} v={h.temperature_2m} u="°C" />
            <Val k={L.humidity} v={h.relative_humidity_2m} u="%" />
          </dl>
          <p className="mt-2 text-sm text-muted">
            {source} · {L.fetched} {fmtFetched(fetchedAt)}
          </p>
        </div>
      )}
    </section>
  );
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-4 w-4 rounded border ${cls}`} aria-hidden="true" />
      {label}
    </span>
  );
}

function Val({ k, v, u }: { k: string; v: number | null; u: string }) {
  return (
    <div>
      <dt className="text-sm text-muted">{k}</dt>
      <dd className="stat-number text-xl font-bold">{v == null ? "–" : `${v} ${u}`}</dd>
    </div>
  );
}
