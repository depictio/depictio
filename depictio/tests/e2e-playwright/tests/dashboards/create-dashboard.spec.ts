/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/dashboards/create-dashboard.cy.js
 *
 * Demonstrates patterns that replace common Cypress idioms:
 *   - cy.wait(N) (sleep)        -> rely on auto-waiting locators / expect(...).toBeVisible()
 *   - cy.typeRobust(sel, val)   -> locator.fill(val) (Playwright auto-retries focus + input)
 *   - cy.contains(...).parents() -> locator(card).filter({ hasText: ... })
 *   - cy.click({force:true})    -> locator.click({ force: true })  (still available; prefer not to)
 */

import { test, expect } from "@fixtures/auth";

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

    // Open the create-dashboard modal.
    await page.getByText("+ New Dashboard").click();

    const uniqueTitle = `Test Dashboard ${new Date()
      .toISOString()
      .replace(/:/g, "-")}`;

    await page.getByPlaceholder("Enter dashboard title").fill(uniqueTitle);

    // Select the project. The Mantine Select is opened by clicking the input,
    // then the option is picked by visible text.
    await page.locator("#dashboard-projects").click();
    await page
      .getByText("Iris Dataset Project Data Analysis (646b0f3c1e4a2d7f8e5b8c9a)")
      .click();

    await page.locator("#create-dashboard-submit").click();

    // Verify at least one dashboard card exists, and our new title is visible.
    const cards = page.locator(".mantine-Card-root");
    await expect(cards.first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(uniqueTitle)).toBeVisible();

    // Cleanup: locate the card by title and trigger its delete flow.
    const targetCard = page
      .locator(".mantine-Card-root")
      .filter({ hasText: uniqueTitle })
      .first();
    await targetCard.getByText("Actions").click({ force: true });
    await targetCard.getByRole("button", { name: "Delete" }).click({
      force: true,
    });

    // Confirm deletion in the dialog.
    await page.getByRole("button", { name: "Delete" }).last().click({
      force: true,
    });

    await expect(page.getByText(uniqueTitle)).toBeHidden({ timeout: 15_000 });
  });
});
