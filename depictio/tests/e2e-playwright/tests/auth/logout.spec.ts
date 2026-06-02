/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/auth/standard/logout.cy.js
 */

import { test, expect } from "@fixtures/auth";

test.describe("Logout flow", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Logout is not exposed in unauthenticated mode.",
  );

  test("logs out and returns to /auth", async ({ loginAsUser, page }) => {
    await loginAsUser();

    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/);

    await page.goto("/profile");
    await page.getByRole("button", { name: "Logout" }).click();

    // Auth modal should reappear and URL should be /auth.
    await expect(page.locator("#modal-content")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page).toHaveURL(/\/auth/);
  });
});
