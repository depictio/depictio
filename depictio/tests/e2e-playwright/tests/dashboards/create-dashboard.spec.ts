/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/dashboards/create-dashboard.cy.js
 * Target: depictio-viewer on :5601.
 */

import { test, expect } from "@fixtures/auth";
import { DASHBOARDS_GRID_URL, createDashboard, deleteDashboard } from "@fixtures/dashboard";

test.describe("Create and manage dashboard", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Dashboard creation requires an authenticated user.",
  );

  test("logs in, creates and deletes a dashboard", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto(DASHBOARDS_GRID_URL);
    await expect(page).toHaveURL(/\/dashboards/);

    const uniqueTitle = `Test Dashboard ${new Date()
      .toISOString()
      .replace(/:/g, "-")}`;

    await createDashboard(page, uniqueTitle);
    await deleteDashboard(page, uniqueTitle);
  });
});
