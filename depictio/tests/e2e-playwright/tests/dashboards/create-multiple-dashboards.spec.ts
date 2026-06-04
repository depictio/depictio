/**
 * Revival + port of
 * depictio/tests/e2e-tests/cypress/e2e/dashboards/create-multiple-dashboards.cy.js
 * (the original Cypress spec was entirely commented out / disabled).
 * Target: React frontend.
 *
 * Creates two dashboards, verifies both appear in the listing, then deletes
 * both. Exercises the create modal and the listing refresh path.
 */

import { test, expect } from "@fixtures/auth";
import { createDashboard, deleteDashboard } from "@fixtures/dashboard";

test.describe("Create and manage multiple dashboards", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Dashboard creation requires an authenticated user.",
  );

  test("creates two dashboards then removes both", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/dashboards");

    const stamp = new Date().toISOString().replace(/:/g, "-");
    const first = `First Dashboard ${stamp}`;
    const second = `Second Dashboard ${stamp}`;

    await createDashboard(page, first);
    await createDashboard(page, second);

    await expect(
      page.locator("[data-testid='dashboard-card']").filter({ hasText: first }),
    ).toBeVisible();
    await expect(
      page.locator("[data-testid='dashboard-card']").filter({ hasText: second }),
    ).toBeVisible();

    await deleteDashboard(page, first);
    await deleteDashboard(page, second);
  });
});
