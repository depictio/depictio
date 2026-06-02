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
import { IRIS_PROJECT_LABEL } from "@fixtures/projects";
import type { Page } from "@playwright/test";

async function createDashboard(page: Page, title: string): Promise<void> {
  await page.getByText("+ New Dashboard").click();
  await page.getByPlaceholder("Enter dashboard title").fill(title);
  await page.locator("#dashboard-projects").click();
  await page.getByText(IRIS_PROJECT_LABEL).click();
  await page.locator("#create-dashboard-submit").click();
  await expect(
    page.locator(".mantine-Card-root").filter({ hasText: title }).first(),
  ).toBeVisible({ timeout: 15_000 });
}

async function deleteDashboardCard(page: Page, title: string): Promise<void> {
  const card = page
    .locator(".mantine-Card-root")
    .filter({ hasText: title })
    .first();
  await card.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText(title)).toBeHidden({ timeout: 15_000 });
}

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

    await expect(page.getByText(first)).toBeVisible();
    await expect(page.getByText(second)).toBeVisible();

    await deleteDashboardCard(page, first);
    await deleteDashboardCard(page, second);
  });
});
