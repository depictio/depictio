/**
 * Browsing dashboard versions in the viewer.
 *
 * The first version-history E2E in this suite. Two things here can only be
 * checked in a real browser, and both are the point of the stage:
 *
 * 1. **In-place** means in-place. A selection that quietly did a full page load
 *    would look identical in a screenshot and identical to every unit test — so
 *    a navigation counter installed before the app boots is the only honest
 *    assertion.
 * 2. **The editor must still open a new tab.** A past version loaded into
 *    editor state is one stray drag away from being autosaved over the present.
 *    That is the safety rule the whole feature is built around, and it lives in
 *    a single `mode` prop, so it is exactly the kind of thing a refactor loses.
 */

import { test, expect, type Page } from "@fixtures/auth";
import { createDashboard, deleteDashboard } from "@fixtures/dashboard";

/** Count full page loads, so "it swapped in place" is measurable rather than
 *  inferred. Must be installed before the app boots. */
async function trackNavigations(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __navCount?: number };
    w.__navCount = (w.__navCount ?? 0) + 1;
  });
}

async function navCount(page: Page): Promise<number> {
  return page.evaluate(
    () => (window as unknown as { __navCount?: number }).__navCount ?? 0,
  );
}

/** Open the drawer and wait for the timeline to have at least one row. */
async function openVersionDrawer(page: Page): Promise<void> {
  await page.locator("[data-testid='version-history-button']").click();
  await expect(page.locator("[data-testid='version-drawer']")).toBeVisible();
  await expect(
    page.locator("[data-testid='version-timeline-item']").first(),
  ).toBeVisible({ timeout: 15_000 });
}

test.describe("Version browsing", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Version history requires an authenticated user.",
  );

  let title: string;

  test.beforeEach(async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    title = `Version Browsing ${new Date().toISOString().replace(/:/g, "-")}`;
    await page.goto("/dashboards");
    await createDashboard(page, title);
  });

  test.afterEach(async ({ page }) => {
    await page.goto("/dashboards");
    await deleteDashboard(page, title).catch(() => undefined);
  });

  test("selecting a version swaps the canvas without a page load", async ({
    page,
  }) => {
    await trackNavigations(page);
    await page.goto("/dashboards");
    await page
      .locator("[data-testid='dashboard-card']")
      .filter({ hasText: title })
      .first()
      .click();

    const before = await navCount(page);
    await openVersionDrawer(page);
    await page.locator("[data-testid='version-timeline-item']").first().click();

    await expect(page.locator("[data-testid='version-banner']")).toBeVisible();
    // The drawer stays open beside the canvas — the whole difference from the
    // old open-a-new-tab behaviour.
    await expect(page.locator("[data-testid='version-drawer']")).toBeVisible();
    await expect(page).toHaveURL(/[?&]version=/);
    expect(await navCount(page)).toBe(before);
  });

  test("arrow keys step through versions", async ({ page }) => {
    await page.goto("/dashboards");
    await page
      .locator("[data-testid='dashboard-card']")
      .filter({ hasText: title })
      .first()
      .click();
    await openVersionDrawer(page);

    const rows = page.locator("[data-testid='version-timeline-item']");
    const count = await rows.count();
    test.skip(count < 2, "Needs at least two versions to step between.");

    await rows.first().click();
    const first = new URL(page.url()).searchParams.get("version");

    await page.keyboard.press("ArrowDown");
    await expect
      .poll(() => new URL(page.url()).searchParams.get("version"))
      .not.toBe(first);

    await page.keyboard.press("ArrowUp");
    await expect
      .poll(() => new URL(page.url()).searchParams.get("version"))
      .toBe(first);
  });

  test("browser back steps out of the preview", async ({ page }) => {
    await page.goto("/dashboards");
    await page
      .locator("[data-testid='dashboard-card']")
      .filter({ hasText: title })
      .first()
      .click();
    await openVersionDrawer(page);
    await page.locator("[data-testid='version-timeline-item']").first().click();
    await expect(page.locator("[data-testid='version-banner']")).toBeVisible();

    await page.goBack();

    // pushState, not replaceState — Back is expected to undo a version switch.
    await expect(page.locator("[data-testid='version-banner']")).toBeHidden();
    await expect(page).not.toHaveURL(/[?&]version=/);
  });

  test("'Back to current' returns to the live dashboard", async ({ page }) => {
    await page.goto("/dashboards");
    await page
      .locator("[data-testid='dashboard-card']")
      .filter({ hasText: title })
      .first()
      .click();
    await openVersionDrawer(page);
    await page.locator("[data-testid='version-timeline-item']").first().click();

    await page.locator("[data-testid='version-banner-exit']").click();

    await expect(page.locator("[data-testid='version-banner']")).toBeHidden();
    await expect(page).not.toHaveURL(/[?&]version=/);
  });

  test("browsing never writes to the dashboard", async ({ page }) => {
    // The failure this guards: NotesFooter saves by re-reading the dashboard
    // and POSTing it back, which during a preview would persist the *snapshot*
    // over the live document.
    const saves: string[] = [];
    await page.route("**/dashboards/save/**", async (route) => {
      saves.push(route.request().url());
      await route.continue();
    });

    await page.goto("/dashboards");
    await page
      .locator("[data-testid='dashboard-card']")
      .filter({ hasText: title })
      .first()
      .click();
    await openVersionDrawer(page);
    await page.locator("[data-testid='version-timeline-item']").first().click();
    await expect(page.locator("[data-testid='version-banner']")).toBeVisible();

    await page.waitForTimeout(1_500);

    expect(saves).toEqual([]);
  });

  test("the editor still opens a version in a new tab", async ({
    page,
    context,
  }) => {
    // The most important test in this stage. In-place browsing is viewer-only
    // precisely because the editor autosaves, and the distinction is one prop.
    await page.goto("/dashboards");
    await page
      .locator("[data-testid='dashboard-card']")
      .filter({ hasText: title })
      .first()
      .click();
    const viewerUrl = page.url();
    const dashboardId = viewerUrl.split("/dashboard/")[1]?.split(/[?#]/)[0];
    test.skip(!dashboardId, "Could not resolve the dashboard id.");

    await page.goto(`/dashboard-edit/${dashboardId}`);
    await openVersionDrawer(page);

    const popupPromise = context.waitForEvent("page");
    await page.locator("[data-testid='version-preview']").first().click();
    const popup = await popupPromise;

    await expect(popup).toHaveURL(/[?&]version=/);
    // And the editor itself did not move.
    await expect(page).toHaveURL(new RegExp(`/dashboard-edit/${dashboardId}`));
    await expect(page.locator("[data-testid='version-banner']")).toBeHidden();
    await popup.close();
  });
});
