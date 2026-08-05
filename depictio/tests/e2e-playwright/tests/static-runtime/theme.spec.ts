/**
 * Static-bundle UX: frozen figures follow the light/dark theme toggle, the
 * Depictio logo renders offline (inlined data: URI, no server path), and
 * backend-dependent affordances (edit button, management links, auth chrome)
 * are hidden — a bundle is a read-only snapshot.
 */
import { expect, test, type Page } from "@playwright/test";

import { blockNetwork, injectedBundleUrl, skipUnlessBundleBuilt } from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

/** Paper background of the first Plotly figure (`.main-svg` carries it). */
async function plotBackground(page: Page): Promise<string> {
  return page
    .locator(".js-plotly-plot .main-svg")
    .first()
    .evaluate((el) => getComputedStyle(el).backgroundColor);
}

test("frozen figures re-theme when the color scheme toggles", async ({ page }) => {
  await blockNetwork(page);
  await page.goto(injectedBundleUrl());
  await expect(page.getByText("Fixture scatter")).toBeVisible();

  const lightBg = await plotBackground(page);

  // The theme toggle lives in the (collapsed-by-default) tab sidebar.
  await page.getByLabel("Toggle tab sidebar").click();
  // Mantine's Switch input is visually hidden — dispatch the click directly.
  await page.getByTestId("theme-toggle").evaluate((el) => (el as HTMLElement).click());

  // The figure renderer re-requests on scheme flip; the shim re-templates the
  // frozen payload, so the plot paper must actually change color.
  await expect
    .poll(async () => plotBackground(page), { timeout: 10_000 })
    .not.toBe(lightBg);

  // And back again — the manifest payload must not have been mutated in place.
  await page.getByTestId("theme-toggle").evaluate((el) => (el as HTMLElement).click());
  await expect
    .poll(async () => plotBackground(page), { timeout: 10_000 })
    .toBe(lightBg);
});

test("logo is inlined (renders from file:// with zero network)", async ({ page }) => {
  await blockNetwork(page);
  await page.goto(injectedBundleUrl());

  const logo = page.locator('img[alt="Depictio"]');
  await expect(logo).toBeVisible();
  // Inlined data: URI — not the server-only /dashboard/logos/... path — and
  // actually decoded (naturalWidth > 0 means the image loaded, not alt text).
  await expect(logo).toHaveAttribute("src", /^data:image\/svg/);
  const naturalWidth = await logo.evaluate((el) => (el as HTMLImageElement).naturalWidth);
  expect(naturalWidth).toBeGreaterThan(0);
});

test("edit and management affordances are hidden in the read-only bundle", async ({
  page,
}) => {
  await blockNetwork(page);
  await page.goto(injectedBundleUrl());
  await expect(page.getByText("Fixture scatter")).toBeVisible();

  // Header: no Edit button (the editor route does not exist in a bundle).
  await expect(page.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);

  // Sidebar (opened): no management navigation, no server/profile chrome —
  // but the client-side theme toggle stays.
  await page.getByLabel("Toggle tab sidebar").click();
  await expect(page.getByTestId("theme-toggle")).toBeAttached();
  await expect(page.getByText("Back to Dashboards")).toHaveCount(0);
  await expect(page.getByText("Server offline")).toHaveCount(0);
  await expect(page.locator('a[href="/dashboards"]')).toHaveCount(0);
});
