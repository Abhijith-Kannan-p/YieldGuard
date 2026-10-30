"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ApiError, transcribe } from "@/lib/api";
import type { Labels } from "@/lib/i18n";
import type { Lang } from "@/lib/types";
import * as voice from "@/lib/voice";
import { MicIcon, Spinner, StopIcon } from "./Icons";

type State = "idle" | "starting" | "recording" | "working";

const ERROR_LABEL: Record<voice.RecordError, keyof Labels> = {
  denied: "micDenied",
  "no-device": "micNoDevice",
  unsupported: "micUnsupported",
  silent: "micSilent",
  "too-short": "micTooShort",
  failed: "micFailed",
};

const subscribeNothing = () => () => {};

/**
 * "Speak" button: tap to record, tap "Stop" to finish (auto-stops after MAX_RECORD_SECONDS).
 * The recording is transcribed by the backend and passed to onText.
 */
export default function MicButton({
  lang,
  L,
  onText,
}: {
  lang: "auto" | Lang;
  L: Labels;
  onText: (text: string, language: Lang | null) => void;
}) {
  const supported = useSyncExternalStore(subscribeNothing, voice.canRecord, () => false);
  const [state, setState] = useState<State>("idle");
  const [level, setLevel] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [message, setMessage] = useState<{ text: string; tone: "muted" | "error" } | null>(null);
  const rec = useRef<voice.Recording | null>(null);
  const abort = useRef<AbortController | null>(null);

  // Cancel any recording or upload when the page unmounts.
  useEffect(
    () => () => {
      rec.current?.cancel();
      abort.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (state !== "recording") return;
    const started = Date.now();
    const t = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 250);
    return () => clearInterval(t);
  }, [state]);

  const fail = (key: keyof Labels | null, text?: string) => {
    setState("idle");
    setLevel(0);
    setMessage({ text: text ?? (L[key!] as string), tone: "error" });
  };

  const stop = async () => {
    const r = rec.current;
    rec.current = null;
    if (!r) return;
    setState("working");
    setLevel(0);
    setMessage({ text: L.micWorking, tone: "muted" });
    let wav: Blob;
    try {
      wav = await r.stop();
    } catch (err) {
      return fail(ERROR_LABEL[(err as voice.VoiceError).code] ?? "micFailed");
    }
    abort.current = new AbortController();
    const timer = setTimeout(() => abort.current?.abort(), 45_000);
    try {
      const res = await transcribe(wav, lang, abort.current.signal);
      if (!res.text) return fail("micEmpty");
      onText(res.text, res.language);
      setState("idle");
      setMessage(null);
    } catch (err) {
      const e = err instanceof ApiError ? err : new ApiError("network", "network");
      fail(null, e.kind === "server" ? e.message : e.kind === "timeout" ? L.timeout : L.network);
    } finally {
      clearTimeout(timer);
    }
  };

  const start = async () => {
    setMessage(null);
    setSeconds(0);
    setState("starting");
    voice.stopSpeaking();
    try {
      rec.current = await voice.startRecording(setLevel, () => void stop());
      setState("recording");
      setMessage({ text: L.micRecording, tone: "muted" });
    } catch (err) {
      fail(ERROR_LABEL[(err as voice.VoiceError).code] ?? "micFailed");
    }
  };

  if (!supported) return null;

  const recording = state === "recording";
  const busy = state === "starting" || state === "working";

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={recording ? () => void stop() : () => void start()}
        disabled={busy}
        aria-pressed={recording}
        className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-semibold transition disabled:cursor-progress disabled:opacity-70 ${
          recording
            ? "border-destructive bg-destructive-soft text-foreground"
            : "border-primary/60 text-primary hover:bg-primary/10"
        }`}
      >
        {busy ? <Spinner /> : recording ? <StopIcon /> : <MicIcon />}
        <span>{recording ? L.micStop : L.micSpeak}</span>
        {recording && (
          <>
            <span className="tabular-nums text-muted">
              0:{String(seconds).padStart(2, "0")} / 0:{voice.MAX_RECORD_SECONDS}
            </span>
            {/* Input level, so the farmer can see the microphone is hearing them. */}
            <span className="flex h-4 items-end gap-0.5" aria-hidden="true">
              {[0.15, 0.35, 0.55, 0.75].map((th) => (
                <span
                  key={th}
                  className={`w-1 rounded-sm ${level > th ? "bg-primary" : "bg-border"}`}
                  style={{ height: `${25 + th * 100}%` }}
                />
              ))}
            </span>
          </>
        )}
      </button>
      {message && (
        <p
          role={message.tone === "error" ? "alert" : "status"}
          className={`max-w-md text-right text-xs ${message.tone === "error" ? "text-destructive" : "text-muted"}`}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}
