/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/auth/standard/auth-ui-registration.cy.js
 * Target: React frontend.
 *
 * cy.registerUser(...) -> uiRegister(page, email, password, confirmPassword?)
 * Feedback assertions read [data-testid='user-feedback-message-register'], same as Cypress.
 */

import { test, expect } from "@fixtures/auth";
import { uiRegister, uiLogin, getAuthMode } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

test.describe("Authentication UI - Registration Flow", () => {
  test.beforeEach(async () => {
    const { is_single_user_mode, is_public_mode } = await getAuthMode();
    test.skip(
      is_single_user_mode || is_public_mode,
      "Registration is disabled in single-user / public mode.",
    );
  });

  // React contract (RegisterForm.tsx): successful registration AUTO-LOGS-IN
  // and navigates away — the success message only renders if the auto-login
  // fails. The Cypress-era "shows a success message" expectation is gone.

  test.describe("Success scenarios", () => {
    test("registers a new user and is auto-logged-in to /dashboards", async ({
      page,
    }) => {
      const email = `test_${Date.now()}@example.com`;
      await uiRegister(page, email, "test_password_123");

      // Register → auto-login → onSuccess() navigates to the app.
      await expect(page).toHaveURL(/\/dashboards/, { timeout: 15_000 });
      await expect(page.locator("[data-testid='modal-content']")).toBeHidden();
    });

    test("registered credentials work for a fresh login", async ({
      page,
    }) => {
      const email = `test_user_${Date.now()}@example.com`;
      const password = "SecurePassword123!";

      await uiRegister(page, email, password);
      await expect(page).toHaveURL(/\/dashboards/, { timeout: 15_000 });

      // Drop the auto-login session, then authenticate from scratch.
      await page.evaluate(() => window.localStorage.clear());
      await uiLogin(page, email, password);
      await expect(page.locator("[data-testid='modal-content']")).toBeHidden({
        timeout: 10_000,
      });
    });
  });

  test.describe("Failure scenarios", () => {
    test("shows an error for password mismatch", async ({ page }) => {
      const email = `test_user_${Date.now()}@example.com`;
      await uiRegister(page, email, "SecurePassword123!", "SecurePassword124!");

      await expect(
        page.locator("[data-testid='user-feedback-message-register']"),
      ).toHaveText(/password.*match/i);
    });

    test("shows an error when registering an existing email", async ({
      page,
    }) => {
      await uiRegister(page, credentials.testUser.email, "SomePassword123!");

      // RegisterForm surfaces a generic failure message on any server error.
      await expect(
        page.locator("[data-testid='user-feedback-message-register']"),
      ).toHaveText(/registration failed/i);
    });
  });
});
