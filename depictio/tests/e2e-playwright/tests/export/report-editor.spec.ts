/**
 * The report editor (/dashboard-report/{id}): reached from Settings > Export,
 * with the dashboard's components live in the structure column and the
 * rendered Quarto report beside them.
 *
 * Runs against the seeded Iris dashboard. The whole describe skips when the
 * server answers features.report_editor: false on /utils/server-info, because
 * the editor is an opt-in feature and its routes 404 while it is off.
 *
 * The preview is an iframe around a Quarto render. On a cold server the first
 * render can take minutes, so the tests that reach it take a long timeout and
 * poll instead of waiting a fixed time.
 */

import type { APIRequestContext, FrameLocator, Locator, Page } from "@playwright/test";

import { API_PREFIX, API_URL, apiOnlyToken, expect, test } from "@fixtures/auth";
import { IRIS_DASHBOARD_ID } from "@fixtures/projects";

const FRAME = "[data-testid='report-preview-frame']";
/** A tile block the patch has not hidden: an unticked tile leaves the report. */
const VISIBLE_TILES = "[data-depictio-tile]:visible";
/** The seeded Iris report opens with every tile in the report, so the first
 *  toggle candidate is also the first card in practice. */
/** The cards of a card row in the preview, in either of its two forms: the
 *  rendered fallback's slots, or the live cards the runtime mounts once the
 *  row scrolls into view (the fallback is then hidden). */
const CARDS = ".dpx-cards > .dpx-card-slot, .depictio-report-row > *";
const FULL_TILES = "[data-testid='report-structure'] .rpt-tile:not(.rpt-tile--half)";

/** The editor page, opened directly. */
async function openEditor(page: Page): Promise<void> {
  await page.goto(`/dashboard-report/${IRIS_DASHBOARD_ID}`);
  await expect(page.locator("[data-testid='report-editor']")).toBeVisible({ timeout: 30_000 });
}

/** The preview frame once it is live: rendered, and taking the patch channel
 *  ("Live" in the status chip), so edits reach it. The first render is the
 *  slow one; a warm server answers in seconds. */
async function livePreview(page: Page): Promise<FrameLocator> {
  await expect(page.locator(FRAME)).toBeAttached({ timeout: 300_000 });
  const frame = page.frameLocator(FRAME);
  await expect(frame.locator(VISIBLE_TILES).first()).toBeVisible({ timeout: 120_000 });
  await expect(page.locator("[data-testid='report-preview-status']")).toContainText("Live", {
    timeout: 60_000,
  });
  return frame;
}

/** True once the stored layer has `key` (`tab:component`) back in the
 *  report: the page saves 800 ms after an edit, and closing it earlier would
 *  abandon the save. */
async function storedInReport(
  request: APIRequestContext,
  token: string,
  key: string,
): Promise<boolean> {
  const at = key.indexOf(":");
  const tabId = key.slice(0, at);
  const componentId = key.slice(at + 1);
  const res = await request.get(
    `${API_URL}${API_PREFIX}/dashboards/report_layer/${IRIS_DASHBOARD_ID}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!res.ok()) return false;
  const layer = (await res.json()) as {
    tiles?: { tab_id: string; component_id: string; in_report: boolean }[];
  };
  return !(layer.tiles ?? []).some(
    (t) => t.tab_id === tabId && t.component_id === componentId && !t.in_report,
  );
}

test.describe("Report editor", () => {
  test.beforeEach(async ({ request }) => {
    const res = await request.get(`${API_URL}${API_PREFIX}/utils/server-info`);
    const features = res.ok()
      ? ((await res.json()) as { features?: { report_editor?: boolean } }).features
      : undefined;
    test.skip(
      features?.report_editor !== true,
      "features.report_editor is off: the report editor is not offered by this server.",
    );
  });

  test("opens from Settings > Export and shows live tiles and the preview", async ({
    loginAsAdmin,
    page,
  }) => {
    test.setTimeout(360_000);
    await loginAsAdmin();
    await page.goto(`/dashboard-edit/${IRIS_DASHBOARD_ID}?no-walkthrough=1`);

    // `exact`: every tile carries its own "… settings" button.
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await page.locator("[data-testid='settings-nav-export']").click();
    const customise = page.locator("[data-testid='export-customise-report']");
    await expect(customise).toBeVisible({ timeout: 15_000 });
    await customise.click();

    await expect(page).toHaveURL(new RegExp(`/dashboard-report/${IRIS_DASHBOARD_ID}$`));
    await expect(page.locator("[data-testid='report-editor']")).toBeVisible({ timeout: 30_000 });

    // The structure column mirrors the dashboard: one tile card per
    // component, each with its live render.
    await expect(page.locator("[data-tile-key]")).not.toHaveCount(0);
    await expect(page.locator("[data-testid^='report-live-']")).not.toHaveCount(0);

    // Each tile leads back to its component: shown in the dashboard, or
    // opened in the dashboard editor.
    const card = page.locator("[data-tile-key]").first();
    const [tabId, componentId] = ((await card.getAttribute("data-tile-key")) ?? "").split(":");
    await expect(card.locator("[data-testid='report-tile-open']")).toHaveAttribute(
      "href",
      `/dashboard/${tabId}?focus=${encodeURIComponent(componentId)}`,
    );
    await expect(card.locator("[data-testid='report-tile-edit']")).toHaveAttribute(
      "href",
      `/dashboard-edit/${tabId}/component/edit/${encodeURIComponent(componentId)}`,
    );

    // The preview is the rendered report, tiles and all.
    const frame = await livePreview(page);
    await expect(frame.locator(VISIBLE_TILES)).not.toHaveCount(0);
  });

  test("unticking a tile removes it from the preview, ticking puts it back", async ({
    loginAsAdmin,
    page,
    request,
  }) => {
    test.setTimeout(360_000);
    await loginAsAdmin();
    await openEditor(page);
    const frame = await livePreview(page);
    const tiles = frame.locator(VISIBLE_TILES);

    // A tile to toggle: ticked (so it is in the report and rendered) and not
    // one of the half-width cards, whose row can share one placeholder in
    // the preview with its neighbours.
    let tile: Locator | null = null;
    let key = "";
    for (const card of await page.locator(FULL_TILES).all()) {
      const toggle = card.locator("[data-testid='report-include-toggle']");
      if (!(await toggle.isChecked())) continue;
      const cardKey = await card.getAttribute("data-tile-key");
      if (!cardKey) continue;
      if (!(await frame.locator(`[data-depictio-tile~="${cardKey}"]`).first().isVisible())) {
        continue;
      }
      tile = card;
      key = cardKey;
      break;
    }
    expect(tile, "no tile in the report with a visible preview tile").not.toBeNull();

    const { access_token } = await apiOnlyToken(request, "adminUser");

    const toggle = tile!.locator("[data-testid='report-include-toggle']");
    const before = await tiles.count();
    try {
      await toggle.click();
      // The autosave lands (an 800 ms debounce), then the patch hides the
      // tile's block in the frame.
      await expect(page.locator("[data-testid='report-save-status']")).toContainText("Saved", {
        timeout: 30_000,
      });
      await expect(tiles).toHaveCount(before - 1, { timeout: 30_000 });
      await expect(tile!.getByText("Not in the report")).toBeVisible();
    } finally {
      // Put the tile back, then wait for the layer to say it is stored:
      // the page must not close on a pending save.
      if (tile && !(await toggle.isChecked())) {
        await toggle.click();
      }
      await expect(tiles).toHaveCount(before, { timeout: 30_000 });
      await expect
        .poll(() => storedInReport(request, access_token, key), { timeout: 30_000 })
        .toBe(true);
    }
  });

  test("unticking one card of a card row hides that card alone", async ({
    loginAsAdmin,
    page,
    request,
  }) => {
    test.setTimeout(360_000);
    await loginAsAdmin();
    await openEditor(page);
    const frame = await livePreview(page);

    // A ticked half-width card whose preview tile is a row of several cards:
    // the row is one block in the report, each card one slot in it.
    let card: Locator | null = null;
    let key = "";
    for (const candidate of await page
      .locator("[data-testid='report-structure'] .rpt-tile--half")
      .all()) {
      const toggle = candidate.locator("[data-testid='report-include-toggle']");
      if (!(await toggle.isChecked())) continue;
      const cardKey = await candidate.getAttribute("data-tile-key");
      if (!cardKey) continue;
      const row = frame.locator(`[data-depictio-tile~="${cardKey}"]`).first();
      if (!(await row.isVisible())) continue;
      if ((await row.locator(CARDS).count()) < 2) continue;
      card = candidate;
      key = cardKey;
      break;
    }
    expect(card, "no ticked card in a visible card row").not.toBeNull();

    const row = frame.locator(`[data-depictio-tile~="${key}"]`).first();
    const slots = row.locator(CARDS).filter({ visible: true });
    const before = await slots.count();
    const { access_token } = await apiOnlyToken(request, "adminUser");
    const toggle = card!.locator("[data-testid='report-include-toggle']");
    try {
      await toggle.click();
      // The card leaves the row; the row and its other cards stay.
      await expect(slots).toHaveCount(before - 1, { timeout: 30_000 });
      await expect(row).toBeVisible();
    } finally {
      if (card && !(await toggle.isChecked())) {
        await toggle.click();
      }
      await expect(slots).toHaveCount(before, { timeout: 30_000 });
      await expect
        .poll(() => storedInReport(request, access_token, key), { timeout: 30_000 })
        .toBe(true);
    }
  });

  test("a section's box takes the whole section out of the preview and back", async ({
    loginAsAdmin,
    page,
    request,
  }) => {
    test.setTimeout(360_000);
    await loginAsAdmin();
    await openEditor(page);
    const frame = await livePreview(page);

    // The structure groups the tiles under their dashboard sections.
    const headings = page.locator("[data-testid='report-section-heading']");
    await expect(headings).not.toHaveCount(0);
    const toggle = page.locator(
      `[data-testid='report-section-toggle-${IRIS_DASHBOARD_ID}:Distributions']`,
    );
    await expect(toggle).toBeChecked();
    const section = frame.locator('[data-depictio-section$=":Distributions"]');
    await expect(section).toBeVisible();

    const { access_token } = await apiOnlyToken(request, "adminUser");
    /** How many tiles the stored layer keeps out of the report. */
    const excluded = async (): Promise<number> => {
      const res = await request.get(
        `${API_URL}${API_PREFIX}/dashboards/report_layer/${IRIS_DASHBOARD_ID}`,
        { headers: { Authorization: `Bearer ${access_token}` } },
      );
      if (!res.ok()) return -1;
      const layer = (await res.json()) as { tiles?: { in_report: boolean }[] };
      return (layer.tiles ?? []).filter((t) => !t.in_report).length;
    };
    const before = await excluded();
    try {
      await toggle.click();
      // The section goes, heading and all, as it does from the export.
      await expect(section).toBeHidden({ timeout: 30_000 });
    } finally {
      if (!(await toggle.isChecked())) await toggle.click();
      await expect(section).toBeVisible({ timeout: 30_000 });
      await expect.poll(excluded, { timeout: 30_000 }).toBe(before);
    }
  });

  test("the splitter resizes the panes", async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    await openEditor(page);
    const splitter = page.locator("[data-testid='report-splitter']");
    const preview = page.locator("[data-testid='report-preview-pane']");
    await expect(splitter).toBeVisible();

    // Drag the handle 200 px to the left: the structure column narrows and
    // the preview grows by about that.
    const before = (await preview.boundingBox())!;
    const box = (await splitter.boundingBox())!;
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx - 200, cy, { steps: 5 });
    await page.mouse.up();
    const dragged = (await preview.boundingBox())!;
    expect(dragged.width).toBeGreaterThan(before.width + 150);

    // The keyboard pins the structure column to its minimum (28 %).
    await splitter.click();
    await page.keyboard.press("Home");
    await expect(splitter).toHaveAttribute("aria-valuenow", "28");

    // A double-click resets the split to about half and half.
    await splitter.dblclick();
    await expect(splitter).toHaveAttribute("aria-valuenow", "50");
    const editBox = (await page.locator("[data-testid='report-edit-column']").boundingBox())!;
    const previewBox = (await preview.boundingBox())!;
    const previewShare = previewBox.width / (previewBox.width + editBox.width);
    expect(previewShare).toBeGreaterThan(0.45);
    expect(previewShare).toBeLessThan(0.55);
  });

  test("the scroll sync toggle flips", async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    await openEditor(page);
    const sync = page.locator("[data-testid='report-scroll-sync']");
    await expect(sync).toBeVisible();
    // On by default: the column and the preview scroll together.
    await expect(sync).toHaveAttribute("aria-pressed", "true");
    await sync.click();
    await expect(sync).toHaveAttribute("aria-pressed", "false");
    // Back where it started.
    await sync.click();
    await expect(sync).toHaveAttribute("aria-pressed", "true");
  });

  test("report settings are saved with the layer", async ({ loginAsAdmin, page, request }) => {
    await loginAsAdmin();
    const { access_token: token } = await apiOnlyToken(request, "adminUser");
    await openEditor(page);
    await page.locator("[data-testid='report-settings-open']").click();
    const modal = page.locator("[data-testid='report-settings']");
    const toc = modal.locator("[data-testid='report-setting-toc']");
    // Mantine draws the switch over a hidden input: the label takes the click.
    const tocLabel = modal.getByText("Table of contents", { exact: true });
    await expect(toc).toBeChecked();
    await tocLabel.click();

    const stored = async (): Promise<boolean | undefined> => {
      const res = await request.get(
        `${API_URL}${API_PREFIX}/dashboards/report_layer/${IRIS_DASHBOARD_ID}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!res.ok()) return undefined;
      return ((await res.json()) as { settings?: { toc?: boolean } }).settings?.toc;
    };
    await expect.poll(stored, { timeout: 15_000 }).toBe(false);

    // Back where it started, so the other tests see the default report.
    await tocLabel.click();
    await expect.poll(stored, { timeout: 15_000 }).toBe(true);
  });
});
