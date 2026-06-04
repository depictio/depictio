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
import { apiLogin, getAuthMode, API_URL, API_PREFIX } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

test.describe("Single-User Mode", () => {
  test.beforeEach(async () => {
    const { is_single_user_mode } = await getAuthMode();
    test.skip(!is_single_user_mode, "Not running in single-user mode.");
  });

  test.describe("Mode detection", () => {
    test("backend reports single-user mode correctly", async ({ request }) => {
      const res = await request.get(
        `${API_URL}${API_PREFIX}/auth/me/optional`,
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
        `${API_URL}${API_PREFIX}/auth/me/optional`,
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
        `${API_URL}${API_PREFIX}/auth/register`,
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

      const btn = page.locator("[data-testid='new-dashboard-btn']");
      await expect(btn).toBeVisible();
      await expect(btn).toBeEnabled();
    });

    test("dashboard list loads without errors", async ({
      loginAsAdmin,
      page,
    }) => {
      await loginAsAdmin();
      await page.goto("/dashboards");

      // App shell is visible (Mantine AppShell root)
      await expect(page.locator(".mantine-AppShell-root")).toBeVisible();
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

  // Registration UI test is not possible in single-user mode because the
  // viewer's /auth page auto-redirects to /dashboards without rendering the
  // login form. The API-level test above (`registration endpoint is disabled`)
  // already covers this contract via direct HTTP.

  test("direct access to /dashboards without prior login", async ({ page }) => {
    // The viewer auto-authenticates in single-user mode via /auth/me/optional
    // (see depictio/viewer/src/auth/AuthApp.tsx). No token seeding required.
    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/, { timeout: 10_000 });
    await expect(page).not.toHaveURL(/\/auth/);
  });
});
