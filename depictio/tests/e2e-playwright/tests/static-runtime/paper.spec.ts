/**
 * Bundles draw Paper (`glass`), the app's default chrome — gated for a
 * read-only file: no Edit / Save, no profile tile, no server card, no "All
 * dashboards", a static-snapshot card at the sidebar's foot, the Plotly styling
 * of the live app (`glassPlotly`: transparent paper), and zero network
 * requests. `?chrome=base` still opts into Classic.
 */
import { expect, test } from "@playwright/test";

import {
  PENGUINS_MANIFEST,
  TABS_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

test("a bundle draws the Paper shell, read-only, with zero network", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  const url = injectedBundleUrl(TABS_MANIFEST);
  await page.goto(url);

  await expect(page.locator(".hy-shell[data-testid='app-shell']")).toBeVisible();
  await expect(page.getByText("A hand-written fixture manifest")).toBeVisible();

  // Nothing that edits, saves or reaches a server or an account.
  await expect(page.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save", exact: true })).toHaveCount(0);
  await expect(page.getByTestId("profile-tile")).toHaveCount(0);
  await expect(page.getByTestId("hy-status")).toHaveCount(0);
  await expect(page.locator('a[href="/dashboards"]')).toHaveCount(0);
  await expect(page.locator('a[href="/profile"]')).toHaveCount(0);
  await expect(page.locator("a.hy-top-brand")).toHaveCount(0); // identity, not a link

  // The rail switches tabs in place.
  await page.locator('nav.hy-side a[aria-label="Distributions"]').click();
  await expect(page.getByText("Second tab body.")).toBeVisible();
  expect(page.url()).toBe(url);

  // Opened, the sidebar's foot says what the file is (its card opens the
  // export provenance) and leads to the project; chrome.spec.ts covers both.
  await page.getByTestId("glass-side-toggle").click();
  const side = page.locator("nav.hy-side");
  await expect(side.getByTestId("hy-snapshot-card")).toContainText("Static snapshot");
  await side.getByTestId("hy-snapshot").click();
  await expect(page.getByTestId("static-snapshot-details")).toContainText("curator@example.org");
  await page.keyboard.press("Escape");
  await expect(side.getByText("All dashboards")).toHaveCount(0);

  // The Guide opens in place (no navigation, nothing fetched).
  await side.getByRole("link", { name: "Guide" }).click();
  await expect(page.getByText("Move between tabs")).toBeVisible();
  expect(page.url().split("?")[0]).toBe(url);
  await page.getByRole("button", { name: /Back to/ }).first().click();

  // Plotly figures take the live app's Paper styling: a transparent paper.
  await page.locator('nav.hy-side a[href$="f1x70000000000000000c0de"]').first().click();
  await expect(page.getByText("Fixture scatter")).toBeVisible();
  const bg = await page
    .locator(".js-plotly-plot .main-svg")
    .first()
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).toBe("rgba(0, 0, 0, 0)");

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("the live penguins bundle renders under Paper with zero network", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  await page.goto(injectedBundleUrl(PENGUINS_MANIFEST));
  await expect(page.locator(".hy-shell")).toBeVisible();
  await expect(page.locator(".react-grid-item").first()).toBeVisible();
  await expect(page.locator(".js-plotly-plot").first()).toBeVisible({ timeout: 20_000 });
  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("?chrome=base still opts into Classic", async ({ page }) => {
  await blockNetwork(page);
  await page.goto(`${injectedBundleUrl(TABS_MANIFEST)}?chrome=base`);
  await expect(page.getByText("A hand-written fixture manifest")).toBeVisible();
  await expect(page.locator(".hy-shell")).toHaveCount(0);
  await expect(page.locator(".mantine-AppShell-navbar")).toBeAttached();
});
