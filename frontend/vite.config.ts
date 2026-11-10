import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Im Entwicklungsmodus leitet Vite alle Backend-Pfade an das lokal laufende Panel weiter.
const backend = "http://127.0.0.1:8090";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": backend, "/mcp": backend, "/v1": backend },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
