/**
 * Port of depictio/tests/e2e-tests/cypress/e2e/auth/standard/auth-ui-login.cy.js
 *
 * Mapping notes:
 *   - cy.fixture()              -> static import of JSON
 *   - cy.loginUser(email, pwd)  -> uiLogin(page, email, pwd)
 *   - cy.loginAsTestUser('x')   -> loginAsUser / loginAsAdmin fixture
 *   - cy.get('#x').should(...)  -> expect(page.locator('#x')).to...
 *   - Cypress.env('FOO')        -> process.env.FOO
 *   - Implicit waits removed: Playwright auto-waits on every locator action.
 */

import { test, expect } from "@fixtures/auth";
import { uiLogin, apiLogin } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

const SKIP_REASON =
  "UNAUTHENTICATED_MODE / PUBLIC_MODE — login UI is not exposed.";
const skipIfUnauth = () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true" ||
      process.env.PUBLIC_MODE === "true",
    SKIP_REASON,
  );
};

test.describe("Authentication UI - Login Flow", () => {
  test.describe("Login Success Scenarios", () => {
    test("logs in successfully with valid credentials (UI flow)", async ({
      page,
    }) => {
      skipIfUnauth();
      await uiLogin(page, credentials.testUser.email, credentials.testUser.password);
      // After successful login the modal closes and the app redirects.
      await expect(page.locator("#modal-content")).toBeHidden({
        timeout: 10_000,
      });
    });

    test("logs in via the loginAsUser fixture (programmatic, fastest)", async ({
      loginAsUser,
      page,
    }) => {
      skipIfUnauth();
      await loginAsUser();
      await page.goto("/dashboards");
      await expect(page).toHaveURL(/\/dashboards/);
    });
  });

  test.describe("Login Failure Scenarios", () => {
    test("shows error message for invalid credentials", async ({ page }) => {
      skipIfUnauth();
      await uiLogin(page, "invalid_user@example.com", "wrong_password");

      const feedback = page.locator("#user-feedback-message-login");
      await expect(feedback).toBeVisible();
      await expect(feedback).toContainText("User not found. Please register first.");
    });
  });

  test.describe("Programmatic auth examples", () => {
    test("apiLogin returns a usable token bundle for the admin user", async ({
      request,
    }) => {
      skipIfUnauth();
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
      skipIfUnauth();
      const user = await loginAsAdmin();
      expect(user.is_admin).toBe(true);
      await page.goto("/dashboards");
      await expect(page).toHaveURL(/\/dashboards/);
    });
  });
});
