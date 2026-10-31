// Device-only storage: saved fields and last-known answers. Every access is wrapped in
// try/catch so the app keeps working when storage is blocked (private mode, full quota).
import type { AdviceResponse } from "./types";

export const MAX_FIELDS = 5;
const MAX_LAST_ANSWERS = 5;
const FIELDS_KEY = "yg.fields.v1";
const SELECTED_KEY = "yg.selectedField.v1";
const LAST_KEY = "yg.lastAnswers.v1";

export interface SavedField {
  id: string;
  name: string; // display name, e.g. "Hubballi, Dharwad district"
  lat: number;
  lon: number;
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): boolean {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

// ---- saved fields ------------------------------------------------------------

export function loadFields(): SavedField[] {
  const list = read<SavedField[]>(FIELDS_KEY, []);
  return Array.isArray(list) ? list.filter((f) => f && typeof f.lat === "number" && typeof f.lon === "number") : [];
}

export function saveFields(fields: SavedField[]): boolean {
  return write(FIELDS_KEY, fields.slice(0, MAX_FIELDS));
}

export function fieldId(lat: number, lon: number): string {
  return `${lat.toFixed(3)},${lon.toFixed(3)}`;
}

export function loadSelectedField(): string | null {
  return read<string | null>(SELECTED_KEY, null);
}

export function saveSelectedField(id: string | null): void {
  if (id === null) {
    try {
      window.localStorage.removeItem(SELECTED_KEY);
    } catch {
      /* storage blocked */
    }
  } else {
    write(SELECTED_KEY, id);
  }
}

// ---- last-known answers ------------------------------------------------------

export interface LastAnswer {
  savedAt: string; // ISO time the answer was received
  res: AdviceResponse;
}

/** Key for "the same place": coordinates if known, otherwise the typed name. */
export function placeKey(where: { name?: string; lat?: number; lon?: number }): string {
  if (where.lat != null && where.lon != null) return `c:${where.lat.toFixed(2)},${where.lon.toFixed(2)}`;
  return `n:${(where.name || "").trim().toLowerCase()}`;
}

export function loadLastAnswer(keys: string[]): LastAnswer | null {
  const all = read<Record<string, LastAnswer>>(LAST_KEY, {});
  for (const k of keys) if (all[k]?.res) return all[k];
  return null;
}

/** Saves under every key given (typed name and resolved coordinates). Keeps the newest few places. */
export function saveLastAnswer(keys: string[], res: AdviceResponse): void {
  const all = read<Record<string, LastAnswer>>(LAST_KEY, {});
  const entry: LastAnswer = { savedAt: new Date().toISOString(), res };
  for (const k of keys) all[k] = entry;
  const newest = Object.entries(all)
    .sort((a, b) => b[1].savedAt.localeCompare(a[1].savedAt))
    .slice(0, MAX_LAST_ANSWERS * 2);
  if (!write(LAST_KEY, Object.fromEntries(newest))) {
    // Quota full: keep only this answer.
    write(LAST_KEY, Object.fromEntries(keys.map((k) => [k, entry])));
  }
}
