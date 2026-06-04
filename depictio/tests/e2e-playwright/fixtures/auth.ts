import { test as base, expect, Page, APIRequestContext } from "@playwright/test";
import { credentials, TestUser, UserType } from "./credentials";

export const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8101";
export const API_PREFIX = "/depictio/api/v1";

interface AuthMode {
  is_single_user_mode: boolean;
  is_public_mode: boolean;
  is_demo_mode: boolean;
}

let _authModeCache: AuthMode | null = null;

/**
 * Fetches the backend auth mode once and caches it.
 * Used to skip tests that are incompatible with single-user / public mode.
 */
export async function getAuthMode(): Promise<AuthMode> {
  if (_authModeCache) return _authModeCache;
  try {
    const res = await fetch(`${API_URL}${API_PREFIX}/auth/me/optional`);
    const data = (await res.json()) as Partial<AuthMode>;
    _authModeCache = {
      is_single_user_mode: data.is_single_user_mode ?? false,
      is_public_mode: data.is_public_mode ?? false,
      is_demo_mode: data.is_demo_mode ?? false,
    };
  } catch {
    _authModeCache = {
      is_single_user_mode: false,
      is_public_mode: false,
      is_demo_mode: false,
    };
  }
  return _authModeCache;
}

export interface TokenBundle {
  access_token: string;
  refresh_token: string;
  user_id: string;
  /** Populated by loginAsTestUser from the credentials table — not returned by
   *  the login endpoint but required by the viewer's local-store session shape
   *  so the ownership check (isOwner) works correctly. */
  email?: string;
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
  // Backoff long enough to ride out the per-minute login rate-limit window
  // when several workers (or consecutive local runs) hammer /auth/login.
  const delays = [0, 2000, 5000, 15000, 30000];
  for (let i = 0; i < delays.length; i++) {
    if (delays[i]) await new Promise((r) => setTimeout(r, delays[i]));
    const response = await request.post(`${API_URL}${API_PREFIX}/auth/login`, {
      form: { username: email, password },
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    if (response.status() === 429) continue;
    expect(response.ok(), `Login failed: ${response.status()}`).toBeTruthy();
    return (await response.json()) as TokenBundle;
  }
  throw new Error("Login rate-limited after 3 retries");
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
  const modal = page.locator("[data-testid='modal-content']");
  await expect(modal).toBeVisible({ timeout: 10_000 });

  // In Mantine v7, data-testid is spread onto the <input> element directly.
  await modal.locator("[data-testid='login-email']").fill(email);
  await modal.locator("[data-testid='login-password']").fill(password);
  await modal.locator("[data-testid='login-button']").click();
}

/**
 * Seed the browser with auth tokens so subsequent navigations are logged in
 * without hitting the UI. Mirrors Cypress `cy.loginWithToken` end-state.
 *
 * The viewer (depictio/viewer/) and the legacy Dash app both use the
 * `local-store` localStorage key with a flat JSON shape.
 * The minimal react-frontend scaffold (depictio/react-frontend/) uses the
 * Zustand `depictio-auth` key instead.
 * Select via PLAYWRIGHT_TARGET: "viewer" | "dash" (default) → local-store,
 *                               "react"                     → depictio-auth.
 */
const TARGET = (process.env.PLAYWRIGHT_TARGET ?? "viewer").toLowerCase();

export async function seedTokenInStorage(
  page: Page,
  tokens: TokenBundle,
): Promise<void> {
  // Use addInitScript to inject localStorage BEFORE any page load rather than
  // navigating to a seed URL. This avoids:
  //   - the React SPA spinner (from "commit" navigations that never resolve)
  //   - race conditions from navigating to JSON endpoints before the SPA
  // The script runs on every subsequent page.goto() in this page context.
  if (TARGET === "react") {
    await page.addInitScript((t) => {
      window.localStorage.setItem(
        "depictio-auth",
        JSON.stringify({
          state: { accessToken: t.access_token, refreshToken: t.refresh_token },
          version: 0,
        }),
      );
    }, tokens);
  } else {
    await page.addInitScript((t) => {
      window.localStorage.setItem(
        "local-store",
        JSON.stringify({
          access_token: t.access_token,
          refresh_token: t.refresh_token,
          logged_in: true,
          user_id: t.user_id,
          email: t.email ?? "",
        }),
      );
    }, tokens);
  }
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
  const modal = page.locator("[data-testid='modal-content']");
  await expect(modal).toBeVisible({ timeout: 10_000 });

  await modal.locator("[data-testid='open-register-form']").click();
  await modal.locator("[data-testid='register-email']").fill(email);
  await modal.locator("[data-testid='register-password']").fill(password);
  await modal.locator("[data-testid='register-confirm-password']").fill(confirmPassword ?? password);
  await modal.locator("[data-testid='register-button']").click();
}

/**
 * UI logout: navigates to /profile and clicks the logout button, then
 * expects the auth modal to reappear. Equivalent to Cypress `cy.logoutRobust`.
 */
export async function uiLogout(page: Page): Promise<void> {
  await page.goto("/profile");
  await page.locator("[data-testid='logout-button']").click();
  await expect(page.locator("[data-testid='modal-content']")).toBeVisible({ timeout: 10_000 });
}

/**
 * Process-level token cache — one apiLogin call per user per test worker run.
 * Avoids 429 rate-limiting when many tests log in as the same user in sequence.
 * Tokens are valid for the duration of the run; no expiry tracking needed here.
 */
const _tokenCache = new Map<UserType, TokenBundle>();

/**
 * Convenience: programmatic login + storage seed.
 * Re-uses a cached token if already fetched in this worker to avoid rate limits.
 */
export async function loginAsTestUser(
  page: Page,
  request: APIRequestContext,
  userType: UserType = "testUser",
): Promise<TestUser> {
  const user = credentials[userType];
  let tokens = _tokenCache.get(userType);
  if (!tokens) {
    tokens = await apiLogin(request, user.email, user.password);
    // Inject email into the bundle so seedTokenInStorage can include it in
    // the local-store payload (required for the viewer's isOwner checks).
    tokens.email = user.email;
    _tokenCache.set(userType, tokens);
  }
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
