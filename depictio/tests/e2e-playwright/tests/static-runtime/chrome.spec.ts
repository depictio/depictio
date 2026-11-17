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
 *     drawer) opens the live project page, read-only and offline: the
 *     collections table, a collection's rows from the bundled table, its
 *     schema, the links map; a project link never navigates.
 *
 * All of it with zero network and no page error.
 */
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

import {
  FIXTURE_MANIFEST,
  PENGUINS_MANIFEST,
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

/** The tab fixture with a real table behind its `penguins` collection (the
 *  hand-written fixture's own blob is a placeholder), so the project page's
 *  data preview has rows to read. */
function tabsManifestWithTable(): string {
  const manifest = JSON.parse(readFileSync(TABS_MANIFEST, "utf-8"));
  const penguins = JSON.parse(readFileSync(PENGUINS_MANIFEST, "utf-8"));
  const ref = Object.values(penguins.data_refs as Record<string, { uri: string; rows: number }>).find(
    (r) => r.rows > 100,
  )!;
  const dcId = "dc00000000000000000000a1";
  manifest.data_refs[dcId] = { ...ref, uri: `inline:dc_${dcId}` };
  manifest.inline_blobs[`dc_${dcId}`] = penguins.inline_blobs[ref.uri.replace("inline:", "")];
  const out = join(mkdtempSync(join(tmpdir(), "depictio-projpage-")), "manifest.json");
  writeFileSync(out, JSON.stringify(manifest));
  return out;
}

test("the project page is the live one, offline", async ({ page }) => {
  const { url, side, attempts, pageErrors } = await openBundle(page, tabsManifestWithTable());
  // Every file the page asks for besides the bundle itself (a workflow logo
  // next to the file would be a broken image, or a leak on a static host).
  const fileRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().startsWith("file://") && !req.url().startsWith(url)) fileRequests.push(req.url());
  });

  await side.getByTestId("glass-project").click();
  const projectPage = page.getByTestId("bundle-project-page");
  await expect(projectPage).toBeVisible();
  await expect(projectPage.getByRole("heading", { level: 1 })).toHaveText("Fixture project");
  await expect(projectPage).toContainText(
    "A hand-written project around the penguin fixture table.",
  );
  await expect(projectPage.getByTestId("bundle-project-snapshot")).toContainText(
    "Static snapshot",
  );
  await expect(projectPage.getByRole("link", { name: /Live project/ })).toHaveAttribute(
    "href",
    "https://demo.depictio.example/projects/f1x7000000000000000000p1",
  );
  // The canvas underneath is hidden while the page is up; no tab is current.
  await expect(page.getByTestId("dashboard-content")).toBeHidden();
  await expect(side.locator(".hy-tablist-item[data-active]")).toHaveCount(0);
  await expect(side.getByTestId("glass-project")).toHaveAttribute("data-active", "true");

  // The live page's parts: its summary, its dashboards (this file's family),
  // its workflows. Nothing that needs a server is offered.
  await expect(projectPage.getByTestId("project-summary")).toContainText("Data collections");
  await expect(projectPage.getByTestId("project-dashboards")).toContainText("Fixture dashboard");
  await expect(projectPage.locator(".pd-workflows")).toContainText("nf-core/fixture");
  for (const absent of [
    "project-settings-button",
    "project-create-dashboard",
    "project-tab-activity",
    "project-tab-runs",
    "add-link-btn",
  ]) {
    await expect(projectPage.getByTestId(absent)).toHaveCount(0);
  }
  await expect(projectPage.getByRole("link", { name: "Permissions" })).toHaveCount(0);

  // Each collection says what the file holds of it.
  const penguinsRow = projectPage.locator('[data-testid="dc-row"]', { hasText: "penguins" });
  await expect(penguinsRow).toContainText("In this file");
  await expect(
    projectPage.locator('[data-testid="dc-row"]', { hasText: "multiqc_report" }),
  ).toContainText("Not included");

  // A collection opens on its rows, read from the bundled table.
  await penguinsRow.click();
  const viewer = projectPage.getByTestId("dc-viewer");
  await expect(viewer.getByRole("heading", { name: "penguins" })).toBeVisible();
  await expect(viewer.getByTestId("dc-fact-rows")).toContainText("3");
  const data = viewer.getByTestId("table-data-section");
  await expect(data).toContainText(/Showing \d+ of 342 rows/);
  await expect(data.locator(".ag-cell").first()).toBeVisible();
  // Its whole recorded schema, the columns the file does not carry included.
  await viewer.getByTestId("dc-section-columns").getByRole("button").first().click();
  await expect(viewer.getByTestId("dc-viewer-columns")).toContainText("island");
  await expect(viewer.getByTestId("dc-viewer-columns")).toContainText("Penguin species");

  // The links map: a node opens its connections, and the collection itself.
  await projectPage.getByTestId("links-section-toggle").click();
  const map = projectPage.getByTestId("connections-map");
  await expect(map).toBeVisible();
  await map.locator('.cm-node[title^="multiqc_report"]').click();
  await expect(projectPage.getByTestId("connections-detail")).toContainText("penguins");
  await projectPage.getByTestId("connections-open-dc").click();
  await expect(viewer.getByRole("heading", { name: "multiqc_report" })).toBeVisible();
  // Not in the file: said where its rows would be, never fetched.
  await expect(viewer.getByTestId("dc-not-in-bundle")).toContainText("Not included in this file");

  expect(fileRequests, `files requested next to the bundle:\n${fileRequests.join("\n")}`).toHaveLength(0);

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
