import { defineConfig, devices } from "@playwright/test";

// E2E по §18.1. На этапе 0 — смоук SPA; полный поток (вход, стрим, стоп) — с этапа 2,
// тогда webServer заменится на поднятый make dev-up стенд.
const port = 4173;

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${port}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm build && pnpm preview --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
