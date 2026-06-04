/**
 * Port of:
 *   cypress/e2e/auth/standard/token-login-test.cy.js
 *   cypress/e2e/auth/standard/auth-account-management.cy.js (token-auth part)
 *
 * Verifies the programmatic (token-based) login path the rest of the suite
 * relies on: API login endpoint contract, localStorage seeding shape used by
 * the React viewer (`local-store`), and protected-page access.
 */

import { test, expect, apiLogin, getAuthMode, seedTokenInStorage, API_URL, API_PREFIX } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

test.describe("Token-Based Login", () => {
  test("login endpoint returns a complete token bundle", async ({ request }) => {
    const tokens = await apiLogin(
      request,
      credentials.adminUser.email,
      credentials.adminUser.password,
    );
    expect(tokens.access_token).toBeTruthy();
    expect(tokens.refresh_token).toBeTruthy();
    expect(tokens.user_id).toBeTruthy();
  });

  test("seeded token grants access to protected pages", async ({
    page,
    request,
  }) => {
    const tokens = await apiLogin(
      request,
      credentials.adminUser.email,
      credentials.adminUser.password,
    );
    tokens.email = credentials.adminUser.email;
    await seedTokenInStorage(page, tokens);

    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/);
    await expect(page).not.toHaveURL(/\/auth/);

    await page.goto("/profile");
    await expect(page).toHaveURL(/\/profile/);
    await expect(
      page.locator("[data-testid='profile-info-email']"),
    ).toContainText(credentials.adminUser.email, { timeout: 15_000 });
  });

  test("localStorage session has the viewer's local-store shape", async ({
    page,
    request,
  }) => {
    const tokens = await apiLogin(
      request,
      credentials.testUser.email,
      credentials.testUser.password,
    );
    tokens.email = credentials.testUser.email;
    await seedTokenInStorage(page, tokens);
    await page.goto("/dashboards");

    const stored = await page.evaluate(() =>
      JSON.parse(window.localStorage.getItem("local-store") ?? "{}"),
    );
    expect(stored.logged_in).toBe(true);
    expect(stored.access_token).toBeTruthy();
    expect(stored.user_id).toBeTruthy();
    expect(stored.email).toBe(credentials.testUser.email);
  });

  test("rejects invalid credentials with 401", async ({ request }) => {
    // In single-user mode the login endpoint auto-issues the admin token
    // regardless of the submitted credentials — nothing to reject.
    const { is_single_user_mode } = await getAuthMode();
    test.skip(is_single_user_mode, "Single-user mode accepts any credentials.");

    const res = await request.post(`${API_URL}${API_PREFIX}/auth/login`, {
      form: { username: "wrong@email.com", password: "wrongpassword" },
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    expect(res.status()).toBe(401);
  });
});
