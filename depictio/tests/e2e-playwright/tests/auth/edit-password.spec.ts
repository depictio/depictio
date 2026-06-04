/**
 * Port of:
 *   cypress/e2e/auth/standard/edit-password.cy.js
 *   cypress/e2e/auth/standard/auth-account-management.cy.js (password part)
 *
 * Differences vs the Cypress original:
 *   - Uses a freshly REGISTERED throwaway user instead of mutating the shared
 *     testUser's password. The Cypress spec was describe.skip'd precisely
 *     because a mid-test failure left the shared password changed; a
 *     throwaway user makes the test idempotent and retry-safe.
 *   - Edit Password is a modal on /profile in the React viewer
 *     (EditPasswordModal.tsx), enabled only in standard auth mode.
 *
 * Only runs in standard mode: the button is disabled in single-user, public
 * and demo modes (ProfileApp.buttonStates).
 */

import { test, expect, getAuthMode, apiLogin, loginStatus, seedTokenInStorage, API_URL, API_PREFIX } from "@fixtures/auth";

const OLD_PASSWORD = "Test123!old";
const NEW_PASSWORD = "Test123!new";

test.describe("Edit Password", () => {
  test.beforeEach(async () => {
    const mode = await getAuthMode();
    test.skip(
      mode.is_single_user_mode || mode.is_public_mode || mode.is_demo_mode,
      "Password editing is only available in standard auth mode.",
    );
  });

  test("changes the password and can re-login with it", async ({
    page,
    request,
  }) => {
    // Register a throwaway user (registration is open in standard dev mode).
    const email = `e2e-pwd-${Date.now()}@example.com`;
    const reg = await request.post(`${API_URL}${API_PREFIX}/auth/register`, {
      data: { email, password: OLD_PASSWORD, is_admin: false },
      headers: { "Content-Type": "application/json" },
    });
    expect(reg.ok(), `registration failed: ${reg.status()}`).toBeTruthy();

    // Log in as the throwaway user and open the profile page.
    const tokens = await apiLogin(request, email, OLD_PASSWORD);
    tokens.email = email;
    await seedTokenInStorage(page, tokens);
    await page.goto("/profile");

    const editBtn = page.locator("[data-testid='edit-password-button']");
    await expect(editBtn).toBeVisible({ timeout: 15_000 });
    await expect(editBtn).toBeEnabled();
    await editBtn.click();

    const modal = page.locator("[data-testid='edit-password-modal']");
    await expect(modal).toBeVisible();

    // Client-side validation: mismatching confirmation.
    await modal.locator("[data-testid='old-password']").fill(OLD_PASSWORD);
    await modal.locator("[data-testid='new-password']").fill(NEW_PASSWORD);
    await modal.locator("[data-testid='confirm-new-password']").fill("not-the-same");
    await modal.locator("[data-testid='save-password-btn']").click();
    await expect(modal.locator("[data-testid='password-message']")).toContainText(
      /do not match/i,
    );

    // Fix the confirmation and submit for real.
    await modal.locator("[data-testid='confirm-new-password']").fill(NEW_PASSWORD);
    await modal.locator("[data-testid='save-password-btn']").click();
    await expect(modal.locator("[data-testid='password-message']")).toContainText(
      /updated successfully/i,
      { timeout: 10_000 },
    );

    // The old password no longer works; the new one does. loginStatus rides
    // out 429s — under parallel workers the limiter can throttle this probe,
    // and a 429 says nothing about the credentials (CI flake source).
    expect(await loginStatus(request, email, OLD_PASSWORD)).toBe(401);

    const newTokens = await apiLogin(request, email, NEW_PASSWORD);
    expect(newTokens.access_token).toBeTruthy();
  });

  test("rejects reusing the old password as the new one", async ({
    page,
    request,
  }) => {
    const email = `e2e-pwd-same-${Date.now()}@example.com`;
    const reg = await request.post(`${API_URL}${API_PREFIX}/auth/register`, {
      data: { email, password: OLD_PASSWORD, is_admin: false },
      headers: { "Content-Type": "application/json" },
    });
    expect(reg.ok()).toBeTruthy();

    const tokens = await apiLogin(request, email, OLD_PASSWORD);
    tokens.email = email;
    await seedTokenInStorage(page, tokens);
    await page.goto("/profile");

    await page.locator("[data-testid='edit-password-button']").click();
    const modal = page.locator("[data-testid='edit-password-modal']");
    await expect(modal).toBeVisible();

    await modal.locator("[data-testid='old-password']").fill(OLD_PASSWORD);
    await modal.locator("[data-testid='new-password']").fill(OLD_PASSWORD);
    await modal.locator("[data-testid='confirm-new-password']").fill(OLD_PASSWORD);
    await modal.locator("[data-testid='save-password-btn']").click();
    await expect(modal.locator("[data-testid='password-message']")).toContainText(
      /cannot be the same/i,
    );
  });
});
