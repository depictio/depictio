/**
 * The navigation chrome of a bundle matches the live app's, and fills the gaps
 * a server leaves:
 *
 *   - the rail draws the family's `tab_group` sections and the main tab's own
 *     name, as the live tab list does;
 *   - the MultiQC logo shows offline, in the rail and in a text tile's tab link;
 *   - the sidebar's foot says what the file is (a static snapshot, its
 *     depictio, its export day; the card opens the whole provenance) where the
 *     live app says "Online", and leads to the project where it has "All
 *     dashboards";
 *   - every way the live app has to the project (the sidebar, the Settings
 *     drawer) opens a read-only project page drawn from the manifest, and a
 *     project link never navigates.
 *
 * All of it with zero network and no page error.
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

const MQC_TAB = "f1x70000000000000000face";

async function openBundle(page: Page, manifest = TABS_MANIFEST) {
  const attempts = await blockNetwork(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  const url = injectedBundleUrl(manifest);
  await page.goto(url);
  await expect(page.locator(".hy-shell[data-testid='app-shell']")).toBeVisible();
  await expect(page.getByText("A hand-written fixture manifest")).toBeVisible();
  // The fixture opens its Filters drawer, which folds the sidebar to its rail:
  // open it the way a reader would.
  const side = page.locator("nav.hy-side");
  if ((await page.locator(".hy-shell").getAttribute("data-side")) === "folded") {
    await page.getByTestId("glass-side-toggle").click();
  }
  await expect(page.locator(".hy-shell")).toHaveAttribute("data-side", "open");
  return { url, side, attempts, pageErrors };
}

/** An <img> that really decoded (not a broken-image glyph). */
async function expectDecoded(img: ReturnType<Page["locator"]>) {
  await expect(img).toBeVisible();
  await expect(img).toHaveAttribute("src", /^data:image\/svg/);
  await expect
    .poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);
}

test("the rail draws the live app's tab sections and names", async ({ page }) => {
  const { side, attempts, pageErrors } = await openBundle(page);

  // Sections, in the family's order, under the ungrouped main tab.
  await expect(side.locator(".hy-tablist-group")).toHaveText(["Analysis", "Quality"]);
  const sections = side.locator(".hy-tablist-section");
  await expect(sections.nth(0).locator(".hy-tablist-label")).toHaveText(["Overview"]);
  await expect(sections.nth(1).locator(".hy-tablist-label")).toHaveText([
    "Distributions",
    "Details",
  ]);
  await expect(sections.nth(2).locator(".hy-tablist-label")).toHaveText(["MultiQC"]);

  // Folded, a rule between groups and the group in each tooltip's eyebrow.
  await page.getByTestId("glass-side-toggle").click();
  await expect(side.locator(".hy-rail-tabs .hy-sep")).toHaveCount(2);

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("the MultiQC logo shows offline, in the rail and in tab links", async ({ page }) => {
  const { side, attempts } = await openBundle(page);

  await expectDecoded(side.locator(`a.hy-tablist-item[href$="${MQC_TAB}"] img`));
  // The main tab's text links to the MultiQC tab by name: the link wears the
  // tab's own logo, as on the live overview.
  await expectDecoded(
    page.locator(`.react-grid-item a[href$="${MQC_TAB}"] img`).first(),
  );

  // Dark: the white variant, still inlined.
  await page.getByTestId("theme-toggle").first().click();
  await expectDecoded(side.locator(`a.hy-tablist-item[href$="${MQC_TAB}"] img`));

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
});

test("the sidebar foot is a static snapshot's, not a server's", async ({ page }) => {
  const { side, attempts } = await openBundle(page);
  const foot = side.locator(".hy-side-foot");

  // No server card, no dashboards list: a file has neither.
  await expect(page.getByTestId("hy-status")).toHaveCount(0);
  await expect(foot.getByText("Online")).toHaveCount(0);
  await expect(foot.getByText("All dashboards")).toHaveCount(0);

  // The snapshot card: what the file is and its export day, on one line like
  // the live server card; its depictio is named for assistive tech and in the
  // details it opens.
  const card = foot.getByTestId("hy-snapshot-card");
  await expect(card).toContainText("Static snapshot");
  await expect(card).toContainText("2026-08-03");
  await expect(foot.getByTestId("hy-snapshot")).toHaveAttribute(
    "aria-label",
    /exported 2026-08-03, depictio v0\.0\.0-fixture/,
  );

  // It opens the whole provenance, the live copy link included.
  await foot.getByTestId("hy-snapshot").click();
  const details = page.getByTestId("static-snapshot-details");
  await expect(details).toBeVisible();
  await expect(details).toContainText("curator@example.org");
  await expect(details).toContainText("2026-08-03 09:15 UTC");
  await expect(details).toContainText("https://demo.depictio.example");
  await expect(details.getByRole("link", { name: /live dashboard/ })).toHaveAttribute(
    "href",
    /^https:\/\/demo\.depictio\.example\/dashboard\//,
  );
  await page.keyboard.press("Escape");

  // The project row, where the live foot has "All dashboards".
  await expect(foot.getByTestId("glass-project")).toContainText("Fixture project");

  // As tall as the live foot (a one-line server card and one 44px row), so
  // the tab list above gets the same room: a taller foot made the rail scroll
  // and hid a tab the live app shows.
  const cardBox = await card.boundingBox();
  const rowBox = await foot.getByTestId("glass-project").boundingBox();
  expect(cardBox?.height).toBeLessThanOrEqual(56);
  expect(rowBox?.height).toBeLessThanOrEqual(44);

  // Folded: icons only, named for assistive tech, nothing cut in half.
  await page.getByTestId("glass-side-toggle").click();
  await expect(foot.getByTestId("hy-snapshot").locator(".hy-status-text")).toBeHidden();
  await expect(foot.getByRole("button", { name: "Project: Fixture project" })).toBeVisible();
  const box = await foot.getByTestId("glass-project").boundingBox();
  expect(box?.width).toBeLessThanOrEqual(48);

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
});

test("the project page opens from the sidebar and the Settings drawer", async ({ page }) => {
  const { url, side, attempts, pageErrors } = await openBundle(page);

  await side.getByTestId("glass-project").click();
  const projectPage = page.getByTestId("bundle-project-page");
  await expect(projectPage).toBeVisible();
  await expect(projectPage.getByRole("heading", { level: 1 })).toHaveText("Fixture project");
  await expect(projectPage).toContainText(
    "A hand-written project around the penguin fixture table.",
  );
  // The canvas underneath is hidden while the page is up; no tab is current.
  await expect(page.getByTestId("dashboard-content")).toBeHidden();
  await expect(side.locator(".hy-tablist-item[data-active]")).toHaveCount(0);
  await expect(side.getByTestId("glass-project")).toHaveAttribute("data-active", "true");

  // What the file carries of each collection.
  const collections = projectPage.getByTestId("bundle-project-collections");
  const penguins = collections.locator("tr", { hasText: "penguins" });
  await expect(penguins).toContainText("In this file");
  // Whole, not "In this…": the column is as wide as its badge.
  const presence = penguins.locator(".mantine-Badge-label", { hasText: "In this file" });
  expect(await presence.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expect(penguins).toContainText("3 rows · 2 columns");
  await expect(collections.locator("tr", { hasText: "multiqc_report" })).toContainText(
    "Not included",
  );
  // The MultiQC type icon is the inlined logo too.
  await expectDecoded(collections.locator('tr:has-text("multiqc_report") img').first());

  await expect(projectPage.getByTestId("bundle-project-workflows")).toContainText(
    "fixture-pipeline",
  );
  await expect(projectPage.getByTestId("bundle-project-workflows")).toContainText(
    "Nextflow 24.10.0",
  );
  await expect(projectPage.getByTestId("bundle-project-links")).toContainText("penguins");
  await expect(projectPage.getByTestId("bundle-project-params")).toContainText("island");
  await expect(projectPage.getByTestId("bundle-project-export")).toContainText(
    "curator@example.org",
  );
  await expect(projectPage.getByRole("link", { name: /Live project/ })).toHaveAttribute(
    "href",
    "https://demo.depictio.example/projects/f1x7000000000000000000p1",
  );

  // Back to the tab it was opened over.
  await projectPage.getByTestId("bundle-project-close").click();
  await expect(projectPage).toHaveCount(0);
  await expect(page.getByText("A hand-written fixture manifest")).toBeVisible();

  // The Settings drawer's project link: the bundle's page, not a dead route.
  await page.locator('[data-hy-slot="settings"] button').click();
  const settings = page.getByTestId("settings-modal");
  await expect(settings.locator(".mantine-Modal-content")).toBeVisible();
  const projectLink = settings.getByRole("link", { name: "Fixture project" });
  await expect(projectLink).toBeVisible();
  // No ingestion report in a file: those links are left out.
  await expect(settings.getByText("View ingestion report")).toHaveCount(0);
  await projectLink.click();
  await expect(projectPage).toBeVisible();
  await expect(settings.locator(".mantine-Modal-content")).toBeHidden();
  expect(page.url()).toBe(url);

  // Esc returns too; a tab click closes the page and switches tab.
  await page.keyboard.press("Escape");
  await expect(projectPage).toHaveCount(0);
  await side.getByTestId("glass-project").click();
  await expect(projectPage).toBeVisible();
  await side.locator(`a.hy-tablist-item[href$="f1x70000000000000000cafe"]`).click();
  await expect(projectPage).toHaveCount(0);
  await expect(page.getByText("Second tab body.")).toBeVisible();
  expect(page.url()).toBe(url);

  expect(attempts, `unexpected network attempts:\n${attempts.join("\n")}`).toHaveLength(0);
  expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
});

test("a bundle without a project offers no project page", async ({ page }) => {
  const attempts = await blockNetwork(page);
  await page.goto(injectedBundleUrl(FIXTURE_MANIFEST));
  await expect(page.getByText("A hand-written fixture manifest")).toBeVisible();
  await expect(page.getByTestId("glass-project")).toHaveCount(0);
  await expect(page.getByTestId("hy-snapshot-card")).toBeVisible();
  expect(attempts).toHaveLength(0);
});
