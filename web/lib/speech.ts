// Reading answers aloud with the browser's speechSynthesis.
// - The voice follows the ANSWER's language, not the interface language.
// - If no voice for that language exists on the device, nothing is read (never in another language).
// - Only one utterance plays at a time; starting one cancels the previous one.
import type { Lang } from "./types";

/** Voice language codes to try, in order. English falls back to US English. */
export const SPEECH_CODES: Record<Lang, string[]> = {
  en: ["en-IN", "en-US"],
  hi: ["hi-IN"],
  kn: ["kn-IN"],
};

const LANGUAGE_NAMES: Record<Lang, string> = { en: "English", hi: "Hindi", kn: "Kannada" };

type VoiceLike = Pick<SpeechSynthesisVoice, "lang" | "name">;

const norm = (code: string) => code.replace("_", "-").toLowerCase();

/** The first voice matching the language's codes in order, with the code it matched. */
export function pickVoice<V extends VoiceLike>(lang: Lang, voices: readonly V[]): { voice: V; code: string } | null {
  for (const code of SPEECH_CODES[lang] ?? []) {
    const voice = voices.find((v) => norm(v.lang) === norm(code));
    if (voice) return { voice, code };
  }
  return null;
}

/** "Voice: Hindi (India)" */
export function voiceLabel(code: string): string {
  let name = code;
  try {
    name = new Intl.DisplayNames(["en"], { type: "language", languageDisplay: "standard" }).of(code) ?? code;
  } catch {
    /* very old browsers: show the code */
  }
  return `Voice: ${name}`;
}

/** "Kannada voice is not available on this device. Try another browser or device." */
export function noVoiceMessage(lang: Lang): string {
  return `${LANGUAGE_NAMES[lang]} voice is not available on this device. Try another browser or device.`;
}

// ---- browser side ------------------------------------------------------------

export function supported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

/** Changes whenever the device's voice list changes ("voiceschanged"); the list can be empty at first. */
export function subscribeVoices(cb: () => void): () => void {
  if (!supported()) return () => {};
  speechSynthesis.addEventListener("voiceschanged", cb);
  return () => speechSynthesis.removeEventListener("voiceschanged", cb);
}

export function voicesKey(): string {
  return supported() ? speechSynthesis.getVoices().map((v) => `${v.lang}|${v.name}`).join(",") : "";
}

// Which Listen button is currently speaking (only one at a time across the page).
let owner: string | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function subscribeOwner(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function currentOwner(): string | null {
  return owner;
}

/** Stops any speech, whoever started it. */
export function stop(): void {
  if (supported()) speechSynthesis.cancel();
  if (owner !== null) {
    owner = null;
    emit();
  }
}

/** Speaks `text` in the answer's language. Returns false (and says nothing) if no matching voice exists. */
export function speak(text: string, lang: Lang, ownerId: string): boolean {
  if (!supported()) return false;
  const match = pickVoice(lang, speechSynthesis.getVoices());
  if (!match) return false;
  speechSynthesis.cancel(); // only one utterance at a time
  const u = new SpeechSynthesisUtterance(text);
  u.voice = match.voice;
  u.lang = match.code;
  u.rate = 0.95;
  const done = () => {
    if (owner === ownerId) {
      owner = null;
      emit();
    }
  };
  u.onend = done;
  u.onerror = done;
  owner = ownerId;
  emit();
  speechSynthesis.speak(u);
  return true;
}

// Leaving the page stops speech (some browsers keep talking after navigation otherwise).
if (typeof window !== "undefined") {
  window.addEventListener("pagehide", stop);
}
