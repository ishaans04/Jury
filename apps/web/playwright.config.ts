import { defineConfig, devices } from "@playwright/test";

/**
 * E2E specs for the two behaviours vitest cannot exercise without a real
 * browser and a running app: the middleware redirect (`auth.spec.ts`) and
 * the boardroom's live-update / reload timing (`boardroom.spec.ts`).
 * Neither runs against live Supabase — see each spec's own header comment
 * for what it assumes and why it's skipped when that isn't available.
 * CI without a browser install should skip this project entirely; the
 * vitest suite (`npm test`) carries all the assertions that must never be
 * skipped (no password, hearing gate, five columns, source links).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
