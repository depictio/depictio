/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/dashboards/create-dashboard-extended.cy.js
 * Target: React frontend.
 *
 * The original Cypress spec is named "extended" but only exercises
 * create + verify-in-list + delete. This port adds a reload to confirm the
 * dashboard persists in the listing (server round-trip), then cleans up.
 */

import { test, expect } from "@fixtures/auth";
import { IRIS_PROJECT_LABEL } from "@fixtures/projects";

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

    await page.getByText("+ New Dashboard").click();

    const uniqueTitle = `Test Dashboard ${new Date()
      .toISOString()
      .replace(/:/g, "-")}`;
    await page.getByPlaceholder("Enter dashboard title").fill(uniqueTitle);
    await page.locator("#dashboard-projects").click();
    await page.getByText(IRIS_PROJECT_LABEL).click();
    await page.locator("#create-dashboard-submit").click();

    const card = page
      .locator(".mantine-Card-root")
      .filter({ hasText: uniqueTitle })
      .first();
    await expect(card).toBeVisible({ timeout: 15_000 });

    // Reload to confirm the dashboard was persisted server-side.
    await page.reload();
    const cardAfterReload = page
      .locator(".mantine-Card-root")
      .filter({ hasText: uniqueTitle })
      .first();
    await expect(cardAfterReload).toBeVisible({ timeout: 15_000 });

    // Cleanup.
    await cardAfterReload.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText(uniqueTitle)).toBeHidden({ timeout: 15_000 });
  });
});
