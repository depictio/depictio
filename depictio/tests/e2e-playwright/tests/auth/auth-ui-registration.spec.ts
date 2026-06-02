/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/auth/standard/auth-ui-registration.cy.js
 * Target: React frontend.
 *
 * cy.registerUser(...) -> uiRegister(page, email, password, confirmPassword?)
 * Feedback assertions read #user-feedback-message-register, same as Cypress.
 */

import { test, expect } from "@fixtures/auth";
import { uiRegister, uiLogin } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

const skipIfUnauth = () =>
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true" ||
      process.env.PUBLIC_MODE === "true",
    "Registration is disabled in unauthenticated / public mode.",
  );

test.describe("Authentication UI - Registration Flow", () => {
  test.describe("Success scenarios", () => {
    test("registers a new user and shows a success message", async ({
      page,
    }) => {
      skipIfUnauth();
      const email = `test_${Date.now()}@example.com`;
      await uiRegister(page, email, "test_password_123");

      const feedback = page.locator("#user-feedback-message-register");
      await expect(feedback).toBeVisible();
      await expect(feedback).toContainText("Registration successful");
    });

    test("registers then logs in with the new credentials", async ({
      page,
    }) => {
      skipIfUnauth();
      const email = `test_user_${Date.now()}@example.com`;
      const password = "SecurePassword123!";

      await uiRegister(page, email, password);
      await expect(
        page.locator("#user-feedback-message-register"),
      ).toContainText("Registration successful");

      // Switch back to login and authenticate with the new account.
      await page.locator("#open-login-form").click();
      await uiLogin(page, email, password);
      await expect(page.locator("#modal-content")).toBeHidden({
        timeout: 10_000,
      });
    });
  });

  test.describe("Failure scenarios", () => {
    test("shows an error for password mismatch", async ({ page }) => {
      skipIfUnauth();
      const email = `test_user_${Date.now()}@example.com`;
      await uiRegister(page, email, "SecurePassword123!", "SecurePassword124!");

      await expect(
        page.locator("#user-feedback-message-register"),
      ).toHaveText(/password.*match/i);
    });

    test("shows an error when registering an existing email", async ({
      page,
    }) => {
      skipIfUnauth();
      await uiRegister(page, credentials.testUser.email, "SomePassword123!");

      await expect(
        page.locator("#user-feedback-message-register"),
      ).toHaveText(/already.*exist|already.*register/i);
    });
  });
});
