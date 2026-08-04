/**
 * Regression coverage for the "Invalid token" session-expiry bug.
 *
 * Symptom: the admin "Log & Task" tab (and any long-open view) started
 * failing every request with FastAPI's 401 {"detail":"Invalid token"} about an
 * hour after page load.
 *
 * Cause: the viewer's `authHeaders()` reads `access_token` out of localStorage
 * with no expiry check, and the SPA only refreshed the token once at boot.
 * `/auth/refresh` mints a 1 h access token, so any page that outlived it kept
 * replaying a dead credential with nothing to renew it.
 *
 * Fixes under test:
 *   1. `/monitoring/*` helpers now go through `authFetch` (refresh + 1 retry).
 *   2. `startSessionKeepAlive()` keeps localStorage fresh for the ~90 helpers
 *      that use the synchronous `authHeaders()` and cannot await a refresh.
 *
 * These are deliberately API/behaviour level rather than unit tests: the bug
 * only appears in the interaction between a lapsed stored token, the refresh
 * endpoint, and the auth dependency guarding each route.
 */

import {
  test,
  expect,
  apiLogin,
  seedTokenInStorage,
  API_URL,
  API_PREFIX,
} from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

/** A syntactically valid JWT whose signature will not verify. Stands in for
 *  "the browser is holding a credential the server will not accept", which is
 *  what an expired token looks like from the client's side. */
const DEAD_TOKEN =
  "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9." +
  "eyJzdWIiOiIwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAiLCJleHAiOjF9." +
  "ZGVhZGJlZWY";

test.describe("Session expiry / token refresh", () => {
  test("strict endpoints reject a dead token with 'Invalid token'", async ({
    request,
  }) => {
    // This is the exact response the user reported seeing in the admin UI.
    const res = await request.get(
      `${API_URL}${API_PREFIX}/monitoring/tasks?limit=1`,
      { headers: { Authorization: `Bearer ${DEAD_TOKEN}` } },
    );
    expect(res.status()).toBe(401);
    expect((await res.json()).detail).toBe("Invalid token");
  });

  test("a refresh token recovers a dead session", async ({ request }) => {
    const tokens = await apiLogin(
      request,
      credentials.adminUser.email,
      credentials.adminUser.password,
    );

    // What authFetch / the keep-alive do when they see a lapsed token.
    const refreshed = await request.post(
      `${API_URL}${API_PREFIX}/auth/refresh`,
      { data: { refresh_token: tokens.refresh_token } },
    );
    expect(refreshed.ok()).toBeTruthy();
    const { access_token: fresh } = await refreshed.json();
    expect(fresh).toBeTruthy();

    // The renewed credential works on the endpoint that was 401ing.
    const retry = await request.get(
      `${API_URL}${API_PREFIX}/monitoring/tasks?limit=1`,
      { headers: { Authorization: `Bearer ${fresh}` } },
    );
    expect(retry.status()).toBe(200);
  });

  test("Log & Task tab recovers when the token lapses mid-session", async ({
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

    // The token must be poisoned AFTER boot, not before. `bootstrapSession()`
    // runs `validateSession()` on every page load, which refreshes a lapsed
    // token before React mounts — so a page that *starts* with a dead token
    // silently self-heals and never exercises this bug. The real-world failure
    // is a tab that has been sitting open, i.e. one that booted fine and then
    // crossed the 1 h expiry while mounted. Reproduce exactly that.
    await page.goto("/admin");
    await expect(page.getByRole("tab", { name: /Log & Task/i })).toBeVisible({
      timeout: 20_000,
    });

    await page.evaluate((dead) => {
      const raw = window.localStorage.getItem("local-store");
      if (!raw) return;
      const parsed = JSON.parse(raw);
      parsed.access_token = dead;
      parsed.expire_datetime = new Date(Date.now() - 60_000).toISOString();
      window.localStorage.setItem("local-store", JSON.stringify(parsed));
    }, DEAD_TOKEN);

    // Open the tab so its panes start polling with the now-dead credential.
    await page.getByRole("tab", { name: /Log & Task/i }).click();

    // The panel renders the raw backend detail in an Alert on failure, so this
    // asserts on the exact string the user reported. Pre-fix this appears and
    // never clears; post-fix authFetch/keep-alive renew the token instead.
    await expect(page.getByText("Invalid token")).toHaveCount(0, {
      timeout: 20_000,
    });

    // And the session was genuinely renewed, not merely un-rendered.
    await expect
      .poll(
        async () =>
          page.evaluate(() => {
            const raw = window.localStorage.getItem("local-store");
            return raw ? JSON.parse(raw).access_token : null;
          }),
        { timeout: 20_000 },
      )
      .not.toBe(DEAD_TOKEN);
  });
});
