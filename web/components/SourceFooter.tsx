import { fmtFetched } from "@/lib/format";
import type { Labels } from "@/lib/i18n";
import type { SourceView } from "@/lib/types";

const PROVIDERS = [
  { name: "Open-Meteo.com", url: "https://open-meteo.com/", licence: "CC BY 4.0", ids: ["geocode", "forecast", "rain_mtd", "rain_baseline"] },
  { name: "ISRIC SoilGrids v2.0", url: "https://soilgrids.org/", licence: "CC BY 4.0", ids: ["soil"] },
];

/** Attribution plus the fetch time of every source used for this result. */
export default function SourceFooter({ sources, L }: { sources: SourceView[]; L: Labels }) {
  return (
    <footer className="rounded-md border border-border bg-card p-4">
      <h2 className="font-semibold">{L.dataSources}</h2>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {PROVIDERS.map((p) => {
          const used = sources.filter((s) => p.ids.includes(s.id));
          return (
            <div key={p.name}>
              <a href={p.url} target="_blank" rel="noopener" className="font-semibold underline hover:text-primary">
                {p.name}
              </a>{" "}
              <span className="text-muted">({p.licence})</span>
              <ul className="mt-1 space-y-0.5 text-sm">
                {used.map((s) => (
                  <li key={s.id} className={s.status !== "ok" ? "text-destructive" : s.stale ? "text-amber" : "text-muted"}>
                    {s.name}:{" "}
                    {s.status === "ok"
                      ? `${L.fetched} ${fmtFetched(s.fetched_at)}${s.stale ? ` (${L.staleTag})` : s.cached ? ` (${L.cached})` : ""}`
                      : `${L.failed}${s.error ? ` (${s.error})` : ""}`}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </footer>
  );
}
