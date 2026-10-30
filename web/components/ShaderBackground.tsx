/**
 * ShaderBackground – a static (non-animated) mesh-gradient WebGL canvas.
 *
 * Rendering uses Paper Shaders (@paper-design/shaders-react, StaticMeshGradient),
 * Copyright Paper Design, licensed under the Apache License, Version 2.0.
 * https://github.com/paper-design/shaders  ·  http://www.apache.org/licenses/LICENSE-2.0
 *
 * Usage: render with className="absolute inset-0 -z-10" inside a relative container.
 * If WebGL is unavailable the canvas stays empty and the container's background shows.
 */
"use client";

import { StaticMeshGradient } from "@paper-design/shaders-react";

// Sage Garden palette: near-black, deep moss, sage primary, pale sage highlight.
const COLORS = ["#111111", "#1f2d24", "#7d9a86", "#3f5a48", "#c9d8cc"];

export default function ShaderBackground({ className }: { className?: string }) {
  return (
    <div className={className} aria-hidden="true">
      <StaticMeshGradient
        colors={COLORS}
        positions={42}
        waveX={0.6}
        waveXShift={0.2}
        waveY={0.45}
        waveYShift={0.7}
        mixing={0.55}
        grainMixer={0.08}
        grainOverlay={0.06}
        fit="cover"
        speed={0}
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
