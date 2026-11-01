import { fmtAge, fmtFetched, fmtLocal } from "@/lib/format";
import { fill, type Labels } from "@/lib/i18n";
import { adviceLink } from "@/lib/links";
import type { Lang, MandiPageResponse, MandiRecord, SourceView } from "@/lib/types";

const rs = (v: number | null) => (v == null ? "–" : v.toLocaleString("en-IN"));
const km = (v: number) => (Math.round(v * 10) / 10).toString();

/** live / cached / saved copy / unavailable, with the fetch time, as on the advice page. */
export function SourceLine({ s, L }: { s: SourceView; L: Labels }) {
  const [label, cls] =
    s.status !== "ok"
      ? [L.statusUnavailable, "text-destructive-text"]
      : s.stale
        ? [L.statusSaved, "text-warning"]
        : s.cached
          ? [L.statusCached, "text-muted-foreground"]
          : [L.statusLive, "text-primary"];
  const age = s.age_minutes != null ? ` (${fmtAge(s.age_minutes, L.ageUnits)})` : "";
  return (
    <p data-source-status={s.status !== "ok" ? "unavailable" : s.stale ? "saved" : s.cached ? "cached" : "live"} className="text-sm text-muted-foreground">
      {L.mandiSource}: {s.name} · <span className={`font-semibold ${cls}`}>{label}</span>
      {s.fetched_at && ` · ${L.fetched} ${fmtFetched(s.fetched_at)}${age}`}
      {s.status !== "ok" && s.error && <span className="block">{s.error}</span>}
      {s.status === "ok" && s.stale && s.error && <span className="block">{s.error}</span>}
    </p>
  );
}

function dateLine(r: MandiRecord, today: string, L: Labels): string {
  const d = fmtLocal(r.arrival_date);
  return r.arrival_date === today ? fill(L.reportedToday, { date: d }) : fill(L.latestAvailable, { date: d });
}

function Prices({ r, L }: { r: MandiRecord; L: Labels }) {
  return (
    <>
      <p className="text-sm text-muted-foreground">{L.modalPrice}</p>
      <p data-modal-price className="text-3xl font-bold tabular-nums">
        Rs {rs(r.modal_price)} <span className="text-base font-normal text-muted-foreground">{L.perQuintal}</span>
      </p>
      <p className="tabular-nums">{fill(L.priceRange, { min: rs(r.min_price), max: rs(r.max_price) })}</p>
      {r.variety && <p className="text-sm text-muted-foreground">{L.variety}: {r.variety}</p>}
    </>
  );
}

function stateMessage(res: MandiPageResponse, L: Labels): string | null {
  const max = km(res.max_distance_km);
  switch (res.status) {
    case "no_nearby_market":
      return fill(L.mandiNoNearby, { km: max });
    case "incomplete":
      return fill(L.mandiIncomplete, { km: max, n: String(res.markets_not_located) });
    case "no_market":
      return L.mandiNoMarket;
    case "no_data":
      return L.mandiNoData;
    case "unknown":
      return L.mandiUnavailable;
    default:
      return null;
  }
}

/** One crop at the nearest reporting market, the other markets nearby, and an explicit state otherwise. */
export default function MandiView({ res, lang, L }: { res: MandiPageResponse; lang: Lang; L: Labels }) {
  const crop = res.labels[lang];
  const msg = stateMessage(res, L);
  const main = res.records[0];
  const ask = adviceLink({
    question: fill(L.askPriceQuestion, { crop }), location: res.location.name, lang,
    lat: res.location.lat, lon: res.location.lon,
  });
  return (
    <div className="grid gap-4">
      <p data-not-forecast className="rounded-md border border-border bg-muted p-3 font-semibold">{L.notForecast}</p>

      {main && res.market ? (
        <section data-section="mandi-price" aria-label={crop} className="rounded-md border border-border bg-card p-4">
          <h2 className="text-lg font-bold">{crop}</h2>
          <p className="font-semibold">
            {res.market.name} · {res.market.district} · {fill(L.kmAway, { km: km(res.market.distance_km) })}
          </p>
          <p data-date-status={res.status} className={res.status === "latest" ? "font-semibold text-warning" : "text-primary"}>
            {dateLine(main, res.today, L)}
          </p>
          <div className="mt-3">
            <Prices r={main} L={L} />
          </div>
          {res.records.length > 1 && (
            <div className="mt-3 border-t border-border pt-3">
              <p className="font-semibold">{L.otherVarieties}</p>
              <ul className="mt-1 grid gap-1">
                {res.records.slice(1).map((r) => (
                  <li key={`${r.variety}-${r.arrival_date}`} className="tabular-nums">
                    {r.variety || r.commodity}: Rs {rs(r.modal_price)} ({fill(L.priceRange, { min: rs(r.min_price), max: rs(r.max_price) })})
                  </li>
                ))}
              </ul>
            </div>
          )}
          <a
            data-ask-link
            href={ask}
            className="mt-4 inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-semibold text-primary-foreground hover:bg-accent hover:text-accent-foreground"
          >
            {L.askPrice}
          </a>
        </section>
      ) : (
        <section data-section="mandi-state" data-status={res.status} role="status" className="rounded-md border border-warning bg-warning-soft p-4">
          <p className="font-semibold">{crop}</p>
          <p>{msg}</p>
          {res.nearest_beyond && (
            <p className="mt-1">
              {fill(L.mandiNearestBeyond, {
                market: res.nearest_beyond.market, district: res.nearest_beyond.district,
                dist: km(res.nearest_beyond.distance_km),
              })}
            </p>
          )}
        </section>
      )}

      {main && res.market && (
        <section data-section="mandi-nearby" aria-label={fill(L.nearbyTitle, { km: km(res.max_distance_km) })} className="rounded-md border border-border bg-card p-4">
          <h2 className="text-lg font-bold">{fill(L.nearbyTitle, { km: km(res.max_distance_km) })}</h2>
          {res.nearby.length === 0 ? (
            <p className="mt-2 text-muted-foreground">{fill(L.nearbyNone, { km: km(res.max_distance_km) })}</p>
          ) : (
            <ul className="mt-2 grid gap-2">
              {res.nearby.map((n) => (
                <li key={`${n.market}|${n.district}`} data-nearby-market={n.market} className="rounded-md border border-border p-3">
                  <p className="font-semibold">
                    {n.market} · {n.district} · {fill(L.kmAway, { km: km(n.distance_km) })}
                  </p>
                  {n.records[0] && (
                    <p className="tabular-nums">
                      Rs {rs(n.records[0].modal_price)} {L.perQuintal} ·{" "}
                      {fill(L.priceRange, { min: rs(n.records[0].min_price), max: rs(n.records[0].max_price) })} ·{" "}
                      {dateLine(n.records[0], res.today, L)}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <SourceLine s={res.source} L={L} />
    </div>
  );
}
