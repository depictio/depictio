import { test, expect, Route } from "@playwright/test";

/**
 * Session-refresh contract for the viewer's shared `authFetch` layer.
 *
 * Every authenticated request goes through `authFetch`, which refreshes the
 * access token when it is at or near expiry. That is load-bearing (a login
 * mints a 1 h access token against a 7 day refresh token) but it must not be
 * applied to the requests that merely *ask* whether a session exists, or
 * logging out stops working: sign-out is client-side only, the refresh token
 * stays valid server-side, and a minting probe on `/auth` mints a new access
 * token off it and bounces the user straight back into the app.
 *
 * These specs drive the real UI against a fully mocked backend, so they hold
 * in every auth mode and do not depend on the deployment the suite runs
 * against. The backend contract they model is the real one:
 *
 *   - `/auth/refresh` overwrites the stored access token
 *     (user_endpoints/routes.py `refresh_token_browser`).
 *   - a bearer authenticates only while it is the currently stored token
 *     (user_endpoints/core_functions.py `_async_fetch_user_from_token`).
 *   - `/auth/me/optional` answers 200 with `user: null` for an unusable token.
 */

const USER = { id: "u1", email: "session_refresh@example.com", is_admin: false };

function statusBody(user: unknown) {
  return {
    auth_mode: "standard",
    user,
    is_public_mode: false,
    is_single_user_mode: false,
    is_demo_mode: false,
    registration_disabled: false,
    is_dev_mode: true,
    walkthrough_disabled: true,
    unauthenticated_mode: false,
    google_oauth_enabled: false,
  };
}

function bearerOf(route: Route): string | null {
  const header = route.request().headers()["authorization"];
  return header ? header.replace(/^Bearer\s+/i, "") : null;
}

/** Seed the viewer's `local-store` session. `expire` omitted reproduces what
 *  the auth fixture writes: no expiry, which `authFetch` treats as "refresh
 *  now". */
async function seedSession(
  page: import("@playwright/test").Page,
  access: string,
  refresh: string,
  expire?: string,
): Promise<void> {
  await page.addInitScript(
    ([a, r, e]) => {
      const payload: Record<string, unknown> = {
        access_token: a,
        refresh_token: r,
        logged_in: true,
        user_id: "u1",
        email: "session_refresh@example.com",
      };
      if (e) payload.expire_datetime = e;
      window.localStorage.setItem("local-store", JSON.stringify(payload));
    },
    [access, refresh, expire ?? ""] as const,
  );
}

test.describe("Session refresh", () => {
  test("logging out is not undone by a token refresh", async ({ page }) => {
    // Server-side token store: only this exact string authenticates.
    let storedAccess = "seeded-token";
    let refreshes = 0;

    await page.route("**/api/v1/auth/refresh", async (route) => {
      refreshes += 1;
      storedAccess = `refreshed-${refreshes}`;
      await route.fulfill({
        json: {
          access_token: storedAccess,
          expire_datetime: "2030-01-01 00:00:00",
          token_type: "bearer",
        },
      });
    });
    await page.route("**/api/v1/auth/me/optional**", async (route) => {
      const tok = bearerOf(route);
      await route.fulfill({ json: statusBody(tok === storedAccess ? USER : null) });
    });
    await page.route("**/api/v1/auth/me", async (route) => {
      if (bearerOf(route) !== storedAccess) {
        await route.fulfill({ status: 401, json: { detail: "Invalid token" } });
        return;
      }
      await route.fulfill({ json: { ...USER, groups: [], tokens: [] } });
    });
    await page.route("**/api/v1/utils/status**", (r) =>
      r.fulfill({ json: { version: "test", status: "ok" } }),
    );
    await page.route("**/api/v1/dashboards/list**", (r) => r.fulfill({ json: [] }));
    await page.route("**/api/v1/projects/get/all**", (r) => r.fulfill({ json: [] }));

    await seedSession(page, "seeded-token", "live-refresh");

    await page.goto("/profile");
    await page.locator("[data-testid='logout-button']").click();

    // The auth card renders and the app STAYS on /auth. The regression this
    // guards let /auth mint a fresh token off the still-live refresh token,
    // see a logged-in user, and redirect back to /dashboards.
    await expect(page.locator("[data-testid='modal-content']")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page).toHaveURL(/\/auth/);

    // And it must still be signed out a moment later — a late refresh
    // resolving after logout would put a working session back and redirect.
    //
    // The session token itself is not asserted here: `addInitScript` re-runs
    // on every navigation, so the harness re-seeds `local-store` as /auth
    // loads. What matters is that the app does not *act* on it — a token the
    // server no longer recognises leaves the user on the login screen.
    await page.waitForTimeout(1_500);
    await expect(page).toHaveURL(/\/auth/);
    await expect(page.locator("[data-testid='modal-content']")).toBeVisible();
  });

  test("an expired access token is refreshed for a real API call", async ({ page }) => {
    // The case the refresh machinery exists for: the access token died an hour
    // ago, the refresh token is still good.
    let storedAccess = "expired-token";
    let refreshes = 0;
    const listBearers: (string | null)[] = [];

    await page.route("**/api/v1/auth/refresh", async (route) => {
      refreshes += 1;
      storedAccess = "fresh-token";
      await route.fulfill({
        json: {
          access_token: storedAccess,
          expire_datetime: "2030-01-01 00:00:00",
          token_type: "bearer",
        },
      });
    });
    await page.route("**/api/v1/auth/me/optional**", async (route) => {
      const tok = bearerOf(route);
      await route.fulfill({ json: statusBody(tok === storedAccess ? USER : null) });
    });
    // Strict endpoint: 401s anything that is not the current token.
    await page.route("**/api/v1/dashboards/list**", async (route) => {
      const tok = bearerOf(route);
      listBearers.push(tok);
      if (tok !== storedAccess) {
        await route.fulfill({ status: 401, json: { detail: "Invalid token" } });
        return;
      }
      await route.fulfill({ json: [] });
    });
    await page.route("**/api/v1/utils/status**", (r) =>
      r.fulfill({ json: { version: "test", status: "ok" } }),
    );
    await page.route("**/api/v1/projects/get/all**", (r) => r.fulfill({ json: [] }));

    const anHourAgo = new Date(Date.now() - 3_600_000)
      .toISOString()
      .replace("T", " ")
      .slice(0, 19);
    await seedSession(page, "expired-token", "live-refresh", anHourAgo);

    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/);
    await expect
      .poll(() => listBearers.length, { timeout: 15_000 })
      .toBeGreaterThan(0);

    expect(refreshes, "an expired token must be refreshed").toBeGreaterThan(0);
    // Every data request carried the refreshed credential, not the dead one.
    expect(listBearers.every((t) => t === "fresh-token")).toBe(true);
    expect(
      await page.evaluate(
        () => JSON.parse(localStorage.getItem("local-store") ?? "{}").access_token,
      ),
    ).toBe("fresh-token");
  });
});
