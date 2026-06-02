import { test as base, expect, Page, APIRequestContext } from "@playwright/test";
import { credentials, TestUser, UserType } from "./credentials";

const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8058";
const API_PREFIX = "/depictio/api/v1";

export interface TokenBundle {
  access_token: string;
  refresh_token: string;
  user_id: string;
}

/**
 * Programmatic login via the FastAPI OAuth2 password endpoint.
 * Equivalent to Cypress `cy.loginWithToken` — bypasses the UI entirely.
 */
export async function apiLogin(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<TokenBundle> {
  const response = await request.post(`${API_URL}${API_PREFIX}/auth/login`, {
    form: { username: email, password },
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  expect(response.ok(), `Login failed: ${response.status()}`).toBeTruthy();
  return (await response.json()) as TokenBundle;
}

/**
 * UI login: opens /auth, fills the modal, submits.
 * Equivalent to Cypress `cy.loginUser`.
 */
export async function uiLogin(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.goto("/auth");
  const modal = page.locator("#modal-content");
  await expect(modal).toBeVisible({ timeout: 10_000 });

  await modal.locator("#login-email").fill(email);
  await modal.locator("#login-password").fill(password);
  await modal.locator("#login-button").click();
}

/**
 * Seed the browser with auth tokens so subsequent navigations are logged in
 * without hitting the UI. Mirrors Cypress `cy.loginWithToken` end-state.
 *
 * Two storage shapes are supported, selected by PLAYWRIGHT_TARGET:
 *   - "react" (default): the React app's Zustand `persist` store under the
 *     `depictio-auth` key, shape `{ state: { accessToken, refreshToken }, version: 0 }`.
 *   - "dash": the Dash app's `local-store` dcc.Store, shape
 *     `{ access_token, refresh_token, logged_in, user_id }`.
 */
const TARGET = (process.env.PLAYWRIGHT_TARGET ?? "react").toLowerCase();

export async function seedTokenInStorage(
  page: Page,
  tokens: TokenBundle,
): Promise<void> {
  await page.goto("/");
  await page.evaluate(
    ({ t, target }) => {
      if (target === "dash") {
        window.localStorage.setItem(
          "local-store",
          JSON.stringify({
            access_token: t.access_token,
            refresh_token: t.refresh_token,
            logged_in: true,
            user_id: t.user_id,
          }),
        );
      } else {
        window.localStorage.setItem(
          "depictio-auth",
          JSON.stringify({
            state: {
              accessToken: t.access_token,
              refreshToken: t.refresh_token,
            },
            version: 0,
          }),
        );
      }
    },
    { t: tokens, target: TARGET },
  );
}

/**
 * UI registration: opens /auth, switches to the register view, fills and
 * submits the form. Equivalent to Cypress `cy.registerUser`.
 */
export async function uiRegister(
  page: Page,
  email: string,
  password: string,
  confirmPassword?: string,
): Promise<void> {
  await page.goto("/auth");
  const modal = page.locator("#modal-content");
  await expect(modal).toBeVisible({ timeout: 10_000 });

  await modal.locator("#open-register-form").click();
  await modal.locator("#register-email").fill(email);
  await modal.locator("#register-password").fill(password);
  await modal
    .locator("#register-confirm-password")
    .fill(confirmPassword ?? password);
  await modal.locator("#register-button").click();
}

/**
 * UI logout: navigates to /profile and clicks the logout button, then
 * expects the auth modal to reappear. Equivalent to Cypress `cy.logoutRobust`.
 */
export async function uiLogout(page: Page): Promise<void> {
  await page.goto("/profile");
  await page.locator("#logout-button").click();
  await expect(page.locator("#modal-content")).toBeVisible({ timeout: 10_000 });
}

/**
 * Convenience: programmatic login + storage seed.
 */
export async function loginAsTestUser(
  page: Page,
  request: APIRequestContext,
  userType: UserType = "testUser",
): Promise<TestUser> {
  const user = credentials[userType];
  const tokens = await apiLogin(request, user.email, user.password);
  await seedTokenInStorage(page, tokens);
  return user;
}

/**
 * Playwright fixture: extends the default `test` with auth helpers.
 *
 * Usage:
 *   import { test, expect } from "@fixtures/auth";
 *   test("...", async ({ page, loginAsAdmin }) => { await loginAsAdmin(); ... });
 */
type AuthFixtures = {
  loginAsAdmin: () => Promise<TestUser>;
  loginAsUser: () => Promise<TestUser>;
};

export const test = base.extend<AuthFixtures>({
  loginAsAdmin: async ({ page, request }, use) => {
    await use(() => loginAsTestUser(page, request, "adminUser"));
  },
  loginAsUser: async ({ page, request }, use) => {
    await use(() => loginAsTestUser(page, request, "testUser"));
  },
});

export { expect };
