import { dataDate, fmtFetched } from "@/lib/format";
import type { Labels } from "@/lib/i18n";
import type { DataPoint } from "@/lib/types";

/** Big-number field status: temperature, rain chance, wind and topsoil, each with source and times. */
export default function StatTiles({ points, rainWarnPct, L }: {
  points: Map<string, DataPoint>;
  rainWarnPct?: number; // heavy-rain rule threshold from the backend config
  L: Labels;
}) {
  const temp = points.get("now_temp");
  const rain = points.get("max_rain_prob_24h");
  const wind = points.get("now_wind");
  const sand = points.get("soil_sand");
  const clay = points.get("soil_clay");
  const ph = points.get("soil_ph");
  const soilAny = sand ?? clay ?? ph;

  return (
    <section aria-label={L.statusTitle} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile label={L.tileTemp} value={temp?.value} unit="°C" p={temp} L={L} />
      <Tile label={L.tileRain} value={rain?.value} unit="%" p={rain} L={L} tone={rainWarnPct != null && Number(rain?.value) > rainWarnPct ? "amber" : undefined} />
      <Tile label={L.tileWind} value={wind?.value} unit="km/h" p={wind} L={L} />
      <div className="rounded-md border border-border bg-card p-3">
        <p className="text-sm text-muted">{L.tileSoil}</p>
        {soilAny ? (
          <>
            <div className="mt-1 grid grid-cols-3 gap-1">
              <Mini label={L.sand} value={sand?.value} unit="%" />
              <Mini label={L.clay} value={clay?.value} unit="%" />
              <Mini label={L.ph} value={ph?.value} unit="" />
            </div>
            <Meta p={soilAny} L={L} />
          </>
        ) : (
          <p className="stat-number mt-1 text-4xl font-bold text-muted">–</p>
        )}
      </div>
    </section>
  );
}

function Tile({ label, value, unit, p, L, tone }: {
  label: string; value: unknown; unit: string; p?: DataPoint; L: Labels; tone?: "amber";
}) {
  return (
    <div className={`rounded-md border p-3 ${tone === "amber" ? "border-amber bg-amber-soft" : "border-border bg-card"}`}>
      <p className="text-sm text-muted">{label}</p>
      <p className={`stat-number mt-1 text-4xl font-bold sm:text-5xl ${tone === "amber" ? "text-amber" : ""}`}>
        {value == null ? "–" : String(value)}
        {value != null && <span className="ml-1 text-lg font-semibold text-muted">{unit}</span>}
      </p>
      {p && <Meta p={p} L={L} />}
    </div>
  );
}

function Mini({ label, value, unit }: { label: string; value: unknown; unit: string }) {
  return (
    <div>
      <p className="stat-number text-2xl font-bold">
        {value == null ? "–" : String(value)}
        <span className="text-sm text-muted">{value == null ? "" : unit}</span>
      </p>
      <p className="text-sm text-muted">{label}</p>
    </div>
  );
}

function Meta({ p, L }: { p: DataPoint; L: Labels }) {
  return (
    <p className="mt-2 text-sm leading-snug text-muted">
      {dataDate(p, L)} · {p.source} · {L.fetched} {fmtFetched(p.fetched_at)}
    </p>
  );
}
