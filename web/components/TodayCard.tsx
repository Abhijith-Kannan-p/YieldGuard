"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchToday } from "@/lib/api";
import { fmtFetched, fmtLocal } from "@/lib/format";
import { I18N } from "@/lib/i18n";
import { loadFields, loadSelectedField } from "@/lib/storage";
import type { TodaySummary } from "@/lib/types";

const L = I18N.en;

type State = { s: "loading" } | { s: "ok"; d: TodaySummary } | { s: "error"; msg: string };

/** Landing card: next spray window, rain chance in the next 24 h and soil summary for the
 *  selected saved field (default Dharwad). Served from the server's one-hour cache. */
export default function TodayCard() {
  const [state, setState] = useState<State>({ s: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    const selected = loadSelectedField();
    const field = loadFields().find((f) => f.id === selected);
    fetchToday(field ? { lat: field.lat, lon: field.lon } : { location: "Dharwad" }, ctrl.signal)
      .then((d) => setState({ s: "ok", d }))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setState({ s: "error", msg: e.message === "network" ? L.network : e.message });
      });
    return () => ctrl.abort();
  }, []);

  return (
    <section
      aria-label="Today in your field"
      className="mx-auto mt-6 w-full max-w-2xl rounded-lg border border-white/15 bg-black/60 p-4 text-left backdrop-blur-sm sm:p-5"
    >
      <h2 className="text-lg font-bold text-white">
        Today in your field
        {state.s === "ok" && (
          <span className="ml-2 font-normal text-[#c9d8cc]">
            · {state.d.location.name}
            {state.d.location.district ? `, ${state.d.location.district}` : ""}
          </span>
        )}
      </h2>

      {state.s === "loading" && (
        <div className="mt-3 grid animate-pulse gap-3 sm:grid-cols-3" aria-hidden="true">
          {[0, 1, 2].map((i) => <div key={i} className="h-24 rounded-md bg-white/10" />)}
        </div>
      )}
      {state.s === "error" && (
        <p role="alert" className="mt-3 rounded-md border border-destructive bg-destructive-soft p-3">
          Live summary unavailable: {state.msg}
        </p>
      )}
      {state.s === "ok" && <Body d={state.d} />}
    </section>
  );
}

function Body({ d }: { d: TodaySummary }) {
  const fc = d.sources.forecast;
  const soil = d.sources.soil;
  const fcMeta = fc.status === "ok" ? `${fc.name} · fetched ${fmtFetched(fc.fetched_at)}${fc.stale ? " (saved copy)" : ""}` : "";
  return (
    <>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <Item title="Next spray window">
          {d.spray == null ? (
            <Fail text={fc.error ?? "forecast unavailable"} />
          ) : d.spray.next ? (
            <>
              <Big>{fmtLocal(d.spray.next.start)}</Big>
              <p className="text-white/85">until {d.spray.next.end.slice(11, 16)} · {d.spray.next.hours} h</p>
            </>
          ) : (
            <p className="text-white/85">No safe window in the next {d.spray.hours_checked} hours</p>
          )}
          {fcMeta && <Meta>{fcMeta}</Meta>}
        </Item>

        <Item title="Rain chance, next 24 h">
          {d.rain_24h == null ? (
            <Fail text={fc.error ?? "forecast unavailable"} />
          ) : (
            <>
              <Big amber={d.rain_24h.status === "warning"}>
                {d.rain_24h.max_prob_pct ?? "–"}
                <span className="text-lg">%</span>
              </Big>
              <p className="text-white/85">
                {d.rain_24h.max_prob_time ? `peak ${fmtLocal(d.rain_24h.max_prob_time)}` : ""}
                {d.rain_24h.total_mm != null ? ` · ${d.rain_24h.total_mm} mm total` : ""}
              </p>
            </>
          )}
          {fcMeta && <Meta>{fcMeta}</Meta>}
        </Item>

        <Item title="Topsoil (0–5 cm)">
          {d.soil == null ? (
            <Fail text={soil.error ?? "soil data unavailable"} />
          ) : (
            <>
              <Big>pH {d.soil.ph ?? "–"}</Big>
              <p className="text-white/85">
                sand {d.soil.sand_pct ?? "–"}% · clay {d.soil.clay_pct ?? "–"}%
                {d.soil.flags.length ? ` · check: ${d.soil.flags.join(", ").replace(/_/g, " ")}` : " · no flags"}
              </p>
            </>
          )}
          {soil.status === "ok" && (
            <Meta>
              {soil.name} · fetched {fmtFetched(soil.fetched_at)}
              {soil.stale ? " (saved copy)" : ""}
            </Meta>
          )}
        </Item>
      </div>

      {d.warnings.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {d.warnings.map((w) => (
            <li key={w.id} className="rounded-md border border-amber bg-amber-soft px-2 py-1 text-white">
              <span className="font-semibold text-amber">⚠ {L.rule[w.id] ?? L.status[w.id] ?? w.id}</span>
              {w.value != null ? ` ${w.value}${w.unit === "%" ? "%" : ` ${w.unit}`}` : ""}
              {w.time ? ` · ${fmtLocal(w.time)}` : ""}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 text-sm text-white/70">
        Summary computed {fmtFetched(d.computed_at)}, refreshed at most once an hour. Open-Meteo.com (CC BY 4.0) · ISRIC
        SoilGrids v2.0 (CC BY 4.0).{" "}
        <Link href="/advice/" className="underline hover:text-white">
          Full advice →
        </Link>
      </p>
    </>
  );
}

function Item({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/5 p-3">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-[#c9d8cc]">{title}</h3>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function Big({ children, amber }: { children: React.ReactNode; amber?: boolean }) {
  return <p className={`stat-number text-3xl font-bold ${amber ? "text-amber" : "text-white"}`}>{children}</p>;
}

function Meta({ children }: { children: React.ReactNode }) {
  return <p className="mt-2 text-sm leading-snug text-white/65">{children}</p>;
}

function Fail({ text }: { text: string }) {
  return <p className="text-destructive">{text}</p>;
}
