// Voice input: record with the microphone, convert to 16 kHz mono WAV in the browser,
// and let the backend (Gemini) transcribe it. This works the same in Chrome, Edge,
// Firefox, Safari and Brave, and handles Kannada and Hindi, unlike the browser's
// built-in SpeechRecognition.
// Voice output: the browser's speechSynthesis, shown only when a voice for the language exists.
import type { Lang } from "./types";

export const MAX_RECORD_SECONDS = 30;
const TARGET_RATE = 16_000;
// Peak level (0..1) a recording must reach to count as speech; below this the mic is
// probably muted or the wrong input device is selected.
const SILENCE_PEAK = 0.04;

export type RecordError = "denied" | "no-device" | "unsupported" | "silent" | "too-short" | "failed";

export class VoiceError extends Error {
  constructor(public code: RecordError) {
    super(code);
  }
}

export function canRecord(): boolean {
  return (
    typeof window !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window.MediaRecorder !== "undefined" &&
    typeof window.AudioContext !== "undefined"
  );
}

export interface Recording {
  /** Stops recording and resolves with a WAV blob, or rejects with VoiceError. */
  stop(): Promise<Blob>;
  /** Stops and discards. */
  cancel(): void;
}

/**
 * Starts recording. onLevel gets the input level (0..1) about 20 times a second so the UI
 * can show that sound is coming in; onAutoStop fires when MAX_RECORD_SECONDS is reached.
 */
export async function startRecording(onLevel: (level: number) => void, onAutoStop: () => void): Promise<Recording> {
  if (!canRecord()) throw new VoiceError("unsupported");
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (err) {
    const name = (err as DOMException).name;
    if (name === "NotAllowedError" || name === "SecurityError") throw new VoiceError("denied");
    if (name === "NotFoundError" || name === "OverconstrainedError") throw new VoiceError("no-device");
    throw new VoiceError("failed");
  }

  // Level meter, also used to detect a silent recording before uploading it.
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  let peak = 0;
  const meter = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let max = 0;
    for (const v of buf) max = Math.max(max, Math.abs(v));
    peak = Math.max(peak, max);
    onLevel(Math.min(1, max * 2.5));
  }, 50);

  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const startedAt = performance.now();
  recorder.start();
  const autoStop = setTimeout(onAutoStop, MAX_RECORD_SECONDS * 1000);

  const cleanup = () => {
    clearInterval(meter);
    clearTimeout(autoStop);
    stream.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => {});
  };

  return {
    stop: () =>
      new Promise<Blob>((resolve, reject) => {
        recorder.onstop = async () => {
          cleanup();
          if (performance.now() - startedAt < 600) return reject(new VoiceError("too-short"));
          if (peak < SILENCE_PEAK) return reject(new VoiceError("silent"));
          try {
            const recorded = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
            resolve(await toWav(recorded));
          } catch {
            reject(new VoiceError("failed"));
          }
        };
        if (recorder.state !== "inactive") recorder.stop();
        else recorder.onstop?.(new Event("stop"));
      }),
    cancel: () => {
      recorder.onstop = null;
      if (recorder.state !== "inactive") recorder.stop();
      cleanup();
    },
  };
}

/** Decodes whatever the browser recorded (webm/ogg/mp4) and re-encodes as 16 kHz mono 16-bit WAV. */
async function toWav(blob: Blob): Promise<Blob> {
  const decodeCtx = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await decodeCtx.decodeAudioData(await blob.arrayBuffer());
  } finally {
    decodeCtx.close().catch(() => {});
  }
  const length = Math.max(1, Math.ceil(decoded.duration * TARGET_RATE));
  const offline = new OfflineAudioContext(1, length, TARGET_RATE);
  const src = offline.createBufferSource();
  src.buffer = decoded; // multi-channel input is down-mixed to mono by the destination
  src.connect(offline.destination);
  src.start();
  const pcm = (await offline.startRendering()).getChannelData(0);

  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const str = (off: number, s: string) => [...s].forEach((c, i) => out.setUint8(off + i, c.charCodeAt(0)));
  str(0, "RIFF");
  out.setUint32(4, 36 + pcm.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  out.setUint32(16, 16, true); // PCM chunk size
  out.setUint16(20, 1, true); // PCM
  out.setUint16(22, 1, true); // mono
  out.setUint32(24, TARGET_RATE, true);
  out.setUint32(28, TARGET_RATE * 2, true); // byte rate
  out.setUint16(32, 2, true); // block align
  out.setUint16(34, 16, true); // bits per sample
  str(36, "data");
  out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) {
    const v = Math.max(-1, Math.min(1, pcm[i]));
    out.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([out], { type: "audio/wav" });
}

// ---- voice output ----------------------------------------------------------

const SPEECH_LANG: Record<Lang, string> = { en: "en-IN", hi: "hi-IN", kn: "kn-IN" };

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

export function stopSpeaking() {
  if (typeof window !== "undefined" && "speechSynthesis" in window) speechSynthesis.cancel();
}

/** Voices load asynchronously in Chrome; call back when they arrive. */
export function onVoicesReady(cb: () => void): () => void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return () => {};
  speechSynthesis.addEventListener("voiceschanged", cb);
  return () => speechSynthesis.removeEventListener("voiceschanged", cb);
}
