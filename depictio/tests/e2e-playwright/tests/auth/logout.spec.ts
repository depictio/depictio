/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/auth/standard/logout.cy.js
 */

import { test, expect } from "@fixtures/auth";
import { getAuthMode } from "@fixtures/auth";

test.describe("Logout flow", () => {
  test("logs out and returns to /auth", async ({ loginAsUser, page }) => {
    const { is_single_user_mode } = await getAuthMode();
    test.skip(
      is_single_user_mode,
      "Single-user mode: logout button is disabled (no session concept).",
    );
    await loginAsUser();

    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/);

    await page.goto("/profile");
    await page.locator("[data-testid='logout-button']").click();

    // Auth card should reappear and URL should be /auth.
    await expect(page.locator("[data-testid='modal-content']")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page).toHaveURL(/\/auth/);
  });
});
