// Optional voice input/output via the browser's Web Speech API.
// Every function degrades to "not available" so the page stays text-only without errors.
import type { Lang } from "./types";

const SPEECH_LANG: Record<Lang, string> = { en: "en-IN", hi: "hi-IN", kn: "kn-IN" };

/* eslint-disable @typescript-eslint/no-explicit-any */
type Recognition = any;

function recognitionCtor(): (new () => Recognition) | null {
  if (typeof window === "undefined") return null;
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function canListen(): boolean {
  return recognitionCtor() !== null;
}

let active: Recognition | null = null;

export function listen(
  lang: Lang,
  onText: (text: string) => void,
  onState: (s: "listening" | "idle" | "denied" | "error") => void,
) {
  const Ctor = recognitionCtor();
  if (!Ctor) return;
  if (active) {
    active.abort();
    active = null;
    onState("idle");
    return;
  }
  const rec = new Ctor();
  rec.lang = SPEECH_LANG[lang] ?? "en-IN";
  rec.interimResults = true;
  rec.maxAlternatives = 1;
  rec.onresult = (e: any) => onText(Array.from(e.results as ArrayLike<any>).map((r) => r[0].transcript).join(" "));
  rec.onerror = (e: any) =>
    onState(e.error === "not-allowed" || e.error === "service-not-allowed" ? "denied" : "error");
  rec.onend = () => {
    active = null;
    onState("idle");
  };
  active = rec;
  onState("listening");
  try {
    rec.start();
  } catch {
    active = null;
    onState("error");
  }
}
/* eslint-enable @typescript-eslint/no-explicit-any */

function voiceFor(lang: Lang): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  const code = SPEECH_LANG[lang] ?? "en-IN";
  const voices = speechSynthesis.getVoices();
  return voices.find((v) => v.lang === code) || voices.find((v) => v.lang.startsWith(code.slice(0, 2))) || null;
}

export function canSpeak(lang: Lang): boolean {
  return voiceFor(lang) !== null;
}

export function speak(text: string, lang: Lang) {
  const voice = voiceFor(lang);
  if (!voice) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.voice = voice;
  u.lang = voice.lang;
  u.rate = 0.95;
  speechSynthesis.speak(u);
}

/** Voices load asynchronously in Chrome; call back when they arrive. */
export function onVoicesReady(cb: () => void): () => void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return () => {};
  speechSynthesis.addEventListener("voiceschanged", cb);
  return () => speechSynthesis.removeEventListener("voiceschanged", cb);
}
