/**
 * Port of: cypress/e2e/pages/about-page.cy.js
 *
 * The React /about page (src/about/AboutApp.tsx) is a static resources page:
 * GitHub + documentation links and funding partner cards.
 */

import { test, expect } from "@fixtures/auth";

test.describe("About Page", () => {
  test("renders resources and partner links without errors", async ({
    loginAsUser,
    page,
  }) => {
    await loginAsUser();
    await page.goto("/about");
    await expect(page).toHaveURL(/\/about/);

    // Resource links are present.
    await expect(
      page.locator("a[href='https://github.com/depictio/depictio']"),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.locator("a[href='https://depictio.github.io/depictio-docs/']"),
    ).toBeVisible();

    // No error alert anywhere on the page.
    await expect(
      page.locator("[role=alert]").filter({ hasText: /error/i }),
    ).toHaveCount(0);
  });
});
