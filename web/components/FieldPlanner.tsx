import { fmtFetched, fmtLocal, fmtSpan } from "@/lib/format";
import { fill, type Labels } from "@/lib/i18n";
import type { AdviceResponse } from "@/lib/types";

/** Irrigation planner (water balance), heat-stress days and fertiliser timing, from the same forecast request. */
export default function FieldPlanner({ res, L }: { res: AdviceResponse; L: Labels }) {
  const wb = res.water_balance;
  const heat = res.heat;
  const fert = res.fertiliser;
  const daily = res.forecast_daily;
  const meta = daily ? `${daily.source} · ${L.fetched} ${fmtFetched(daily.fetched_at)}` : "";
  const fertRule = res.rules.find((r) => r.id === "fertiliser");

  return (
    <div className="grid grid-cols-1 gap-4">
      {/* Irrigation planner */}
      <section className="rounded-md border border-border bg-card p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-bold">{L.plannerTitle}</h2>
          <span className="rounded-full border border-border px-2 py-0.5 text-sm text-muted">{L.estimate}</span>
        </div>
        {!wb || wb.status === "unknown" ? (
          <p className="mt-2 text-muted">{L.status.unknown}</p>
        ) : (
          <>
            <p className={`mt-2 text-lg font-semibold ${wb.irrigate_on ? "text-primary" : ""}`}>
              {wb.irrigate_on
                ? fill(L.irrigateOn, { date: fmtLocal(wb.irrigate_on) })
                : fill(L.noIrrigation, { n: wb.days.length })}
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[30rem] border-collapse">
                <thead>
                  <tr className="text-left text-sm text-muted">
                    {[L.colDay, `${L.colEt0} (mm)`, `${L.colUse} (mm)`, `${L.colRain} (mm)`, `${L.colDeficit} (mm)`].map((h) => (
                      <th key={h} className="border-b border-border px-2 py-1.5 font-semibold">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {wb.days.map((d) => (
                    <tr key={d.date} className={d.date === wb.irrigate_on ? "bg-primary-soft" : ""}>
                      <td className="border-b border-border px-2 py-1.5 whitespace-nowrap">{fmtLocal(d.date)}</td>
                      <td className="border-b border-border px-2 py-1.5 tabular-nums">{d.et0_mm}</td>
                      <td className="border-b border-border px-2 py-1.5 tabular-nums">{d.crop_use_mm}</td>
                      <td className="border-b border-border px-2 py-1.5 tabular-nums">{d.rain_mm}</td>
                      <td className="border-b border-border px-2 py-1.5">
                        <div className="flex items-center gap-2">
                          <span className="w-12 tabular-nums font-semibold">{d.deficit_mm}</span>
                          <span className="h-2 flex-1 rounded bg-border" aria-hidden="true">
                            <span
                              className={`block h-2 rounded ${d.over_threshold ? "bg-amber" : "bg-primary"}`}
                              style={{ width: `${Math.min(100, (d.deficit_mm / wb.thresholds.deficit_mm) * 100)}%` }}
                            />
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-sm text-muted">
              {fill(L.calcExplain, { kc: wb.thresholds.crop_factor, mm: wb.thresholds.deficit_mm })}
            </p>
            <p className="mt-1 text-sm text-muted">{meta}</p>
          </>
        )}
      </section>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* Heat stress */}
        <section className={`rounded-md border p-4 ${heat?.status === "warning" ? "border-amber bg-amber-soft" : "border-border bg-card"}`}>
          <h2 className="text-lg font-bold">{L.heatTitle}</h2>
          {!heat || heat.status === "unknown" ? (
            <p className="mt-2 text-muted">{L.status.unknown}</p>
          ) : heat.status === "warning" ? (
            <>
              <p className="mt-2 font-semibold text-amber">⚠ {fill(L.heatHot, { t: heat.thresholds.tmax_c })}</p>
              <ul className="mt-1 space-y-1">
                {heat.hot_days.map((d) => (
                  <li key={d.date} className="flex justify-between gap-2">
                    <span>{fmtLocal(d.date)}</span>
                    <span className="stat-number text-xl font-bold text-amber">{d.tmax_c} °C</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="mt-2">
              {fill(L.heatNone, { t: heat.thresholds.tmax_c })}
              {heat.max_tmax_c != null && heat.max_tmax_date && (
                <span className="block text-muted">
                  max <b className="stat-number text-foreground">{heat.max_tmax_c} °C</b> · {fmtLocal(heat.max_tmax_date)}
                </span>
              )}
            </p>
          )}
          {daily && <p className="mt-2 text-sm text-muted">{meta}</p>}
        </section>

        {/* Fertiliser timing */}
        <section className={`rounded-md border p-4 ${fert?.status === "delay" ? "border-amber bg-amber-soft" : "border-border bg-card"}`}>
          <h2 className="text-lg font-bold">{L.fertTitle}</h2>
          {!fert || fert.status === "unknown" ? (
            <p className="mt-2 text-muted">{L.status.unknown}</p>
          ) : (
            <>
              <p className={`mt-2 font-semibold ${fert.status === "delay" ? "text-amber" : "text-primary"}`}>
                {fert.status === "delay" ? `⚠ ${L.fertDelay}` : L.fertOk}
              </p>
              <p className="mt-1">
                {fill(L.next48, {
                  h: fert.thresholds.lookahead_h,
                  p: fert.max_precip_prob_pct ?? "–",
                  mm: fert.total_precip_mm ?? "–",
                })}
              </p>
              {fertRule && <p className="mt-1 text-sm text-muted">{fertRule.summary}</p>}
              {res.forecast_hourly && (
                <p className="mt-2 text-sm text-muted">
                  {fmtSpan(fert.window_start)} – {fmtSpan(fert.window_end)} · {res.forecast_hourly.source} · {L.fetched}{" "}
                  {fmtFetched(res.forecast_hourly.fetched_at)}
                </p>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
