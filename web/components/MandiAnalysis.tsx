"use client";

import { useState } from "react";
import { Cites } from "./AdviceResult";
import { SourceLine } from "./MandiView";
import { ApiError, postMandiAnalysis, REQUEST_TIMEOUT_MS } from "@/lib/api";
import { fetchForecast, SOURCE_NAME, type BrowserForecast } from "@/lib/forecastClient";
import { fmtFetched } from "@/lib/format";
import { fill, type Labels } from "@/lib/i18n";
import type { DataPoint, Lang, MandiAnalysisResponse, MandiPageResponse } from "@/lib/types";

const SECTION = "rounded-md border border-border bg-card p-4";

/** The analysis: summary, cited sections, number check, missing data and the sources it used. */
export function AnalysisView({ res, L }: { res: MandiAnalysisResponse; L: Labels }) {
  const points = new Map<string, DataPoint>(res.data_points.map((p) => [p.id, p]));
  const a = res.analysis;
  return (
    <div className="grid gap-3">
      <p data-generated-by={res.generated_by} className="text-sm text-muted-foreground">
        {L.generatedBy}: {res.generated_by === "rules-fallback" ? L.fallbackNote : res.generated_by} ·{" "}
        {fmtFetched(res.generated_at)}
        {res.served_from_cache && <span data-cached> · {fill(L.analysisCached, { time: fmtFetched(res.generated_at) })}</span>}
      </p>
      <p className="text-lg font-semibold">{a.summary}</p>
      {a.sections.map((s, i) => (
        <div key={`${i}-${s.title}`} data-analysis-section className="border-t border-border pt-3">
          <h3 className="font-bold">{s.title}</h3>
          <p className="mt-1">{s.text}</p>
          <Cites ids={s.evidence} points={points} L={L} />
        </div>
      ))}
      {res.unverified_numbers.length > 0 && (
        <p data-unverified className="rounded-md border border-warning bg-warning-soft p-2">
          {L.unverified} {res.unverified_numbers.join(", ")}
        </p>
      )}
      {a.missing_data.length > 0 && (
        <p className="text-muted-foreground">{L.missing} {a.missing_data.join("; ")}</p>
      )}
      <p className="text-sm text-muted-foreground">{a.disclaimer}</p>
      <div className="grid gap-1 border-t border-border pt-3">
        {res.sources.map((s) => <SourceLine key={s.id} s={s} L={L} />)}
      </div>
    </div>
  );
}

type State = { s: "idle" } | { s: "loading" } | { s: "ok"; d: MandiAnalysisResponse } | { s: "error"; msg: string };

/** Under the price card: nothing is requested until the farmer taps Analyse. */
export default function MandiAnalysisPanel({ res, lang, L }: { res: MandiPageResponse; lang: Lang; L: Labels }) {
  const [state, setState] = useState<State>({ s: "idle" });

  const analyse = async () => {
    setState({ s: "loading" });
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
    const { name, lat, lon } = res.location;
    try {
      // The forecast is fetched here in the browser, as on the advice page.
      const forecast = await fetchForecast(lat, lon);
      const body = { crop: res.commodity ?? res.crop_word, location: name, lat, lon, lang, forecast };
      const d = await postMandiAnalysis(body, ctrl.signal).catch((e: unknown) => {
        if (!(e instanceof ApiError && e.code === "invalid_forecast")) throw e;
        // The server rejected the browser's forecast (e.g. a wrong device clock): ask once more without it.
        const failed: BrowserForecast = { ok: false, status: null, error: `rejected: ${e.message}`.slice(0, 250), source: SOURCE_NAME };
        return postMandiAnalysis({ ...body, forecast: failed }, ctrl.signal);
      });
      setState({ s: "ok", d });
    } catch (err) {
      const ae = err instanceof ApiError ? err : new ApiError("network", "network");
      setState({ s: "error", msg: ae.kind === "timeout" ? L.timeout : ae.kind === "network" ? L.network : ae.message });
    } finally {
      clearTimeout(timer);
    }
  };

  return (
    <section data-section="mandi-analysis" aria-label={L.analysisTitle} aria-live="polite" className={SECTION}>
      <h2 className="text-lg font-bold">{L.analysisTitle}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{L.analysisIntro}</p>
      {state.s !== "ok" && (
        <>
          {state.s === "idle" && <p className="mt-3">{L.analysisHint}</p>}
          {state.s === "error" && (
            <div role="alert" className="mt-3 rounded-md border border-destructive bg-destructive-soft p-3">
              <p className="font-semibold text-destructive-text">{L.analysisFailed}</p>
              <p className="mt-1">{state.msg}</p>
            </div>
          )}
          <button
            type="button"
            data-analyse
            onClick={analyse}
            disabled={state.s === "loading"}
            className="mt-3 min-h-12 rounded-md bg-primary px-5 text-lg font-bold text-primary-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-progress disabled:opacity-60"
          >
            {state.s === "loading" ? L.analysing : L.analyse}
          </button>
        </>
      )}
      {state.s === "ok" && (
        <div className="mt-3">
          <AnalysisView res={state.d} L={L} />
        </div>
      )}
    </section>
  );
}
