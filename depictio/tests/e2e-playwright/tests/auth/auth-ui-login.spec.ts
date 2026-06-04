/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/auth/standard/auth-ui-login.cy.js
 */

import { test, expect } from "@fixtures/auth";
import { uiLogin, apiLogin, getAuthMode } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

test.describe("Authentication UI - Login Flow", () => {
  test.describe("Login Success Scenarios", () => {
    test("logs in successfully with valid credentials (UI flow)", async ({
      page,
    }) => {
      const { is_single_user_mode } = await getAuthMode();
      test.skip(
        is_single_user_mode,
        "Single-user mode: /auth auto-redirects to /dashboards, no login form rendered.",
      );
      await uiLogin(page, credentials.testUser.email, credentials.testUser.password);
      await expect(page.locator("[data-testid='modal-content']")).toBeHidden({
        timeout: 10_000,
      });
    });

    test("logs in via the loginAsUser fixture (programmatic, fastest)", async ({
      loginAsUser,
      page,
    }) => {
      await loginAsUser();
      await page.goto("/dashboards");
      await expect(page).toHaveURL(/\/dashboards/);
    });
  });

  test.describe("Login Failure Scenarios", () => {
    test("shows error message for invalid credentials", async ({ page }) => {
      const { is_single_user_mode } = await getAuthMode();
      test.skip(
        is_single_user_mode,
        "Single-user mode: backend accepts any credential, login errors never surface.",
      );

      await uiLogin(page, "invalid_user@example.com", "wrong_password");

      const feedback = page.locator("[data-testid='user-feedback-message-login']");
      await expect(feedback).toBeVisible();
      await expect(feedback).toContainText("Invalid email or password.");
    });
  });

  test.describe("Programmatic auth examples", () => {
    test("apiLogin returns a usable token bundle for the admin user", async ({
      request,
    }) => {
      const tokens = await apiLogin(
        request,
        credentials.adminUser.email,
        credentials.adminUser.password,
      );
      expect(tokens.access_token).toBeTruthy();
      expect(tokens.refresh_token).toBeTruthy();
      expect(tokens.user_id).toBeTruthy();
    });

    test("admin fixture provides logged-in admin context", async ({
      loginAsAdmin,
      page,
    }) => {
      const user = await loginAsAdmin();
      expect(user.is_admin).toBe(true);
      await page.goto("/dashboards");
      await expect(page).toHaveURL(/\/dashboards/);
    });
  });
});
