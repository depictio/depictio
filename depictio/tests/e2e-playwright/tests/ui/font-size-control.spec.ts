/**
 * Dashboard-wide font-size control (issue #854).
 *
 * The control lives in the dashboard viewer/editor header
 * (src/chrome/Header.tsx, data-testid="font-size-control"): A− / A+ step
 * through [0.85, 1, 1.15, 1.3]; the percent label appears when off 100% and
 * doubles as reset. The preference is persisted in the `depictio-ui-scale`
 * localStorage key and applied through Mantine's `theme.scale`
 * (`--mantine-scale` on :root).
 */

import { test, expect } from "@fixtures/auth";
import { createDashboard, deleteDashboard } from "@fixtures/dashboard";

async function mantineScale(page: import("@playwright/test").Page): Promise<string> {
  return page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--mantine-scale").trim(),
  );
}

test.describe("Font size control", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Dashboard creation requires an authenticated user.",
  );

  test("A+ / reset adjust the UI scale and persist across reloads", async ({
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

    const control = page.locator("[data-testid='font-size-control']");
    await expect(control).toBeAttached({ timeout: 15_000 });

    // A+ → next step up (1 → 1.15), persisted and applied via --mantine-scale.
    await page.locator("[data-testid='font-size-increase']").click();
    expect(
      await page.evaluate(() => window.localStorage.getItem("depictio-ui-scale")),
    ).toBe("1.15");
    expect(await mantineScale(page)).toBe("1.15");

    // Survives a reload.
    await page.reload();
    await expect(control).toBeAttached({ timeout: 15_000 });
    expect(await mantineScale(page)).toBe("1.15");

    // The percent label doubles as reset.
    await page.locator("[data-testid='font-size-reset']").click();
    expect(
      await page.evaluate(() => window.localStorage.getItem("depictio-ui-scale")),
    ).toBe("1");
    await expect(page.locator("[data-testid='font-size-reset']")).toHaveCount(0);

    // Cleanup.
    await page.goto("/dashboards");
    await deleteDashboard(page, title);
  });
});
