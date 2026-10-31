"use client";

import { useEffect, useRef } from "react";

/**
 * DataRain: a flow-field particle animation drawn on two canvases (a sharp main layer and a
 * blurred bloom copy), with a vignette and film grain on top. Particles fall through a smooth,
 * slowly changing flow field; each draws a short trail coloured by speed (calm -> mid -> hot)
 * and a small head spark in --dr-core with a soft halo.
 *
 * theme "dark" (default) adds light ("lighter" blending) on a dark page; theme "light" paints
 * with "source-over", a dark --dr-core and a much weaker halo so a light page is not washed out.
 * prefers-reduced-motion: a single still frame is rendered and nothing animates.
 * The root has pointer-events: none, so content above it stays clickable.
 */
export type DataRainPalette = { calm: string; mid: string; hot: string };

const DEFAULT_PALETTE: DataRainPalette = { calm: "var(--dr-calm)", mid: "var(--dr-mid)", hot: "var(--dr-hot)" };
const MAX_DPR = 2;
const STILL_FRAME_STEPS = 140; // simulation steps used to settle the single reduced-motion frame

type P = { x: number; y: number; px: number; py: number; vx: number; vy: number; life: number; spark: boolean };

export default function DataRain({
  theme = "dark",
  count,
  palette = DEFAULT_PALETTE,
  contained = false,
  className = "",
}: {
  theme?: "dark" | "light";
  count?: number; // default: scales with area, up to 7000
  palette?: DataRainPalette; // hex colours or var(--name)
  contained?: boolean; // relative box instead of covering the nearest positioned parent
  className?: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLCanvasElement>(null);
  const bloomRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const root = rootRef.current, main = mainRef.current, bloom = bloomRef.current;
    if (!root || !main || !bloom) return;
    const ctx = main.getContext("2d");
    const bctx = bloom.getContext("2d");
    if (!ctx || !bctx) return;

    const light = theme === "light";
    const css = getComputedStyle(root);
    const resolve = (c: string) => {
      const m = c.match(/^var\((--[\w-]+)\)$/);
      return m ? css.getPropertyValue(m[1]).trim() || "#888" : c;
    };
    const colors = [resolve(palette.calm), resolve(palette.mid), resolve(palette.hot)];
    const core = css.getPropertyValue("--dr-core").trim() || (light ? "#0d3b2e" : "#eafff4");
    const haloAlpha = light ? 0.05 : 0.22;
    const trailFade = light ? 0.075 : 0.09; // how fast old trails disappear

    let w = 0, h = 0, dpr = 1, particles: P[] = [], raf = 0, t = 0, frame = 0;

    const spawn = (p: P | null, anywhere: boolean): P => {
      const x = Math.random() * w;
      const y = anywhere ? Math.random() * h : -10 - Math.random() * 40;
      const q = p ?? ({} as P);
      q.x = q.px = x; q.y = q.py = y; q.vx = 0; q.vy = 0.6 + Math.random() * 0.8;
      q.life = 200 + Math.random() * 400;
      q.spark = Math.random() < 0.06;
      return q;
    };

    const resize = () => {
      const r = root.getBoundingClientRect();
      dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
      w = Math.max(1, r.width); h = Math.max(1, r.height);
      for (const c of [main, bloom]) {
        c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      bctx.setTransform(1, 0, 0, 1, 0, 0);
      const n = count ?? Math.min(7000, Math.round((w * h) / 260));
      particles = Array.from({ length: n }, () => spawn(null, true));
      root.dataset.count = String(n); // visible in dev tools; handy for checking the phone/desktop counts
      ctx.clearRect(0, 0, w, h);
    };

    // Smooth pseudo-noise flow field: mostly downward with a slowly turning sideways drift.
    const field = (x: number, y: number) => {
      const a = Math.sin(x * 0.0042 + t * 0.21) + Math.cos(y * 0.0035 - t * 0.17) + Math.sin((x + y) * 0.0021 + t * 0.09);
      return { fx: Math.sin(a) * 0.9, fy: 1.1 + Math.cos(a * 0.7) * 0.5 };
    };

    const step = (draw: boolean) => {
      t += 0.016;
      if (draw) {
        // Fade the previous frame (works on a transparent canvas for both themes).
        ctx.globalCompositeOperation = "destination-out";
        ctx.fillStyle = `rgba(0,0,0,${trailFade})`;
        ctx.fillRect(0, 0, w, h);
        ctx.globalCompositeOperation = light ? "source-over" : "lighter";
        ctx.lineWidth = 1;
        ctx.lineCap = "round";
      }
      for (const p of particles) {
        const { fx, fy } = field(p.x, p.y);
        p.vx = p.vx * 0.92 + fx * 0.08 * 2;
        p.vy = p.vy * 0.94 + fy * 0.06 * 2;
        p.px = p.x; p.py = p.y;
        p.x += p.vx; p.y += p.vy;
        p.life -= 1;
        if (p.y > h + 10 || p.x < -20 || p.x > w + 20 || p.life <= 0) {
          spawn(p, false);
          continue;
        }
        if (!draw) continue;
        const speed = Math.hypot(p.vx, p.vy);
        const ci = speed < 1.6 ? 0 : speed < 2.3 ? 1 : 2;
        ctx.strokeStyle = colors[ci];
        ctx.globalAlpha = light ? 0.55 : 0.7;
        ctx.beginPath();
        ctx.moveTo(p.px, p.py);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        if (p.spark) {
          ctx.globalAlpha = haloAlpha;
          ctx.fillStyle = colors[ci];
          ctx.beginPath();
          ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = light ? 0.85 : 0.95;
          ctx.fillStyle = core;
          ctx.fillRect(p.x - 0.75, p.y - 0.75, 1.5, 1.5);
        }
      }
      if (draw) {
        ctx.globalAlpha = 1;
        // Bloom layer: a copy of the main canvas, blurred by CSS (.dr-bloom), refreshed every 3 frames.
        if (frame++ % 3 === 0) {
          bctx.clearRect(0, 0, bloom.width, bloom.height);
          bctx.drawImage(main, 0, 0);
        }
      }
    };

    const loop = () => {
      step(true);
      raf = requestAnimationFrame(loop);
    };

    resize();
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      for (let i = 0; i < STILL_FRAME_STEPS; i++) step(i > STILL_FRAME_STEPS - 40);
    } else {
      raf = requestAnimationFrame(loop);
    }

    const ro = new ResizeObserver(() => {
      resize();
      if (reduce) for (let i = 0; i < STILL_FRAME_STEPS; i++) step(i > STILL_FRAME_STEPS - 40);
    });
    ro.observe(root);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [theme, count, palette.calm, palette.mid, palette.hot]);

  return (
    <div
      ref={rootRef}
      aria-hidden="true"
      className={`dr-root ${contained ? "dr-root--contained" : ""} ${theme === "light" ? "dr-root--light" : ""} ${className}`}
    >
      <canvas ref={bloomRef} className="dr-bloom" />
      <canvas ref={mainRef} className="dr-main" />
      <div className="dr-vignette" />
      <div className="dr-grain" />
    </div>
  );
}
