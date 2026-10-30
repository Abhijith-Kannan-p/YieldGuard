(() => {
  const $ = (id) => document.getElementById(id);
  const REQUEST_TIMEOUT_MS = 90000;
  const SLOW_AFTER_MS = 9000;

  const state = {
    uiLang: "en",
    suggestions: new Map(), // datalist label -> {name, lat, lon}
    coords: null,           // {lat, lon, name} from geolocation or a picked suggestion
    lastAnswer: null,
  };

  // ---------- helpers ----------------------------------------------------
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function fmtLocal(iso) {
    // "2026-10-31T11:00" (already local IST) -> "31 Oct, 11:00"
    if (!iso) return "";
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso);
    if (!m) return iso;
    const day = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
    return m[4] ? `${day}, ${m[4]}:${m[5]}` : day;
  }

  function fmtSpan(s) {
    if (!s) return "";
    return String(s).replace(/\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?/g, (x) => fmtLocal(x));
  }

  function fmtFetched(iso) {
    return iso ? `${fmtLocal(iso)} IST` : "";
  }

  function fmtValue(p) {
    if (p.value == null) return "–";
    if (typeof p.value === "string") return fmtSpan(p.value);
    return `${p.value}${p.unit ? (p.unit === "%" || p.unit === "°" ? "" : " ") + p.unit : ""}`;
  }

  function node(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function L(key) {
    return t(state.uiLang, key);
  }

  // ---------- language ---------------------------------------------------
  function setUiLang(lang) {
    state.uiLang = I18N[lang] ? lang : "en";
    applyI18n(state.uiLang);
    renderExamples();
    updateVoiceButtons();
  }

  function renderExamples() {
    const box = $("examples");
    box.textContent = "";
    L("examples").forEach((q) => {
      const b = node("button", "chip", q);
      b.type = "button";
      b.addEventListener("click", () => { $("question").value = q; $("question").focus(); });
      box.appendChild(b);
    });
  }

  $("lang").addEventListener("change", (e) => setUiLang(e.target.value === "auto" ? "en" : e.target.value));

  // ---------- location search --------------------------------------------
  let searchTimer = null;
  $("location").addEventListener("input", (e) => {
    const q = e.target.value.trim();
    state.coords = state.suggestions.get(e.target.value) || null;
    $("loc-hint").textContent = state.coords ? `${state.coords.lat.toFixed(3)}, ${state.coords.lon.toFixed(3)}` : "";
    clearTimeout(searchTimer);
    if (q.length < 2 || state.coords) return;
    searchTimer = setTimeout(() => searchPlaces(q), 350);
  });

  async function searchPlaces(q) {
    try {
      const r = await fetch(`/api/locations?q=${encodeURIComponent(q)}`);
      if (!r.ok) return;
      const data = await r.json();
      const list = $("places");
      list.textContent = "";
      state.suggestions.clear();
      data.results.slice(0, 8).forEach((p) => {
        const label = p.district ? `${p.name} (${p.district})` : p.name;
        state.suggestions.set(label, { name: p.name, lat: p.lat, lon: p.lon });
        const opt = document.createElement("option");
        opt.value = label;
        list.appendChild(opt);
      });
    } catch (_) { /* suggestions are optional */ }
  }

  $("geo").addEventListener("click", () => {
    if (!navigator.geolocation) return;
    $("loc-hint").textContent = "…";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = Number(pos.coords.latitude.toFixed(4));
        const lon = Number(pos.coords.longitude.toFixed(4));
        state.coords = { lat, lon, name: "My location" };
        $("location").value = `My location (${lat}, ${lon})`;
        $("loc-hint").textContent = "";
      },
      () => { $("loc-hint").textContent = "Location permission denied – type a place name."; },
      { timeout: 10000 },
    );
  });

  // ---------- voice ------------------------------------------------------
  function currentLang() {
    const sel = $("lang").value;
    return sel === "auto" ? state.uiLang : sel;
  }

  function updateVoiceButtons() {
    $("mic").hidden = !Voice.canListen();
    $("speak").hidden = !(state.lastAnswer && Voice.canSpeak(state.lastAnswer.language));
  }
  document.addEventListener("voices-ready", updateVoiceButtons);

  $("mic").addEventListener("click", () => {
    Voice.listen(currentLang(), (text) => { $("question").value = text; }, (s) => {
      $("mic").classList.toggle("on", s === "listening");
      $("status").textContent = s === "listening" ? L("listening") : s === "denied" ? L("micDenied") : "";
    });
  });

  $("speak").addEventListener("click", () => {
    const a = state.lastAnswer;
    if (!a) return;
    const text = [a.answer.text, ...a.answer.recommendations.map((r) => r.text), a.answer.disclaimer].join(" ");
    Voice.speak(text, a.language);
  });

  // ---------- connectivity -----------------------------------------------
  const syncOnline = () => { $("offline").hidden = navigator.onLine; };
  window.addEventListener("online", syncOnline);
  window.addEventListener("offline", syncOnline);
  syncOnline();

  // ---------- submit -----------------------------------------------------
  $("ask").addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = $("question").value.trim();
    const locText = $("location").value.trim();
    if (!question || !locText) return;

    const params = new URLSearchParams({ q: question, lang: $("lang").value });
    const picked = state.coords || state.suggestions.get(locText);
    if (picked) {
      params.set("lat", picked.lat);
      params.set("lon", picked.lon);
      params.set("location", picked.name);
    } else {
      params.set("location", locText);
    }

    $("error").hidden = true;
    $("submit").disabled = true;
    $("status").textContent = L("loading");
    const slowTimer = setTimeout(() => { $("status").textContent = L("slow"); }, SLOW_AFTER_MS);
    const thinkTimer = setTimeout(() => { $("status").textContent = L("thinking"); }, 4000);
    const ctrl = new AbortController();
    const abortTimer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);

    try {
      const r = await fetch(`/api/advice?${params}`, { signal: ctrl.signal });
      let body = null;
      try { body = await r.json(); } catch (_) { /* non-JSON error page */ }
      if (!r.ok) {
        showError((body && body.error && body.error.message) || `Server error (${r.status}). Please try again.`);
        return;
      }
      render(body);
    } catch (err) {
      showError(err.name === "AbortError" ? L("timeout") : L("network"));
    } finally {
      clearTimeout(slowTimer);
      clearTimeout(thinkTimer);
      clearTimeout(abortTimer);
      $("submit").disabled = false;
      $("status").textContent = "";
    }
  });

  function showError(msg) {
    $("error").textContent = msg;
    $("error").hidden = false;
    $("error").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ---------- render -----------------------------------------------------
  function render(res) {
    state.lastAnswer = res;
    if ($("lang").value === "auto") setUiLang(res.language);
    const points = Object.fromEntries(res.data_points.map((p) => [p.id, p]));

    // warnings
    const warn = $("warnings");
    warn.textContent = "";
    res.warnings.forEach((w) => warn.appendChild(node("div", "banner banner-warn", w)));
    if (res.unverified_numbers.length) {
      warn.appendChild(node("div", "banner banner-warn", `${L("unverified")} ${res.unverified_numbers.join(", ")}`));
    }

    // answer
    const loc = res.location;
    $("place").textContent = `📍 ${loc.name}${loc.district ? ", " + loc.district : ""} · ${loc.lat.toFixed(3)}, ${loc.lon.toFixed(3)}`
      + ` · ${loc.source}${loc.fetched_at ? " · " + L("fetched") + " " + fmtFetched(loc.fetched_at) : ""}`;
    $("answer-text").textContent = res.answer.text;

    const recs = $("recs");
    recs.textContent = "";
    res.answer.recommendations.forEach((r) => recs.appendChild(itemWithCites(r, points)));

    const why = $("why");
    why.textContent = "";
    res.answer.why.forEach((r) => why.appendChild(itemWithCites(r, points)));

    $("missing").hidden = !res.answer.missing_data.length;
    $("missing").textContent = `${L("missing")} ${res.answer.missing_data.join("; ")}`;
    $("disclaimer").textContent = res.answer.disclaimer;
    const by = res.generated_by === "rules-fallback" ? L("fallbackNote") : res.generated_by;
    $("meta").textContent = `${L("generatedBy")}: ${by} · ${fmtFetched(res.generated_at)} · ${res.elapsed_ms} ms · id ${res.request_id}`;

    // chart
    const sprayRule = res.rules.find((r) => r.id === "spray_window");
    const hasChart = renderChart($("chart"), res.forecast_hourly, res.spray_windows, sprayRule && sprayRule.thresholds);
    $("chart").closest(".card").hidden = !hasChart;
    if (hasChart) {
      $("chart-src").textContent = `${res.forecast_hourly.source} · ${L("fetched")} ${fmtFetched(res.forecast_hourly.fetched_at)}`;
    }

    renderRules(res.rules, points);
    renderTable(res.data_points);
    renderSources(res.sources);

    $("result").hidden = false;
    updateVoiceButtons();
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function itemWithCites(item, points) {
    const li = node("li");
    li.appendChild(node("div", null, item.text));
    if (!item.evidence.length) {
      li.appendChild(node("div", "uncited", L("noCite")));
      return li;
    }
    const box = node("div", "cite");
    item.evidence.forEach((id) => {
      const p = points[id];
      if (!p) return;
      const chip = node("span");
      chip.appendChild(node("b", null, `${p.label}: ${fmtValue(p)}`));
      const when = p.valid_time ? ` · ${fmtSpan(p.valid_time)}` : "";
      chip.appendChild(document.createTextNode(`${when} · ${p.source} · ${L("fetched")} ${fmtFetched(p.fetched_at)}`));
      box.appendChild(chip);
    });
    li.appendChild(box);
    return li;
  }

  const RULE_CLASS = {
    found: "good", ok: "good", normal: "good",
    warning: "alert", drought_risk: "alert", waterlogging_risk: "alert",
    none: "caution", flags: "caution",
  };

  function renderRules(rules, points) {
    const box = $("rules");
    box.textContent = "";
    rules.forEach((r) => {
      const card = node("div", `rule ${RULE_CLASS[r.status] || ""}`);
      const h = node("h4", null, r.name);
      h.appendChild(node("span", "pill", r.status.replace(/_/g, " ")));
      card.appendChild(h);
      card.appendChild(node("p", null, r.summary));
      const vals = r.evidence.map((id) => points[id]).filter(Boolean)
        .map((p) => `${p.label}: ${fmtValue(p)}`).join(" · ");
      if (vals) card.appendChild(node("p", "muted small", vals));
      box.appendChild(card);
    });
  }

  function renderTable(dataPoints) {
    const tbody = $("data-rows");
    tbody.textContent = "";
    dataPoints.forEach((p) => {
      const tr = node("tr");
      tr.appendChild(node("td", null, p.label));
      tr.appendChild(node("td", "num", fmtValue(p)));
      tr.appendChild(node("td", null, fmtSpan(p.valid_time) || "–"));
      tr.appendChild(node("td", null, p.source));
      tr.appendChild(node("td", null, `${fmtFetched(p.fetched_at)}${p.cached ? " (" + L("cached") + ")" : ""}`));
      tbody.appendChild(tr);
    });
  }

  function renderSources(sources) {
    const ul = $("sources");
    ul.textContent = "";
    sources.forEach((s) => {
      const li = node("li");
      li.appendChild(node("span", s.status === "ok" ? "ok-dot" : "bad-dot"));
      li.appendChild(node("b", null, s.name));
      const detail = s.status === "ok"
        ? ` · ${L("fetched")} ${fmtFetched(s.fetched_at)}${s.cached ? " (" + L("cached") + ")" : ""}`
        : ` · ${L("failed")}: ${s.error}`;
      li.appendChild(document.createTextNode(detail));
      if (s.attribution) li.appendChild(node("div", "muted small", s.attribution));
      ul.appendChild(li);
    });
  }

  // ---------- init -------------------------------------------------------
  // Shareable links: /?location=Hubballi&q=Can+I+spray&lang=kn fills the form and asks.
  const qs = new URLSearchParams(location.search);
  if (qs.get("lang") && I18N[qs.get("lang")]) $("lang").value = qs.get("lang");
  setUiLang($("lang").value === "auto" ? "en" : $("lang").value);
  if (qs.get("location")) $("location").value = qs.get("location");
  if (qs.get("q")) {
    $("question").value = qs.get("q");
    $("ask").requestSubmit();
  }
})();
