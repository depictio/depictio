/**
 * Port of: cypress/e2e/auth/demo/demo-mode.cy.js (against the React viewer)
 *
 * NOT ported (Dash-only features with no React equivalent yet):
 *   - "Demo Mode" sidebar badge        (#tour-popover-welcome-demo …)
 *   - Welcome tour popover + steps     (the React viewer has data-tour-id
 *     anchors but no demo tour implementation)
 *   - depictio-tour-completed localStorage state
 * If/when the demo tour lands in the viewer, port those tests here.
 *
 * Only runs when the backend reports is_demo_mode=true (which implies
 * public mode — DEMO_MODE requires PUBLIC_MODE on the backend).
 */

import { test, expect, getAuthMode, API_URL, API_PREFIX } from "@fixtures/auth";

test.describe("Demo Mode", () => {
  test.beforeEach(async () => {
    const { is_demo_mode } = await getAuthMode();
    test.skip(!is_demo_mode, "Not running in demo mode.");
  });

  test("backend reports demo mode as a superset of public mode", async ({
    request,
  }) => {
    const res = await request.get(`${API_URL}${API_PREFIX}/auth/me/optional`);
    expect(res.ok()).toBeTruthy();
    const body = (await res.json()) as {
      is_demo_mode: boolean;
      is_public_mode: boolean;
      temporary_user_expiry_hours: number;
    };
    expect(body.is_demo_mode).toBe(true);
    expect(body.is_public_mode).toBe(true);
    // The 24h retention promise shown to demo users.
    expect(body.temporary_user_expiry_hours).toBeGreaterThan(0);
  });

  test("dashboards are accessible without login in demo context", async ({
    page,
  }) => {
    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/, { timeout: 15_000 });
    await expect(page).not.toHaveURL(/\/auth/);
    await expect(page.locator(".mantine-AppShell-root")).toBeVisible();
  });
});
