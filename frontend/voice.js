// Optional voice input/output using the browser's Web Speech API.
// Buttons stay hidden when the browser (or a voice for the language) is not available,
// so the app falls back to text without errors.
const SPEECH_LANG = { en: "en-IN", hi: "hi-IN", kn: "kn-IN" };

const Voice = {
  Recognition: window.SpeechRecognition || window.webkitSpeechRecognition || null,
  rec: null,

  canListen() {
    return !!this.Recognition;
  },

  listen(lang, onText, onState) {
    if (!this.canListen()) return;
    if (this.rec) { this.rec.abort(); this.rec = null; onState("idle"); return; }
    const rec = new this.Recognition();
    rec.lang = SPEECH_LANG[lang] || "en-IN";
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      const text = Array.from(e.results).map((r) => r[0].transcript).join(" ");
      onText(text, e.results[e.results.length - 1].isFinal);
    };
    rec.onerror = (e) => onState(e.error === "not-allowed" || e.error === "service-not-allowed" ? "denied" : "error");
    rec.onend = () => { this.rec = null; onState("idle"); };
    this.rec = rec;
    onState("listening");
    rec.start();
  },

  voiceFor(lang) {
    if (!("speechSynthesis" in window)) return null;
    const code = SPEECH_LANG[lang] || "en-IN";
    const voices = speechSynthesis.getVoices();
    return voices.find((v) => v.lang === code) || voices.find((v) => v.lang.startsWith(code.slice(0, 2))) || null;
  },

  canSpeak(lang) {
    return !!this.voiceFor(lang);
  },

  speak(text, lang) {
    const voice = this.voiceFor(lang);
    if (!voice) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.voice = voice;
    u.lang = voice.lang;
    u.rate = 0.95;
    speechSynthesis.speak(u);
  },
};

// Voices load asynchronously in Chrome.
if ("speechSynthesis" in window) {
  speechSynthesis.onvoiceschanged = () => document.dispatchEvent(new Event("voices-ready"));
}
