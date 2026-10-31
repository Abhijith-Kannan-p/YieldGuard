"use client";

import { useMemo } from "react";
import HourStrip from "./HourStrip";
import { AdviceBlock, Alerts, collectAlerts, NowRow, SourcesTable, SummaryBar, WhyTable } from "./AnswerSections";
import { dataDate, fmtFetched, fmtValue } from "@/lib/format";
import type { Labels } from "@/lib/i18n";
import type { AdviceResponse, DataPoint } from "@/lib/types";

export { WARN_STATUSES } from "./AnswerSections";

/** One answer in a fixed order on a 12-column grid (one column on phones):
 *  1 summary bar, 2 now row, 3 next 72 hours, 4 alerts, 5 advice, 6 why (collapsed), 7 data and sources.
 *  The follow-up box and share buttons (8) are rendered below this by the page. */
export default function AdviceResult({ res, L }: { res: AdviceResponse; L: Labels }) {
  const points = useMemo(() => new Map(res.data_points.map((p) => [p.id, p])), [res.data_points]);
  const spray = res.rules.find((r) => r.id === "spray_window");
  const alerts = collectAlerts(res, points, L);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
      {res.fixture_mode && (
        <div role="alert" className="rounded-md border-2 border-destructive bg-destructive-soft p-3 font-bold lg:col-span-12">
          {L.fixtureBanner}
        </div>
      )}
      <SummaryBar res={res} L={L} />
      <NowRow points={points} L={L} />
      {res.forecast_hourly && res.forecast_hourly.hours.length > 0 && (
        <div className="lg:col-span-12">
          <HourStrip
            hours={res.forecast_hourly.hours}
            windows={res.spray_windows}
            maxWind={(spray?.thresholds.max_wind_kmh as number) ?? 10}
            maxProb={(spray?.thresholds.max_precip_prob_pct as number) ?? 20}
            source={res.forecast_hourly.source}
            fetchedAt={res.forecast_hourly.fetched_at}
            L={L}
          />
        </div>
      )}
      <Alerts alerts={alerts} L={L} />
      <AdviceBlock res={res} points={points} L={L} />
      <WhyTable res={res} points={points} L={L} />
      <SourcesTable res={res} L={L} />
    </div>
  );
}

/** Citation chips (used by follow-up answers): value, data date, source and fetch time. */
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
