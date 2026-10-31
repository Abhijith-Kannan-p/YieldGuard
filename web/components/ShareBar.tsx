"use client";

import { useState } from "react";
import { fmtFetched } from "@/lib/format";
import type { Labels } from "@/lib/i18n";
import type { AdviceResponse } from "@/lib/types";

/** Plain-text summary in the answer's language: place, advice, fetch times and sources. */
export function summaryText(res: AdviceResponse, L: Labels): string {
  const loc = [res.location.name, res.location.district].filter(Boolean).join(", ");
  const fetched = res.sources
    .filter((s) => s.status === "ok" && s.id !== "user")
    .map((s) => `${s.name}: ${fmtFetched(s.fetched_at)}`);
  return [
    `YieldGuard · ${loc}`,
    "",
    `${L.sumAdvice}: ${res.answer.text}`,
    ...res.answer.recommendations.map((r) => `- ${r.text}`),
    "",
    res.answer.disclaimer,
    "",
    `${L.sumFetched}:`,
    ...fetched.map((f) => `- ${f}`),
    `${L.sumSources}: Open-Meteo.com (CC BY 4.0), ISRIC SoilGrids v2.0 (CC BY 4.0)`,
  ].join("\n");
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Older browsers / insecure context: fall back to a hidden textarea.
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

export default function ShareBar({ res, L }: { res: AdviceResponse; L: Labels }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const text = summaryText(res, L);

  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={async () => setState((await copyText(text)) ? "copied" : "failed")}
          className="inline-flex min-h-11 items-center rounded-md border border-primary/60 px-4 font-semibold text-primary hover:bg-accent/20"
        >
          {state === "copied" ? `✓ ${L.copied}` : L.copySummary}
        </button>
        <a
          href={`https://wa.me/?text=${encodeURIComponent(text)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-11 items-center rounded-md border border-primary/60 px-4 font-semibold text-primary hover:bg-accent/20"
        >
          {L.shareWhatsapp}
        </a>
      </div>
      {state === "failed" && (
        <>
          <p role="alert" className="mt-2 text-sm text-destructive-text">{L.copyFailed}</p>
          <textarea readOnly value={text} rows={6} className="mt-2 w-full rounded-md border border-border bg-background p-2 text-sm" />
        </>
      )}
    </div>
  );
}
