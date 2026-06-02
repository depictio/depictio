/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/dashboards/create-dashboard.cy.js
 * Target: React frontend (depictio/react-frontend).
 *
 * Mapping notes:
 *   - cy.wait(N) (sleep)        -> rely on auto-waiting locators / expect(...).toBeVisible()
 *   - cy.typeRobust(sel, val)   -> locator.fill(val)
 *   - Dash "Actions" accordion + confirm dialog -> React renders a direct
 *     "Delete" button on each dashboard card, so deletion is one click.
 */

import { test, expect } from "@fixtures/auth";
import { IRIS_PROJECT_LABEL } from "@fixtures/projects";

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

    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/);

    await page.getByText("+ New Dashboard").click();

    const uniqueTitle = `Test Dashboard ${new Date()
      .toISOString()
      .replace(/:/g, "-")}`;

    await page.getByPlaceholder("Enter dashboard title").fill(uniqueTitle);

    // Mantine Select: click to open, then pick the option by visible text.
    await page.locator("#dashboard-projects").click();
    await page.getByText(IRIS_PROJECT_LABEL).click();

    await page.locator("#create-dashboard-submit").click();

    // The new card should appear with our unique title.
    const targetCard = page
      .locator(".mantine-Card-root")
      .filter({ hasText: uniqueTitle })
      .first();
    await expect(targetCard).toBeVisible({ timeout: 15_000 });

    // Cleanup: delete the dashboard we just created.
    await targetCard.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText(uniqueTitle)).toBeHidden({ timeout: 15_000 });
  });
});
