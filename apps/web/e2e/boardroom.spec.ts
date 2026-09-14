import { expect, test } from "@playwright/test";

/**
 * F8's measurable criteria against a real running app + real Supabase
 * Realtime: a row insert reaching its column within 2s, and a reload
 * mid-run restoring every already-written row. Both require seeded data
 * (a project with an in-progress run) that this repo's fixtures do not
 * provide out of the box, so these specs are written to the contract but
 * are expected to be skipped/pointed at a seeded environment via
 * `E2E_BASE_URL` and `E2E_PROJECT_ID` rather than run unconditionally in
 * CI. The vitest suite (`tests/boardroom.test.tsx`) is what proves the
 * routing/refetch logic itself, deterministically and without a browser.
 */
const projectId = process.env.E2E_PROJECT_ID;

test.skip(!projectId, "requires E2E_PROJECT_ID pointing at a seeded, in-progress run");

test("an inserted evidence row appears in its column within 2s", async ({ page }) => {
  await page.goto(`/projects/${projectId}`);
  const boardroom = page.getByTestId("boardroom");
  await expect(boardroom).toBeVisible();

  const cardCountBefore = await page.getByTestId("evidence-card").count();
  // A real insert is triggered by the seeded environment's fixture runner;
  // here we only assert the latency bound once the count changes.
  await expect
    .poll(async () => page.getByTestId("evidence-card").count(), { timeout: 2_000 })
    .toBeGreaterThan(cardCountBefore);
});

test("reloading mid-run restores every row already written", async ({ page }) => {
  await page.goto(`/projects/${projectId}`);
  const before = await page.getByTestId("evidence-card").count();
  await page.reload();
  await expect(page.getByTestId("evidence-card")).toHaveCount(before);
});
