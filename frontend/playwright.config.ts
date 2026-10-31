import { defineConfig, devices } from "@playwright/test";

// E2E по §18.1 — против работающего бэкенда.
// По умолчанию: собранная SPA (vite preview) с прокси на api из `make dev-up` (127.0.0.1:8000).
// E2E_BASE_URL=http://localhost:5173 — прогон прямо против фронтенда дев-стенда.
const port = 4173;
const external = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "tests/e2e",
  // Тесты меняют общие данные стенда (блокировки, настройки) — выполняем последовательно.
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: external ?? `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    // Без UTF-8-локали Chromium на Linux не может дать скачанному файлу кириллическое имя
    // и называет его «download» (проверка имени в files.spec.ts).
    launchOptions: { env: { ...process.env, LANG: "C.UTF-8", LC_ALL: "C.UTF-8" } },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: external
    ? undefined
    : {
        command: `pnpm build && pnpm preview --host 127.0.0.1 --port ${port}`,
        url: `http://127.0.0.1:${port}`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
