/**
 * Port of:
 *   cypress/e2e/ui/theme-switch-basic.cy.js
 *   cypress/e2e/ui/dark-mode-core-tests.cy.js
 *
 * React-stack equivalents:
 *   - Toggle lives in the sidebar footer (src/chrome/ThemeToggle.tsx), a
 *     Mantine Switch with data-testid="theme-toggle".
 *   - Color scheme is reflected on [data-mantine-color-scheme] and persisted
 *     in the `theme-store` localStorage key (shared with the Dash app).
 *
 * NOT ported: the navbar-logo swap test (#navbar-logo-content is a Dash
 * element; the React sidebar logo handling differs).
 */

import { test, expect } from "@fixtures/auth";
import { clickMantineSwitch } from "@fixtures/ui";

const SCHEME_ATTR = "[data-mantine-color-scheme]";

async function currentScheme(page: import("@playwright/test").Page): Promise<string> {
  return (
    (await page.locator(SCHEME_ATTR).first().getAttribute("data-mantine-color-scheme")) ?? ""
  );
}

test.describe("Theme Toggle", () => {
  test.beforeEach(async ({ loginAsUser, page }) => {
    await loginAsUser();
    await page.goto("/dashboards");
    await expect(page.locator(".mantine-AppShell-root")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("toggle is present in the sidebar", async ({ page }) => {
    await expect(page.locator("[data-testid='theme-toggle']")).toBeAttached();
  });

  test("toggles between light and dark and back", async ({ page }) => {
    const before = await currentScheme(page);
    expect(["light", "dark"]).toContain(before);
    const flipped = before === "dark" ? "light" : "dark";

    await clickMantineSwitch(page, "theme-toggle");
    await expect(page.locator(SCHEME_ATTR).first()).toHaveAttribute(
      "data-mantine-color-scheme",
      flipped,
    );

    await clickMantineSwitch(page, "theme-toggle");
    await expect(page.locator(SCHEME_ATTR).first()).toHaveAttribute(
      "data-mantine-color-scheme",
      before,
    );
  });

  test("persists the chosen scheme across reloads via theme-store", async ({
    page,
  }) => {
    const before = await currentScheme(page);
    const flipped = before === "dark" ? "light" : "dark";

    await clickMantineSwitch(page, "theme-toggle");
    await expect(page.locator(SCHEME_ATTR).first()).toHaveAttribute(
      "data-mantine-color-scheme",
      flipped,
    );

    // Persisted in the shared theme-store key…
    const stored = await page.evaluate(() =>
      window.localStorage.getItem("theme-store"),
    );
    expect(stored).toContain(flipped);

    // …and survives a reload.
    await page.reload();
    await expect(page.locator(SCHEME_ATTR).first()).toHaveAttribute(
      "data-mantine-color-scheme",
      flipped,
      { timeout: 15_000 },
    );
  });
});
