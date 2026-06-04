/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/dashboards/create-dashboard-extended.cy.js
 * Target: depictio-viewer on :5601.
 *
 * The original Cypress spec is named "extended" but only exercises
 * create + verify-in-list + delete. This port adds a reload to confirm the
 * dashboard persists in the listing (server round-trip), then cleans up.
 */

import { test, expect } from "@fixtures/auth";
import { createDashboard, deleteDashboard } from "@fixtures/dashboard";

test.describe("Create dashboard and verify it persists", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Dashboard creation requires an authenticated user.",
  );

  test("creates a dashboard, confirms it survives reload, then deletes it", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/dashboards");

    const uniqueTitle = `Test Dashboard ${new Date()
      .toISOString()
      .replace(/:/g, "-")}`;

    await createDashboard(page, uniqueTitle);

    // Navigate away and back to confirm server-side persistence.
    // (page.reload() leaves the viewer in a session-loading state which
    // temporarily disables ownership-gated actions like Delete.)
    await page.goto("/profile");
    await page.goto("/dashboards");
    await expect(
      page.locator("[data-testid='dashboard-card']").filter({ hasText: uniqueTitle }).first(),
    ).toBeVisible({ timeout: 15_000 });

    await deleteDashboard(page, uniqueTitle);
  });
});
