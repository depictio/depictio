/**
 * Dashboard content font-size control (issue #854).
 *
 * The control lives in the Settings drawer (src/chrome/SettingsDrawer.tsx,
 * data-testid="font-size-control"): A− / A+ step through [0.85, 1, 1.15, 1.3];
 * the preference is persisted in the `depictio-ui-scale` localStorage key.
 * The scale applies to the dashboard content container only
 * (data-testid="dashboard-content", via a `--mantine-scale` override plus
 * re-scaled font-size tokens) — the app chrome (:root) stays at 1.
 */

import { test, expect } from "@fixtures/auth";
import { createDashboard, deleteDashboard } from "@fixtures/dashboard";

type Page = import("@playwright/test").Page;

async function scaleVarOn(page: Page, selector: string): Promise<string> {
  return page.evaluate(
    (sel) =>
      getComputedStyle(document.querySelector(sel) ?? document.documentElement)
        .getPropertyValue("--mantine-scale")
        .trim(),
    selector,
  );
}

test.describe("Font size control", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Dashboard creation requires an authenticated user.",
  );

  test("A+ in the Settings drawer scales the content only and persists", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/dashboards");
    await expect(page).toHaveURL(/\/dashboards/);

    const title = `Font Scale ${new Date().toISOString().replace(/:/g, "-")}`;
    await createDashboard(page, title);

    // Open the dashboard viewer via the card's link.
    await page
      .locator("[data-testid='dashboard-card']")
      .filter({ hasText: title })
      .first()
      .locator("a[href*='/dashboard/']")
      .first()
      .click();
    await expect(page).toHaveURL(/\/dashboard\//, { timeout: 15_000 });

    // The control moved out of the header into the Settings drawer.
    await page.getByRole("button", { name: "Settings" }).click();
    const control = page.locator("[data-testid='font-size-control']");
    await expect(control).toBeVisible({ timeout: 15_000 });

    // A+ → next step up (1 → 1.15), persisted and applied to the content
    // container — while the chrome (:root) stays at 1.
    await page.locator("[data-testid='font-size-increase']").click();
    expect(
      await page.evaluate(() => window.localStorage.getItem("depictio-ui-scale")),
    ).toBe("1.15");
    expect(await scaleVarOn(page, "[data-testid='dashboard-content']")).toBe("1.15");
    expect(await scaleVarOn(page, ":root")).toBe("1");

    // Survives a reload without reopening the drawer.
    await page.reload();
    await expect(page.locator("[data-testid='dashboard-content']")).toBeAttached({
      timeout: 15_000,
    });
    expect(await scaleVarOn(page, "[data-testid='dashboard-content']")).toBe("1.15");

    // Reset from the drawer brings the content back to 100%.
    await page.getByRole("button", { name: "Settings" }).click();
    await expect(control).toBeVisible({ timeout: 15_000 });
    await page.locator("[data-testid='font-size-reset']").click();
    expect(
      await page.evaluate(() => window.localStorage.getItem("depictio-ui-scale")),
    ).toBe("1");
    await expect(page.locator("[data-testid='font-size-reset']")).toHaveCount(0);
    expect(await scaleVarOn(page, "[data-testid='dashboard-content']")).toBe("1");

    // Cleanup.
    await page.goto("/dashboards");
    await deleteDashboard(page, title);
  });
});
