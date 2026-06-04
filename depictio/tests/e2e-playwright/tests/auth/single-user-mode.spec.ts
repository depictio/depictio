/**
 * Port + extension of:
 * depictio/tests/e2e-tests/cypress/e2e/auth/single-user/single-user-mode.cy.js
 *
 * These tests only run when the backend reports is_single_user_mode=true
 * (detected live via /auth/me/optional — no env var needed).
 *
 * Single-user mode contract:
 *   - One admin user is auto-provisioned; no registration UI.
 *   - Credentials still work for programmatic login (token-based).
 *   - Admin privileges: dashboard creation available.
 *   - No demo / public mode features visible.
 *
 * React frontend note: direct unauthenticated access to /dashboards is NOT
 * yet auto-supported (ProtectedRoute redirects to /auth without a token even
 * in single-user mode). The "immediate access without login" test is marked
 * xfail and documents what the React app still needs to implement.
 */

import { test, expect } from "@fixtures/auth";
import { apiLogin, getAuthMode } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

test.describe("Single-User Mode", () => {
  test.beforeEach(async () => {
    const { is_single_user_mode } = await getAuthMode();
    test.skip(!is_single_user_mode, "Not running in single-user mode.");
  });

  test.describe("Mode detection", () => {
    test("backend reports single-user mode correctly", async ({ request }) => {
      const res = await request.get(
        "http://localhost:8101/depictio/api/v1/auth/me/optional",
      );
      expect(res.ok()).toBeTruthy();
      const body = await res.json() as {
        auth_mode: string;
        is_single_user_mode: boolean;
        is_public_mode: boolean;
        is_demo_mode: boolean;
      };
      expect(body.auth_mode).toBe("single_user");
      expect(body.is_single_user_mode).toBe(true);
      expect(body.is_public_mode).toBe(false);
      expect(body.is_demo_mode).toBe(false);
    });

    test("auto-provisioned admin user has correct attributes", async ({
      request,
    }) => {
      const res = await request.get(
        "http://localhost:8101/depictio/api/v1/auth/me/optional",
      );
      const body = await res.json() as { user: { email: string; is_admin: boolean } };
      expect(body.user.email).toBe(credentials.adminUser.email);
      expect(body.user.is_admin).toBe(true);
    });
  });

  test.describe("Authentication", () => {
    test("admin credentials produce a valid token", async ({ request }) => {
      const tokens = await apiLogin(
        request,
        credentials.adminUser.email,
        credentials.adminUser.password,
      );
      expect(tokens.access_token).toBeTruthy();
      expect(tokens.refresh_token).toBeTruthy();
    });

    test("registration endpoint is disabled", async ({ request }) => {
      const res = await request.post(
        "http://localhost:8101/depictio/api/v1/auth/register",
        {
          data: { email: "new@example.com", password: "Test123!", is_admin: false },
          headers: { "Content-Type": "application/json" },
        },
      );
      expect(res.status()).toBe(403);
      const body = await res.json() as { detail: string };
      expect(body.detail).toMatch(/single-user|disabled/i);
    });
  });

  test.describe("Admin access after login", () => {
    test("+ New Dashboard button is visible and enabled", async ({
      loginAsAdmin,
      page,
    }) => {
      await loginAsAdmin();
      await page.goto("/dashboards");
      await expect(page).toHaveURL(/\/dashboards/);

      const btn = page.getByRole("button", { name: /New Dashboard/i });
      await expect(btn).toBeVisible();
      await expect(btn).toBeEnabled();
    });

    test("dashboard list loads without errors", async ({
      loginAsAdmin,
      page,
    }) => {
      await loginAsAdmin();
      await page.goto("/dashboards");

      // App shell is visible
      await expect(page.locator("#app-shell")).toBeVisible();
      // No error alert
      await expect(page.locator("[role=alert]").filter({ hasText: /error/i })).toHaveCount(0);
    });

    test("no public/demo mode features visible", async ({
      loginAsAdmin,
      page,
    }) => {
      await loginAsAdmin();
      await page.goto("/dashboards");

      const body = page.locator("body");
      await expect(body).not.toContainText("Demo Mode");
      await expect(body).not.toContainText("Public Mode");
      await expect(body).not.toContainText("Login as a temporary user");
    });
  });

  test.describe("Registration UI blocked", () => {
    test("register form shows disabled-mode error", async ({ page }) => {
      // Navigate to /auth and try to open the register form.
      await page.goto("/auth");
      await expect(page.locator("#modal-content")).toBeVisible();
      await page.locator("#open-register-form").click();

      // Fill and submit — backend will reject with 403.
      await page.locator("#register-email").fill("blocked@example.com");
      await page.locator("#register-password").fill("AnyPassword1!");
      await page.locator("#register-confirm-password").fill("AnyPassword1!");
      await page.locator("#register-button").click();

      await expect(page.locator("#user-feedback-message-register")).toContainText(
        /single-user|disabled/i,
      );
    });
  });

  // ── Future: auto-auth without token ──────────────────────────────────────
  // The React ProtectedRoute currently redirects to /auth if no token is
  // present in localStorage, even in single-user mode. The Dash frontend
  // handled this server-side. This test documents the gap and will pass once
  // ProtectedRoute calls /auth/me/optional at boot and auto-seeds the token.
  test("TODO: direct access to /dashboards without prior login", async ({
    page,
  }) => {
    test.fail(
      true,
      "React ProtectedRoute does not yet auto-authenticate in single-user mode.",
    );
    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/);
    await expect(page).not.toHaveURL(/\/auth/);
  });
});
