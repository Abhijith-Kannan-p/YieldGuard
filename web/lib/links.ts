// Shareable advice links: /advice/?location=Hubballi&q=Can+I+spray&lang=kn, optionally with &lat=..&lon=..
// so a saved field or "My location" keeps its coordinates. Links with only location= work as before.
import type { Lang } from "./types";

const LANGS = new Set(["en", "hi", "kn"]);

export function adviceLink(p: { question: string; location: string; lang: Lang; lat?: number; lon?: number }): string {
  const qs = new URLSearchParams({ location: p.location, q: p.question, lang: p.lang });
  if (p.lat != null && p.lon != null) {
    qs.set("lat", String(p.lat));
    qs.set("lon", String(p.lon));
  }
  return `/advice/?${qs}`;
}

export interface AdviceLink {
  location: string | null;
  question: string | null;
  lang: Lang | null;
  coords: { lat: number; lon: number } | null;
}

const coord = (v: string | null, limit: number): number | null => {
  if (v == null || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && Math.abs(n) <= limit ? n : null;
};

export function readAdviceLink(search: string): AdviceLink {
  const qs = new URLSearchParams(search);
  const lang = qs.get("lang");
  const lat = coord(qs.get("lat"), 90);
  const lon = coord(qs.get("lon"), 180);
  return {
    location: qs.get("location") || null,
    question: qs.get("q") || qs.get("question") || null,
    lang: lang && LANGS.has(lang) ? (lang as Lang) : null,
    coords: lat != null && lon != null ? { lat, lon } : null,
  };
}
