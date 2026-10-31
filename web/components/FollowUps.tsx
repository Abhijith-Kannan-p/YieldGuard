"use client";

import { useRef, useState } from "react";
import { Cites } from "./AdviceResult";
import MicButton from "./MicButton";
import { ApiError, postFollowup } from "@/lib/api";
import { fmtAge, fmtFetched } from "@/lib/format";
import { fill, type Labels } from "@/lib/i18n";
import type { AdviceResponse, DataPoint, FollowupResponse, Lang } from "@/lib/types";

type Item =
  | { id: string; question: string; state: "loading" }
  | { id: string; question: string; state: "done"; data: FollowupResponse }
  | { id: string; question: string; state: "error"; code?: string; message: string };

const BLOCKING = new Set(["data_stale", "followup_limit", "no_session"]);

/** Follow-up questions about one answer. Answered by the server from the data stored with that
 *  answer (session cookie), so no weather or soil API is called. */
export default function FollowUps({
  res, L, lang, onRefresh,
}: {
  res: AdviceResponse;
  L: Labels;
  lang: "auto" | Lang;
  onRefresh: () => void;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [question, setQuestion] = useState("");
  const [used, setUsed] = useState(0);
  const [limit, setLimit] = useState(10);
  const [blocked, setBlocked] = useState<{ code: string; message: string } | null>(null);
  const seq = useRef(0);
  const busy = items.some((i) => i.state === "loading");

  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy || blocked) return;
    const id = `f${++seq.current}`;
    setItems((xs) => [...xs, { id, question: q, state: "loading" }]);
    setQuestion("");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 60_000);
    try {
      const data = await postFollowup(q, lang, ctrl.signal);
      setUsed(data.followups_used);
      setLimit(data.followups_limit);
      setItems((xs) => xs.map((x) => (x.id === id ? { id, question: q, state: "done", data } : x)));
    } catch (err) {
      const ae = err instanceof ApiError ? err : new ApiError("network", "network");
      const message = ae.kind === "timeout" ? L.timeout : ae.kind === "network" ? L.network : ae.message;
      if (ae.code && BLOCKING.has(ae.code)) setBlocked({ code: ae.code, message });
      setItems((xs) => xs.map((x) => (x.id === id ? { id, question: q, state: "error", code: ae.code, message } : x)));
    } finally {
      clearTimeout(timer);
    }
  };

  return (
    <section aria-label={L.followTitle} className="rounded-md border border-border bg-card p-4">
      <h2 className="text-xl font-bold">{L.followTitle}</h2>
      <p className="mt-1 text-muted-foreground">{L.followHint}</p>

      <ol className="mt-3 grid gap-3">
        {items.map((it) => (
          <li key={it.id} className="grid gap-2">
            <p className="justify-self-end rounded-md bg-muted px-3 py-2">
              <span className="block text-sm text-muted-foreground">{L.followYou}</span>
              {it.question}
            </p>
            {it.state === "loading" && <p className="animate-pulse text-muted-foreground">{L.followThinking}</p>}
            {it.state === "error" && !BLOCKING.has(it.code ?? "") && (
              <div role="alert" className="rounded-md border border-destructive bg-destructive-soft p-3">
                <b className="text-destructive-text">{L.followFailed}</b>
                <span className="block">{it.message}</span>
              </div>
            )}
            {it.state === "done" && <FollowupAnswer d={it.data} L={L} />}
          </li>
        ))}
      </ol>

      {blocked && (
        <div role="alert" className="mt-3 rounded-md border border-warning bg-warning-soft p-3">
          <p className="font-semibold text-warning">
            {blocked.code === "data_stale" ? L.staleTitleF : blocked.code === "followup_limit" ? L.limitTitle : L.noSessionTitle}
          </p>
          <p className="mt-1">{blocked.message}</p>
          {blocked.code !== "followup_limit" && (
            <button
              type="button"
              onClick={onRefresh}
              className="mt-2 min-h-11 rounded-md bg-primary px-4 font-semibold text-primary-foreground hover:bg-accent hover:text-accent-foreground"
            >
              {L.refreshData}
            </button>
          )}
        </div>
      )}

      <form onSubmit={ask} className="mt-3">
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <label htmlFor={`followup-${res.request_id}`} className="font-semibold">{L.followTitle}</label>
          <MicButton lang={lang} L={L} onText={(t) => setQuestion(t)} />
        </div>
        <div className="flex gap-2">
          <textarea
            id={`followup-${res.request_id}`}
            rows={2}
            maxLength={1000}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={!!blocked}
            placeholder={L.followPlaceholder}
            className="w-full min-w-0 resize-y rounded-md border border-border bg-background px-3 py-2.5 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={busy || !!blocked || !question.trim()}
            className="min-h-11 rounded-md bg-primary px-5 font-bold text-primary-foreground hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
          >
            {busy ? "…" : L.followAsk}
          </button>
        </div>
        {used > 0 && <p className="mt-2 text-sm text-muted-foreground">{fill(L.followUsed, { used, limit })}</p>}
      </form>
    </section>
  );
}

function FollowupAnswer({ d, L }: { d: FollowupResponse; L: Labels }) {
  const points = new Map<string, DataPoint>(d.evidence_points.map((p) => [p.id, p]));
  return (
    <article className={`rounded-md border p-3 ${d.covered ? "border-border bg-muted" : "border-warning bg-warning-soft"}`}>
      {!d.covered && d.not_covered_message && (
        <p className="mb-2">
          <b className="block text-warning">⚠ {L.notCoveredTitle}</b>
          {d.not_covered_message}
        </p>
      )}
      <p className="text-lg leading-relaxed">{d.answer.text}</p>
      {d.answer.missing_data.length > 0 && <p className="mt-2 text-muted-foreground">{L.missing} {d.answer.missing_data.join("; ")}</p>}
      {d.unverified_numbers.length > 0 && (
        <p className="mt-2 rounded-md border border-warning bg-warning-soft p-2">{L.unverified} {d.unverified_numbers.join(", ")}</p>
      )}
      {d.answer.why.length > 0 && (
        <details open className="mt-3">
          <summary className="min-h-11 cursor-pointer font-semibold">{L.whyAnswer}</summary>
          <ul className="mt-1 list-disc space-y-2 pl-5">
            {d.answer.why.map((w, i) => (
              <li key={i}>
                {w.text}
                {w.evidence.length ? <Cites ids={w.evidence} points={points} L={L} /> : (
                  <span className="block text-sm text-warning">{L.noCite}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="mt-3 rounded-md border border-primary/40 bg-muted p-2 font-semibold">{d.answer.disclaimer}</p>
      <p className="mt-2 text-sm text-muted-foreground">
        {fill(L.basedOn, { time: fmtFetched(d.data_fetched_at), age: fmtAge(d.data_age_minutes, L.ageUnits) })} ·{" "}
        {L.generatedBy}: {d.generated_by} · {fmtFetched(d.generated_at)}
      </p>
    </article>
  );
}
