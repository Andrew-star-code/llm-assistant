import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// В dev-стенде фронтенд ходит в api через прокси Vite; в проде — через nginx (этап 10).
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
const proxy = Object.fromEntries(
  ["/api", "/health", "/ready"].map((path) => [path, { target: apiTarget, changeOrigin: false }]),
);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: { host: "0.0.0.0", port: 5173, strictPort: true, proxy },
  preview: { port: 4173, strictPort: true, proxy },
  build: { sourcemap: true },
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/unit/setup.ts"],
    css: false,
  },
});
