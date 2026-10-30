import type { NextConfig } from "next";

// Static export: `npm run build` writes plain HTML/JS/CSS to web/out, which the
// FastAPI backend serves from the same origin (one Render service, no CORS).
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true, // /advice -> out/advice/index.html
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
