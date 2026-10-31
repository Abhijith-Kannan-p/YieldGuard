import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { noVoiceMessage, pickVoice, SPEECH_CODES, voiceLabel } from "@/lib/speech";

const v = (lang: string, name = lang) => ({ lang, name });

describe("voice language mapping", () => {
  it("maps answer languages to voice codes", () => {
    expect(SPEECH_CODES).toEqual({ en: ["en-IN", "en-US"], hi: ["hi-IN"], kn: ["kn-IN"] });
  });

  it("picks the voice for the answer's language", () => {
    const voices = [v("en-US"), v("hi-IN", "Google हिन्दी"), v("kn-IN", "Kannada"), v("en-IN")];
    expect(pickVoice("hi", voices)).toEqual({ voice: voices[1], code: "hi-IN" });
    expect(pickVoice("kn", voices)).toEqual({ voice: voices[2], code: "kn-IN" });
    expect(pickVoice("en", voices)).toEqual({ voice: voices[3], code: "en-IN" }); // en-IN preferred
  });

  it("falls back to en-US for English when there is no en-IN voice", () => {
    const voices = [v("en-GB"), v("en-US", "Samantha"), v("fr-FR")];
    expect(pickVoice("en", voices)).toEqual({ voice: voices[1], code: "en-US" });
  });

  it("accepts Android-style codes with an underscore", () => {
    expect(pickVoice("hi", [v("hi_IN")])?.code).toBe("hi-IN");
  });

  it("never reads Hindi or Kannada with a voice for another language", () => {
    const voices = [v("en-IN"), v("en-US"), v("ta-IN"), v("mr-IN")];
    expect(pickVoice("kn", voices)).toBeNull();
    expect(pickVoice("hi", voices)).toBeNull();
    expect(pickVoice("en", [])).toBeNull(); // empty list (voices not loaded yet)
  });
});

describe("messages", () => {
  it("explains when the language's voice is missing", () => {
    expect(noVoiceMessage("kn")).toBe("Kannada voice is not available on this device. Try another browser or device.");
    expect(noVoiceMessage("hi")).toBe("Hindi voice is not available on this device. Try another browser or device.");
  });

  it("names the voice in use", () => {
    expect(voiceLabel("hi-IN")).toBe("Voice: Hindi (India)");
    expect(voiceLabel("kn-IN")).toBe("Voice: Kannada (India)");
    expect(voiceLabel("en-US")).toBe("Voice: English (United States)");
  });
});

describe("speaking", () => {
  const spoken: { text: string; lang: string; voice: string }[] = [];
  let cancels = 0;

  beforeEach(() => {
    spoken.length = 0;
    cancels = 0;
    class Utterance {
      text: string; lang = ""; voice: { name: string } | null = null; rate = 1;
      onend: (() => void) | null = null; onerror: (() => void) | null = null;
      constructor(t: string) { this.text = t; }
    }
    const synth = {
      getVoices: () => [v("en-US", "US"), v("hi-IN", "Hindi")],
      speak: (u: Utterance) => spoken.push({ text: u.text, lang: u.lang, voice: u.voice!.name }),
      cancel: () => { cancels++; },
      addEventListener: () => {}, removeEventListener: () => {},
    };
    vi.stubGlobal("window", { speechSynthesis: synth, SpeechSynthesisUtterance: Utterance, addEventListener: () => {} });
    vi.stubGlobal("speechSynthesis", synth);
    vi.stubGlobal("SpeechSynthesisUtterance", Utterance);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("speaks in the answer's language, one utterance at a time, and refuses missing voices", async () => {
    const speech = await import("@/lib/speech");
    expect(speech.speak("नमस्ते", "hi", "a")).toBe(true);
    expect(spoken.at(-1)).toEqual({ text: "नमस्ते", lang: "hi-IN", voice: "Hindi" });
    expect(speech.currentOwner()).toBe("a");

    const before = cancels;
    expect(speech.speak("Hello", "en", "b")).toBe(true);
    expect(cancels).toBe(before + 1); // the previous utterance was cancelled first
    expect(spoken.at(-1)?.lang).toBe("en-US"); // en-IN missing -> en-US
    expect(speech.currentOwner()).toBe("b");

    expect(speech.speak("ನಮಸ್ಕಾರ", "kn", "c")).toBe(false); // no Kannada voice: nothing is read
    expect(spoken.length).toBe(2);

    speech.stop();
    expect(speech.currentOwner()).toBeNull();
  });
});
