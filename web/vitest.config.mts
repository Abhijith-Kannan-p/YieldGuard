import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Unit tests for the page components. Rendering uses react-dom/server, so no browser is needed.
export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: { include: ["tests/**/*.test.{ts,tsx}"], environment: "node" },
});
