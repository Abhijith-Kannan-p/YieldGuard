// Hourly chart: rain probability (bars, right axis %), wind speed (line, left axis km/h),
// rule thresholds (dashed) and safe spray windows (green bands). Plain SVG, no library.
function renderChart(container, series, windows, thresholds) {
  container.textContent = "";
  if (!series || !series.hours || !series.hours.length) return false;

  const hours = series.hours;
  const W = 760, H = 290, padL = 44, padR = 44, padT = 24, padB = 66;
  const iw = W - padL - padR, ih = H - padT - padB;
  const n = hours.length;
  const step = iw / n;
  const winds = hours.map((h) => h.wind_speed_10m);
  const windMax = Math.max(20, Math.ceil(Math.max(...winds.filter((v) => v != null), 0) / 5) * 5);
  const x = (i) => padL + i * step;
  const yWind = (v) => padT + ih - (v / windMax) * ih;
  const yPct = (v) => padT + ih - (v / 100) * ih;
  const idx = Object.fromEntries(hours.map((h, i) => [h.time, i]));

  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Hourly wind speed and rain probability with safe spray windows");
  const el = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    svg.appendChild(e);
    return e;
  };

  // spray windows
  (windows || []).forEach((w) => {
    const i0 = idx[w.start];
    if (i0 == null) return;
    el("rect", { x: x(i0), y: padT, width: w.hours * step, height: ih, fill: "#3c9a4a", opacity: 0.16 });
  });

  // gridlines + axes labels
  [0, 25, 50, 75, 100].forEach((p) => {
    el("line", { x1: padL, x2: W - padR, y1: yPct(p), y2: yPct(p), stroke: "#ebe9e0" });
    el("text", { x: W - padR + 6, y: yPct(p) + 4, "font-size": 11, fill: "#2f6fb3" }, `${p}%`);
  });
  for (let v = 0; v <= windMax; v += windMax / 4) {
    el("text", { x: padL - 6, y: yWind(v) + 4, "font-size": 11, fill: "#c06a1b", "text-anchor": "end" }, Math.round(v));
  }
  el("text", { x: padL - 6, y: padT - 10, "font-size": 10, fill: "#c06a1b", "text-anchor": "end" }, "km/h");

  // rain probability bars
  hours.forEach((h, i) => {
    if (h.precipitation_probability == null) return;
    const y = yPct(h.precipitation_probability);
    el("rect", { x: x(i) + 1, y, width: Math.max(1, step - 2), height: padT + ih - y, fill: "#2f6fb3", opacity: 0.45 });
  });

  // thresholds
  if (thresholds) {
    el("line", { x1: padL, x2: W - padR, y1: yWind(thresholds.max_wind_kmh), y2: yWind(thresholds.max_wind_kmh),
      stroke: "#c06a1b", "stroke-dasharray": "5 4" });
    el("line", { x1: padL, x2: W - padR, y1: yPct(thresholds.max_precip_prob_pct), y2: yPct(thresholds.max_precip_prob_pct),
      stroke: "#2f6fb3", "stroke-dasharray": "5 4" });
  }

  // wind line (gaps where data is missing)
  let d = "";
  let pen = false;
  hours.forEach((h, i) => {
    if (h.wind_speed_10m == null) { pen = false; return; }
    d += `${pen ? "L" : "M"}${(x(i) + step / 2).toFixed(1)},${yWind(h.wind_speed_10m).toFixed(1)}`;
    pen = true;
  });
  el("path", { d, fill: "none", stroke: "#c06a1b", "stroke-width": 2.2 });

  // x axis: day boundaries and every 6 hours
  hours.forEach((h, i) => {
    const hr = Number(h.time.slice(11, 13));
    if (hr === 0 && i > 0) el("line", { x1: x(i), x2: x(i), y1: padT, y2: padT + ih, stroke: "#9a9a8a", "stroke-width": 1 });
    if (hr % 6 === 0) el("text", { x: x(i), y: H - padB + 16, "font-size": 11, fill: "#5d6a5d", "text-anchor": "middle" },
      `${String(hr).padStart(2, "0")}:00`);
    if (hr === 12 || i === 0) el("text", { x: x(i), y: H - padB + 32, "font-size": 11, fill: "#1f2a1f", "font-weight": 600,
      "text-anchor": "middle" }, h.time.slice(8, 10) + "/" + h.time.slice(5, 7));
  });

  // legend
  el("rect", { x: padL, y: H - 14, width: 10, height: 8, fill: "#2f6fb3", opacity: 0.45 });
  el("text", { x: padL + 14, y: H - 6, "font-size": 11, fill: "#5d6a5d" }, "rain chance %");
  el("line", { x1: padL + 110, x2: padL + 128, y1: H - 10, y2: H - 10, stroke: "#c06a1b", "stroke-width": 2.2 });
  el("text", { x: padL + 132, y: H - 6, "font-size": 11, fill: "#5d6a5d" }, "wind km/h");
  el("rect", { x: padL + 210, y: H - 14, width: 10, height: 8, fill: "#3c9a4a", opacity: 0.3 });
  el("text", { x: padL + 224, y: H - 6, "font-size": 11, fill: "#5d6a5d" }, "safe spray window");

  container.appendChild(svg);
  return true;
}
