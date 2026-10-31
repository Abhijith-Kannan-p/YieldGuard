import { fmtFetched, fmtLocal } from "@/lib/format";
import { fill, type Labels } from "@/lib/i18n";
import type { AdviceResponse } from "@/lib/types";

/** Day-by-day water balance behind the irrigation rule (shown inside "Why this advice").
 *  Heat and fertiliser results appear as alert rows and in the why table, so they are not repeated here. */
export function IrrigationTable({ res, L }: { res: AdviceResponse; L: Labels }) {
  const wb = res.water_balance;
  const daily = res.forecast_daily;
  if (!wb || wb.status === "unknown" || !wb.days.length) return null;
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{L.plannerTitle}</h3>
        <span className="rounded-full border border-border px-2 py-0.5 text-sm text-muted-foreground">{L.estimate}</span>
        <span className={wb.irrigate_on ? "font-semibold text-primary" : ""}>
          {wb.irrigate_on ? fill(L.irrigateOn, { date: fmtLocal(wb.irrigate_on) }) : fill(L.noIrrigation, { n: wb.days.length })}
        </span>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[30rem] border-collapse text-left">
          <thead>
            <tr className="text-sm text-muted-foreground">
              <th className="border-b border-border px-2 py-1.5 font-semibold">{L.colDay}</th>
              {[`${L.colEt0} (mm)`, `${L.colUse} (mm)`, `${L.colRain} (mm)`, `${L.colDeficit} (mm)`].map((h) => (
                <th key={h} className="border-b border-border px-2 py-1.5 text-right font-semibold">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {wb.days.map((d) => (
              <tr key={d.date} className={d.date === wb.irrigate_on ? "bg-muted" : ""}>
                <td className="border-b border-border px-2 py-1.5 whitespace-nowrap">{fmtLocal(d.date)}</td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums">{d.et0_mm}</td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums">{d.crop_use_mm}</td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums">{d.rain_mm}</td>
                <td className={`border-b border-border px-2 py-1.5 text-right font-semibold tabular-nums ${d.over_threshold ? "text-warning" : ""}`}>
                  {d.deficit_mm}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        {fill(L.calcExplain, { kc: wb.thresholds.crop_factor, mm: wb.thresholds.deficit_mm })}
        {daily ? ` ${daily.source} · ${L.fetched} ${fmtFetched(daily.fetched_at)}` : ""}
      </p>
    </div>
  );
}
