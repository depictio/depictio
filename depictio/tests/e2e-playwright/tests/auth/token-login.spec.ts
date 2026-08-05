/**
 * Port of:
 *   cypress/e2e/auth/standard/token-login-test.cy.js
 *   cypress/e2e/auth/standard/auth-account-management.cy.js (token-auth part)
 *
 * Verifies the programmatic (token-based) login path the rest of the suite
 * relies on: API login endpoint contract, localStorage seeding shape used by
 * the React viewer (`local-store`), and protected-page access.
 */

import { test, expect, apiLogin, getAuthMode, loginStatus, seedTokenInStorage } from "@fixtures/auth";
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
    // Single-user mode's /auth/login ignores the submitted credentials and
    // always issues the admin token, so the per-user email assertion below
    // cannot hold. Same guard the other credential-sensitive tests here use.
    const { is_single_user_mode } = await getAuthMode();
    test.skip(
      is_single_user_mode,
      "Single-user mode always logs in as admin, not the requested user.",
    );

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

    // Via `loginStatus` rather than a bare POST: this asserts an *outcome* of
    // the submitted credentials, and a 429 from the per-minute login limiter
    // says nothing about them. Earlier specs in the file log in repeatedly, so
    // the window is often already part-spent by the time this runs.
    expect(
      await loginStatus(request, "wrong@email.com", "wrongpassword"),
    ).toBe(401);
  });
});
