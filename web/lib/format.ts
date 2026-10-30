import type { DataPoint } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-31T11:00" (already local IST from the backend) -> "31 Oct, 11:00". */
export function fmtLocal(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso);
  if (!m) return iso;
  const day = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
  return m[4] ? `${day}, ${m[4]}:${m[5]}` : day;
}

/** Replaces every ISO date/time inside a string, e.g. "2026-10-01 to 2026-10-31". */
export function fmtSpan(s: string | null | undefined): string {
  if (!s) return "";
  return String(s).replace(/\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?/g, (x) => fmtLocal(x));
}

export function fmtFetched(iso: string | null | undefined): string {
  return iso ? `${fmtLocal(iso)} IST` : "";
}

export function fmtValue(p: DataPoint): string {
  if (p.value == null) return "–";
  if (typeof p.value === "string") return fmtSpan(p.value);
  const tight = p.unit === "%" || p.unit === "°";
  return `${p.value}${p.unit ? (tight ? "" : " ") + p.unit : ""}`;
}

/** The date the value describes. Soil maps and coordinates have no single date. */
export function dataDate(p: DataPoint, labels: { soilMap: string; place: string }): string {
  if (p.valid_time) return fmtSpan(p.valid_time);
  if (p.source_id === "soil") return labels.soilMap;
  if (p.source_id === "geocode" || p.source_id === "user") return labels.place;
  return "–";
}
