"use client";

import { useEffect, useId, useState, useSyncExternalStore } from "react";
import { SpeakerIcon, StopIcon } from "./Icons";
import type { Labels } from "@/lib/i18n";
import * as speech from "@/lib/speech";
import type { Lang } from "@/lib/types";

const VOICE_WAIT_MS = 1500; // some browsers fill the voice list late; give up waiting after this
const subscribeNothing = () => () => {};

/** Listen / Stop for one answer. Speaks in the answer's language only; says so if the device lacks that voice. */
export default function ListenButton({ text, lang, L }: { text: string; lang: Lang; L: Labels }) {
  const id = useId();
  const supported = useSyncExternalStore(subscribeNothing, speech.supported, () => false);
  const voices = useSyncExternalStore(speech.subscribeVoices, speech.voicesKey, () => "");
  const owner = useSyncExternalStore(speech.subscribeOwner, speech.currentOwner, () => null);
  const [waited, setWaited] = useState(false);
  const speaking = owner === id;

  // The voice list can be empty on first load: wait for "voiceschanged", or give up after a moment.
  useEffect(() => {
    const t = setTimeout(() => setWaited(true), VOICE_WAIT_MS);
    return () => clearTimeout(t);
  }, []);

  // A new answer (different text or language) or leaving the page stops this answer's speech.
  useEffect(
    () => () => {
      if (speech.currentOwner() === id) speech.stop();
    },
    [id, text, lang],
  );

  if (!supported) return null;
  const match = voices ? speech.pickVoice(lang, speechSynthesis.getVoices()) : null;
  const loading = !match && !voices && !waited;
  const unavailable = !match && !loading;

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={() => (speaking ? speech.stop() : speech.speak(text, lang, id))}
        disabled={unavailable || loading}
        aria-pressed={speaking}
        className={`inline-flex min-h-11 items-center gap-2 rounded-md border px-3 font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
          speaking ? "border-accent bg-accent/20 text-foreground" : "border-primary/60 text-primary hover:bg-accent/20"
        }`}
      >
        {speaking ? <StopIcon /> : <SpeakerIcon />}
        <span>{speaking ? L.micStop : L.listen}</span>
      </button>
      {match && <p className="text-sm text-muted-foreground">{speech.voiceLabel(match.code)}</p>}
      {unavailable && (
        <p role="status" className="max-w-xs text-right text-sm text-warning">{speech.noVoiceMessage(lang)}</p>
      )}
    </div>
  );
}
