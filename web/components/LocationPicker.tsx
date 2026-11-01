"use client";

import { useEffect, useState } from "react";
import { PinIcon } from "./Icons";
import { searchPlaces } from "@/lib/api";
import type { Labels } from "@/lib/i18n";
import type { PlaceSuggestion } from "@/lib/types";

export type PickedPlace = { lat: number; lon: number; name: string };

const labelFor = (p: PlaceSuggestion) => (p.district ? `${p.name} (${p.district})` : p.name);

/** Village / town input with Karnataka suggestions and "Use my location". The parent owns the text and
 *  coordinates (saved fields and links set them too); a hint is shown only for the text it was made for. */
export default function LocationPicker({
  value, hasCoords, onChange, L, id = "location",
}: {
  value: string;
  hasCoords: boolean;
  onChange: (value: string, picked: PickedPlace | null) => void;
  L: Labels;
  id?: string;
}) {
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [hint, setHint] = useState<{ text: string; forValue: string }>({ text: "", forValue: "" });

  // Suggestions are debounced and optional; once coordinates are known no lookup is made.
  useEffect(() => {
    const q = value.trim();
    if (q.length < 2 || hasCoords) return;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      searchPlaces(q, ctrl.signal)
        .then((r) => setSuggestions(r.slice(0, 8)))
        .catch(() => {}); // suggestions are a convenience; the main request reports real errors
    }, 350);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [value, hasCoords]);

  const onType = (v: string) => {
    const p = suggestions.find((s) => labelFor(s) === v);
    setHint({ text: p ? `${p.lat.toFixed(3)}, ${p.lon.toFixed(3)}` : "", forValue: v });
    onChange(v, p ? { lat: p.lat, lon: p.lon, name: p.name } : null);
  };

  const useMyLocation = () => {
    if (!navigator.geolocation) return;
    setHint({ text: "…", forValue: value });
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = Number(pos.coords.latitude.toFixed(4));
        const lon = Number(pos.coords.longitude.toFixed(4));
        setHint({ text: "", forValue: "" });
        onChange(`My location (${lat}, ${lon})`, { lat, lon, name: "My location" });
      },
      () => setHint({ text: L.locDenied, forValue: value }),
      { timeout: 10_000 },
    );
  };

  const shown = hint.forValue === value ? hint.text : "";
  return (
    <>
      <label htmlFor={id} className="mb-1.5 block font-semibold">{L.location}</label>
      <div className="flex gap-2">
        <input
          id={id}
          list={`${id}-places`}
          value={value}
          onChange={(e) => onType(e.target.value)}
          required
          maxLength={80}
          className="min-h-11 w-full min-w-0 rounded-md border border-border bg-background px-3"
        />
        <button
          type="button"
          onClick={useMyLocation}
          title={L.useLocation}
          aria-label={L.useLocation}
          className="min-h-11 min-w-11 rounded-md border border-border bg-background px-3 text-muted-foreground hover:border-primary hover:text-primary"
        >
          <PinIcon />
        </button>
      </div>
      <datalist id={`${id}-places`}>
        {suggestions.map((p) => <option key={`${p.lat},${p.lon}`} value={labelFor(p)} />)}
      </datalist>
      {shown && <small className="mt-1 block text-sm text-muted-foreground">{shown}</small>}
    </>
  );
}
