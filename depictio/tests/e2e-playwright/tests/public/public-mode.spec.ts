/**
 * Port of (against the React viewer):
 *   cypress/e2e/auth/public/anonymous-profile.cy.js
 *   cypress/e2e/auth/public/api-endpoint-protection.cy.js
 *   cypress/e2e/auth/public/dashboard-access-restrictions.cy.js
 *   cypress/e2e/auth/public/new-dashboard-button-behavior.cy.js (replaced)
 *   cypress/e2e/auth/public/enable-interactive-mode.cy.js       (replaced)
 *
 * React-stack contract differs from the old Dash UI:
 *   - Temporary users are auto-minted at SPA bootstrap (src/main.tsx
 *     bootstrapSession) — there is NO "Login as a temporary user" upgrade
 *     flow anymore, so the two fully-skipped Cypress specs are replaced by
 *     assertions on the new behaviour.
 *   - Write affordances are DISABLED, not hidden (new-dashboard-btn,
 *     add-cli-config-btn, Edit Password / Logout on profile).
 *   - Creation is additionally blocked at the API level (401/403).
 *
 * Only runs when the backend reports is_public_mode=true.
 */

import { test, expect, getAuthMode, API_URL, API_PREFIX } from "@fixtures/auth";

test.describe("Public Mode", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(!is_public_mode, "Not running in public mode.");
  });

  test.describe("Temporary user bootstrap", () => {
    test("auto-mints a temporary session and reaches /dashboards without login", async ({
      page,
    }) => {
      await page.goto("/dashboards");
      await expect(page).toHaveURL(/\/dashboards/, { timeout: 15_000 });
      await expect(page).not.toHaveURL(/\/auth/);

      // The bootstrap persisted a usable token.
      await expect
        .poll(async () =>
          page.evaluate(() => {
            try {
              const raw = window.localStorage.getItem("local-store");
              return raw ? Boolean(JSON.parse(raw).access_token) : false;
            } catch {
              return false;
            }
          }),
        )
        .toBe(true);
    });

    test("profile shows the temporary user, no editing capabilities", async ({
      page,
    }) => {
      await page.goto("/profile");

      // Email row shows a temp_user_*@depictio.temp address — never a real
      // seeded account.
      const emailRow = page.locator("[data-testid='profile-info-email']");
      await expect(emailRow).toBeVisible({ timeout: 15_000 });
      await expect(emailRow).toContainText(/temp_user_.*@depictio\.temp/);
      await expect(emailRow).not.toContainText("@example.com");

      // Write affordances are disabled, not hidden.
      await expect(page.locator("[data-testid='edit-password-button']")).toBeDisabled();
      await expect(page.locator("[data-testid='logout-button']")).toBeDisabled();
    });
  });

  test.describe("Dashboard list restrictions", () => {
    test("new-dashboard button is visible but disabled", async ({ page }) => {
      await page.goto("/dashboards");
      const btn = page.locator("[data-testid='new-dashboard-btn']");
      await expect(btn).toBeVisible({ timeout: 15_000 });
      await expect(btn).toBeDisabled();
    });

    test("public dashboards are listed and viewable", async ({ page }) => {
      await page.goto("/dashboards");
      const cards = page.locator("[data-testid='dashboard-card']");
      await expect(cards.first()).toBeVisible({ timeout: 15_000 });

      // Open the first public dashboard and verify the viewer renders.
      await cards.first().click();
      await expect(page).toHaveURL(/\/dashboard\//, { timeout: 15_000 });
      await expect(page.locator("body")).not.toContainText("404");
    });

    test("CLI config creation is disabled for temporary users", async ({
      page,
    }) => {
      await page.goto("/cli-agents");
      const addBtn = page.locator("[data-testid='add-cli-config-btn']");
      await expect(addBtn).toBeVisible({ timeout: 15_000 });
      await expect(addBtn).toBeDisabled();
    });
  });

  test.describe("API endpoint protection", () => {
    /** Pull the temporary user's token out of the SPA's localStorage. */
    async function tempUserToken(page: import("@playwright/test").Page): Promise<string> {
      await page.goto("/dashboards");
      await expect
        .poll(async () =>
          page.evaluate(() => {
            try {
              const raw = window.localStorage.getItem("local-store");
              return raw ? (JSON.parse(raw).access_token as string) ?? "" : "";
            } catch {
              return "";
            }
          }),
        )
        .not.toBe("");
      return page.evaluate(
        () => JSON.parse(window.localStorage.getItem("local-store")!).access_token as string,
      );
    }

    test("rejects dashboard creation from anonymous users", async ({
      page,
      request,
    }) => {
      const token = await tempUserToken(page);
      const res = await request.post(
        `${API_URL}${API_PREFIX}/dashboards/save/507f1f77bcf86cd799439011`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          data: {
            id: "507f1f77bcf86cd799439011",
            title: "Test Dashboard",
            dashboard_id: "507f1f77bcf86cd799439011",
            project_id: "507f1f77bcf86cd799439012",
            permissions: { owners: [], viewers: [] },
          },
        },
      );
      expect([401, 403, 422]).toContain(res.status());
    });

    test("allows anonymous users to list public dashboards", async ({
      page,
      request,
    }) => {
      const token = await tempUserToken(page);
      const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/list`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(res.status()).toBe(200);
      expect(Array.isArray(await res.json())).toBe(true);
    });
  });
});
