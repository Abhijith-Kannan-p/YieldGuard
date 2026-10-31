"use client";

import { useEffect, useState } from "react";
import { fetchToday } from "@/lib/api";
import { fmtLocal } from "@/lib/format";
import type { Labels } from "@/lib/i18n";
import { MAX_FIELDS, type SavedField } from "@/lib/storage";
import type { TodaySummary } from "@/lib/types";

type Status = { state: "loading" } | { state: "ok"; data: TodaySummary } | { state: "error"; message: string };

/** Up to MAX_FIELDS saved places with a one-line live status each; one tap switches field. */
export default function SavedFields({
  fields, selectedId, storageOk, canSave, onSelect, onRemove, onSaveCurrent, L,
}: {
  fields: SavedField[];
  selectedId: string | null;
  storageOk: boolean;
  canSave: boolean;
  onSelect: (f: SavedField) => void;
  onRemove: (f: SavedField) => void;
  onSaveCurrent: () => void;
  L: Labels;
}) {
  const [status, setStatus] = useState<Record<string, Status>>({});

  // Status lines come from /api/today, which the server caches per location for one hour.
  useEffect(() => {
    const ctrl = new AbortController();
    for (const f of fields) {
      fetchToday({ lat: f.lat, lon: f.lon }, ctrl.signal)
        .then((data) => setStatus((s) => ({ ...s, [f.id]: { state: "ok", data } })))
        .catch((e: Error) => {
          if (e.name !== "AbortError") setStatus((s) => ({ ...s, [f.id]: { state: "error", message: e.message } }));
        });
    }
    return () => ctrl.abort();
  }, [fields]);

  const full = fields.length >= MAX_FIELDS;

  return (
    <section className="rounded-md border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-bold">
          {L.savedTitle} <span className="text-base font-normal text-muted">{fields.length}/{MAX_FIELDS}</span>
        </h2>
        {canSave && storageOk && !full && (
          <button
            type="button"
            onClick={onSaveCurrent}
            className="min-h-11 rounded-md border border-primary/60 px-3 font-semibold text-primary hover:bg-primary-soft"
          >
            + {L.saveField}
          </button>
        )}
      </div>
      {!storageOk && <p className="mt-2 text-sm text-amber">{L.storageBlocked}</p>}
      {canSave && full && <p className="mt-2 text-sm text-muted">{L.savedFull}</p>}
      {fields.length === 0 && storageOk && <p className="mt-2 text-muted">{L.noFields}</p>}

      <ul className="mt-3 space-y-2">
        {fields.map((f) => {
          const st = status[f.id] ?? { state: "loading" };
          const active = f.id === selectedId;
          return (
            <li key={f.id} className={`flex items-stretch gap-2 rounded-md border ${active ? "border-primary bg-primary-soft" : "border-border"}`}>
              <button
                type="button"
                onClick={() => onSelect(f)}
                aria-pressed={active}
                className="min-h-11 flex-1 px-3 py-2 text-left"
              >
                <span className="block font-semibold">{f.name}</span>
                <FieldStatus st={st} L={L} />
              </button>
              <button
                type="button"
                onClick={() => onRemove(f)}
                aria-label={`${L.removeField}: ${f.name}`}
                title={L.removeField}
                className="min-h-11 min-w-11 rounded-r-md px-3 text-muted hover:text-destructive"
              >
                ✕
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function FieldStatus({ st, L }: { st: Status; L: Labels }) {
  if (st.state === "loading") return <span className="block text-sm text-muted">{L.statusLoading}</span>;
  if (st.state === "error") return <span className="block text-sm text-destructive">{L.statusFailed}: {st.message}</span>;
  const d = st.data;
  const next = d.spray?.next;
  return (
    <span className="block text-sm">
      <span className="text-muted">{L.nextSpray}: </span>
      {d.spray == null ? (
        <span className="text-destructive">{d.sources.forecast.error ?? L.statusFailed}</span>
      ) : next ? (
        <span className="text-primary">
          {fmtLocal(next.start)} – {next.end.slice(11, 16)}
        </span>
      ) : (
        <span>{L.noSprayShort}</span>
      )}
      {d.warnings.map((w) => (
        <span key={w.id} className="ml-2 inline-block rounded bg-amber-soft px-1.5 text-amber">
          ⚠ {L.status[w.id] ?? L.rule[w.id] ?? w.id}
        </span>
      ))}
      {d.sources.forecast.fetched_at && (
        <span className="block text-muted">
          {d.sources.forecast.name} · {L.fetched} {fmtLocal(d.sources.forecast.fetched_at)}
          {d.sources.forecast.stale ? ` (${L.staleTag})` : ""}
        </span>
      )}
    </span>
  );
}
