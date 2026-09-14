import { expect, test } from "@playwright/test";

/**
 * Requires the app running against a real (or locally-run) Supabase
 * project, since `middleware.ts` calls `supabase.auth.getUser()` on every
 * request. Not run under vitest — no browser, no server — and skipped in
 * CI unless a browser + a running `next dev`/`next start` are both
 * available (see `playwright.config.ts`).
 */
test("unauthenticated /projects redirects to /login with a next param", async ({ page }) => {
  await page.goto("/projects");
  await expect(page).toHaveURL(/\/login\?next=%2Fprojects/);
});

test("the login page never renders a password field", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
});
