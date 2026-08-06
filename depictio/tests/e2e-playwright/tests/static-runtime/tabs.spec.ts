/**
 * A bundled tab family switches IN PLACE.
 *
 * The viewer's left-rail pills are `<a href="/dashboard/<id>">` anchors, which
 * on `file://` are navigations to a path that does not exist. The static
 * runtime intercepts them and re-renders App against the manifest's other tab
 * documents — so the assertions here are: the pills exist, clicking one swaps
 * the rendered dashboard, the document never navigates, and nothing reaches
 * the network on the way.
 */
import { expect, test, type Page } from "@playwright/test";

import {
  FIXTURE_MANIFEST,
  TABS_MANIFEST,
  blockNetwork,
  injectedBundleUrl,
  skipUnlessBundleBuilt,
} from "./helpers";

test.beforeEach(() => skipUnlessBundleBuilt());

const tabPill = (page: Page, name: string) =>
  page.locator('[role="tab"]').filter({ hasText: name });

test("clicking a rail pill switches tab in place, offline", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  const url = injectedBundleUrl(TABS_MANIFEST);
  await page.goto(url);

  // Entry tab: the basic fixture's dashboard, plus a pill per family member.
  await expect(page.getByText("A hand-written fixture manifest")).toBeVisible();
  await expect(page.locator('[role="tab"]')).toHaveCount(3);
  for (const name of ["Overview", "Distributions", "Details"]) {
    await expect(tabPill(page, name)).toHaveCount(1);
  }

  await tabPill(page, "Distributions").click();
  await expect(page.getByText("Second tab body.")).toBeVisible();
  await expect(page.getByText("A hand-written fixture manifest")).toHaveCount(0);
  // In place: same document, no navigation (pushState on file:// would throw).
  expect(page.url()).toBe(url);

  await tabPill(page, "Details").click();
  await expect(page.getByText("Third tab body.")).toBeVisible();
  await expect(page.getByText("Second tab body.")).toHaveCount(0);

  // …and back to the entry tab, which must render exactly as it did on load.
  await tabPill(page, "Overview").click();
  await expect(page.getByText("A hand-written fixture manifest")).toBeVisible();
  await expect(page.getByText("43.92")).toBeVisible();

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("the rail carries the export provenance", async ({ page }) => {
  await blockNetwork(page);
  await page.goto(injectedBundleUrl(TABS_MANIFEST));

  const rail = page.locator(".mantine-AppShell-navbar");
  await expect(rail.getByText("Static export")).toBeVisible();
  await expect(
    rail.getByText("A self-contained copy of this dashboard"),
  ).toBeVisible();
  await expect(rail.getByText("curator@example.org")).toBeVisible();
  // Naive timestamp in the manifest — read as UTC, not as local time.
  await expect(rail.getByText("2026-08-03 09:15 UTC")).toBeVisible();
  await expect(rail.getByText("https://demo.depictio.example")).toBeVisible();
  await expect(rail.getByText("Fixture project")).toBeVisible();
  await expect(rail.getByText("depictio 0.0.0-fixture")).toBeVisible();
  await expect(rail.getByText("Producer")).toBeVisible();

  // The one link a bundle can honour keeps its real target (and is NOT
  // swallowed by the in-place navigation interceptor).
  await expect(rail.getByRole("link", { name: "open in a new tab" })).toHaveAttribute(
    "href",
    /^https:\/\/demo\.depictio\.example\/dashboard\//,
  );
});

test("a Celery-computed view says filters do not reach it", async ({ page }) => {
  await blockNetwork(page);
  await page.goto(injectedBundleUrl(TABS_MANIFEST));
  await tabPill(page, "Distributions").click();

  const badge = page.locator('[data-static-reason="celery_compute"]');
  await expect(badge).toBeVisible();
  await expect(badge).toHaveAttribute("data-static-tier", "frozen");

  await badge.hover();
  const card = page.locator(".mantine-HoverCard-dropdown");
  await expect(card).toContainText("Filters do not affect this view");
  await expect(card).toContainText(
    "This view comes from a heavy computation that ran once",
  );

  // This fixture's build note reads as prose, so it is offered — one click
  // away, never as the headline.
  const detail = card.locator("[data-testid='static-tier-detail']");
  await expect(detail).toHaveCount(0);
  await card.locator("[data-testid='static-tier-detail-toggle']").click();
  await expect(detail).toHaveText(
    "computed at export time — filters do not refresh this view",
  );
});

test("a single-tab bundle renders exactly as before", async ({ page }) => {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  await page.goto(injectedBundleUrl(FIXTURE_MANIFEST));

  // No family -> the rail keeps the viewer's collapsed-by-default behaviour,
  // so it has to be opened by hand (a multi-tab bundle opens it on first run).
  await expect(page.locator(".react-grid-item")).toHaveCount(3);
  await page.getByLabel("Toggle tab sidebar").click();

  // `tabs: []` -> no pills, the same "No sibling tabs" rail as today.
  await expect(page.locator('[role="tab"]')).toHaveCount(0);
  await expect(page.getByText("No sibling tabs.")).toBeVisible();

  // The provenance block still renders what it can: producer + version are
  // top-level manifest fields, every provenance field of this fixture is null.
  const rail = page.locator(".mantine-AppShell-navbar");
  await expect(rail.getByText("Static export")).toBeVisible();
  await expect(rail.getByText("depictio 0.0.0-fixture")).toBeVisible();
  await expect(rail.getByText("Producer")).toBeVisible();
  // Every provenance field of this fixture is null, so none of their rows
  // exist — the block is the two top-level manifest facts and nothing else.
  for (const label of ["By", "On", "From", "Project", "Live copy"]) {
    await expect(rail.getByText(label, { exact: true })).toHaveCount(0);
  }

  expect(attempts).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});
