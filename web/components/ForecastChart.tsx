import type { ForecastHour, SprayWindow } from "@/lib/types";

// Hourly chart: rain probability (bars, right axis %), wind speed (line, left axis km/h),
// rule thresholds (dashed) and safe spray windows (sage bands). Plain SVG, no chart library.
export default function ForecastChart({
  hours,
  windows,
  maxWind,
  maxRainProb,
}: {
  hours: ForecastHour[];
  windows: SprayWindow[];
  maxWind?: number;
  maxRainProb?: number;
}) {
  if (!hours.length) return null;

  const W = 760, H = 290, padL = 44, padR = 44, padT = 24, padB = 66;
  const iw = W - padL - padR, ih = H - padT - padB;
  const step = iw / hours.length;
  const winds = hours.map((h) => h.wind_speed_10m).filter((v): v is number => v != null);
  const windMax = Math.max(20, Math.ceil(Math.max(0, ...winds) / 5) * 5);
  const x = (i: number) => padL + i * step;
  const yWind = (v: number) => padT + ih - (v / windMax) * ih;
  const yPct = (v: number) => padT + ih - (v / 100) * ih;
  const idx = new Map(hours.map((h, i) => [h.time, i]));

  let windPath = "";
  let pen = false;
  hours.forEach((h, i) => {
    if (h.wind_speed_10m == null) {
      pen = false;
      return;
    }
    windPath += `${pen ? "L" : "M"}${(x(i) + step / 2).toFixed(1)},${yWind(h.wind_speed_10m).toFixed(1)}`;
    pen = true;
  });

  const MUTED = "#a3a8a4", GRID = "#2a2a2a", RAIN = "#6b9bd1", WIND = "#e5e7e3", SAGE = "#7d9a86";

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Hourly wind speed and rain probability with safe spray windows"
      className="block h-auto w-full min-w-[560px]"
    >
      {windows.map((w) => {
        const i0 = idx.get(w.start);
        if (i0 == null) return null;
        return <rect key={w.start} x={x(i0)} y={padT} width={w.hours * step} height={ih} fill={SAGE} opacity={0.25} />;
      })}

      {[0, 25, 50, 75, 100].map((p) => (
        <g key={p}>
          <line x1={padL} x2={W - padR} y1={yPct(p)} y2={yPct(p)} stroke={GRID} />
          <text x={W - padR + 6} y={yPct(p) + 4} fontSize={11} fill={RAIN}>{`${p}%`}</text>
        </g>
      ))}
      {[0, 1, 2, 3, 4].map((k) => {
        const v = (windMax / 4) * k;
        return (
          <text key={k} x={padL - 6} y={yWind(v) + 4} fontSize={11} fill={WIND} textAnchor="end">
            {Math.round(v)}
          </text>
        );
      })}
      <text x={padL - 6} y={padT - 10} fontSize={10} fill={WIND} textAnchor="end">km/h</text>

      {hours.map((h, i) => {
        if (h.precipitation_probability == null) return null;
        const y = yPct(h.precipitation_probability);
        return (
          <rect key={h.time} x={x(i) + 1} y={y} width={Math.max(1, step - 2)} height={padT + ih - y} fill={RAIN} opacity={0.5} />
        );
      })}

      {maxWind != null && (
        <line x1={padL} x2={W - padR} y1={yWind(maxWind)} y2={yWind(maxWind)} stroke={WIND} strokeDasharray="5 4" opacity={0.7} />
      )}
      {maxRainProb != null && (
        <line x1={padL} x2={W - padR} y1={yPct(maxRainProb)} y2={yPct(maxRainProb)} stroke={RAIN} strokeDasharray="5 4" />
      )}

      <path d={windPath} fill="none" stroke={WIND} strokeWidth={2.2} />

      {hours.map((h, i) => {
        const hr = Number(h.time.slice(11, 13));
        return (
          <g key={`x${h.time}`}>
            {hr === 0 && i > 0 && <line x1={x(i)} x2={x(i)} y1={padT} y2={padT + ih} stroke="#555" />}
            {hr % 6 === 0 && (
              <text x={x(i)} y={H - padB + 16} fontSize={11} fill={MUTED} textAnchor="middle">
                {`${String(hr).padStart(2, "0")}:00`}
              </text>
            )}
            {(hr === 12 || i === 0) && (
              <text x={x(i)} y={H - padB + 32} fontSize={11} fill="#f2f2f0" fontWeight={600} textAnchor="middle">
                {`${h.time.slice(8, 10)}/${h.time.slice(5, 7)}`}
              </text>
            )}
          </g>
        );
      })}

      <rect x={padL} y={H - 14} width={10} height={8} fill={RAIN} opacity={0.5} />
      <text x={padL + 14} y={H - 6} fontSize={11} fill={MUTED}>rain chance %</text>
      <line x1={padL + 110} x2={padL + 128} y1={H - 10} y2={H - 10} stroke={WIND} strokeWidth={2.2} />
      <text x={padL + 132} y={H - 6} fontSize={11} fill={MUTED}>wind km/h</text>
      <rect x={padL + 210} y={H - 14} width={10} height={8} fill={SAGE} opacity={0.5} />
      <text x={padL + 224} y={H - 6} fontSize={11} fill={MUTED}>safe spray window</text>
    </svg>
  );
}
