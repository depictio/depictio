/**
 * Dashboard version history (editor Settings > History / Data version).
 *
 * Every save of a dashboard captures a version. The editor's Settings modal
 * lists them (History) and offers a data time-travel picker (Data version);
 * `/dashboard/{id}?version={vid}` renders one read-only behind a banner.
 *
 * The spec works on a dashboard it creates itself (and deletes at the end), not
 * on a seeded one: it bookmarks, edits and restores, and a seeded dashboard is
 * shared with every other spec running in parallel.
 *
 * The content change between the bookmark and the restore is a tab rename sent
 * to the API (`PATCH /dashboards/tab/{id}`), then a reload of the editor. The
 * header breadcrumb is built from the tab list, which a restore does not
 * refetch, so the restored title is asserted on the stored document (the source
 * of truth) rather than on the header.
 *
 * Does not depend on Delta history existing for the data: the Data version
 * section is asserted to render, and its picker only to be coherent.
 */

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { test, expect, apiOnlyToken, API_URL, API_PREFIX } from "@fixtures/auth";
import { DASHBOARDS_GRID_URL, createDashboard } from "@fixtures/dashboard";

interface DashboardEntry {
  dashboard_id: string;
  title?: string;
}

interface VersionSummary {
  version_id: string;
  seq: number;
  kind: string;
  label: string | null;
  pinned: boolean;
  save_count?: number;
}

interface VersionList {
  total: number;
  current_version_id: string | null;
  versions: VersionSummary[];
}

async function authHeaders(request: APIRequestContext): Promise<Record<string, string>> {
  const { access_token } = await apiOnlyToken(request, "adminUser");
  return { Authorization: `Bearer ${access_token}` };
}

/** Id of the dashboard just created through the UI, found by its unique title. */
async function findDashboardId(request: APIRequestContext, title: string): Promise<string> {
  const headers = await authHeaders(request);
  let id: string | null = null;
  await expect
    .poll(
      async () => {
        const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/list`, { headers });
        if (!res.ok()) return null;
        const body = (await res.json()) as { dashboards?: DashboardEntry[] } | DashboardEntry[];
        const entries = Array.isArray(body) ? body : (body.dashboards ?? []);
        id = entries.find((d) => d.title === title)?.dashboard_id ?? null;
        return id;
      },
      { timeout: 15_000, message: `the dashboard "${title}" should be listed` },
    )
    .not.toBeNull();
  return id!;
}

async function listVersions(request: APIRequestContext, id: string): Promise<VersionList> {
  const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/${id}/versions?limit=200`, {
    headers: await authHeaders(request),
  });
  expect(res.ok(), "listing versions should succeed").toBe(true);
  return (await res.json()) as VersionList;
}

async function nameCurrentState(
  request: APIRequestContext,
  id: string,
  label: string,
): Promise<{ version_id: string; seq: number }> {
  const res = await request.post(`${API_URL}${API_PREFIX}/dashboards/${id}/versions`, {
    headers: await authHeaders(request),
    data: { label },
  });
  expect(res.ok(), "naming the current state should succeed").toBe(true);
  return (await res.json()) as { version_id: string; seq: number };
}

async function renameTab(request: APIRequestContext, id: string, title: string): Promise<void> {
  const res = await request.patch(`${API_URL}${API_PREFIX}/dashboards/tab/${id}`, {
    headers: await authHeaders(request),
    data: { title },
  });
  expect(res.ok(), "renaming the tab should succeed").toBe(true);
}

async function storedTitle(request: APIRequestContext, id: string): Promise<string | null> {
  const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/get/${id}`, {
    headers: await authHeaders(request),
  });
  if (!res.ok()) return null;
  return ((await res.json()) as { title?: string }).title ?? null;
}

async function deleteDashboardViaApi(request: APIRequestContext, id: string): Promise<void> {
  await request.delete(`${API_URL}${API_PREFIX}/dashboards/delete/${id}`, {
    headers: await authHeaders(request),
  });
}

/** Opens the editor's Settings modal. Works at both widths: the labelled
 *  button shows from `sm` up and the gear icon below it, and the hidden one is
 *  not in the accessibility tree. */
async function openSettings(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByTestId("settings-modal")).toBeVisible();
}

async function openHistory(page: Page): Promise<void> {
  await openSettings(page);
  await page.getByTestId("settings-nav-history").click();
  await expect(page.getByTestId("version-history-panel")).toBeVisible();
}

/** Opens a version row's "more" menu and returns it. Preview, Bookmark and
 *  Delete live there; the menu is portaled to <body>, so its items are found
 *  on the page rather than inside the row. */
async function openRowMenu(page: Page, row: Locator): Promise<Locator> {
  await row.getByTestId("version-actions").click();
  const menu = page.getByTestId("version-actions-menu");
  await expect(menu).toBeVisible();
  return menu;
}

async function closeSettings(page: Page): Promise<void> {
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("settings-modal")).toBeHidden();
}

/** Opens `/dashboard-edit/{id}` and waits for the header's Settings button. */
async function openEditor(page: Page, id: string): Promise<void> {
  await page.goto(`/dashboard-edit/${id}`);
  await expect(page.getByRole("button", { name: "Settings", exact: true })).toBeVisible({
    timeout: 30_000,
  });
}

/** Creates a dashboard through the listing and returns its title and id. */
async function createOwnDashboard(
  page: Page,
  request: APIRequestContext,
  prefix: string,
): Promise<{ title: string; id: string }> {
  await page.goto(DASHBOARDS_GRID_URL);
  const title = `${prefix} ${new Date().toISOString().replace(/:/g, "-")}`;
  await createDashboard(page, title);
  return { title, id: await findDashboardId(request, title) };
}

test.describe("Dashboard version history", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "Dashboard creation requires an authenticated user.",
  );

  test("bookmark, edit, restore, undo, preview and data version", async ({
    page,
    context,
    request,
    loginAsAdmin,
  }) => {
    // Two editor loads, a handful of API round trips and a preview tab.
    test.setTimeout(180_000);
    await loginAsAdmin();
    const { title: originalTitle, id } = await createOwnDashboard(page, request, "E2E Versions");

    try {
      const rows = page.getByTestId("version-row");
      const bookmarkLabel = `e2e bookmark ${Date.now()}`;
      const changedTitle = `${originalTitle} (changed)`;
      const changedLabel = `e2e changed ${Date.now()}`;

      await test.step("open Settings > History and read the newest row", async () => {
        await openEditor(page, id);
        await openHistory(page);
        // A fresh dashboard may have no version yet: only record the newest
        // seq when there is one.
        const empty = await rows.count();
        const newestSeq = empty > 0 ? Number(await rows.first().getAttribute("data-version-seq")) : 0;
        expect(Number.isFinite(newestSeq)).toBe(true);
        await test.info().attach("newest-seq-before-bookmark", { body: String(newestSeq) });
      });

      await test.step("bookmark the current state", async () => {
        await page.getByTestId("version-snapshot").click();
        await expect(page.getByTestId("version-bookmark-dialog")).toBeVisible();
        // Empty names are refused: Bookmark stays disabled until one is typed.
        await expect(page.getByTestId("version-bookmark-confirm")).toBeDisabled();
        await page.getByTestId("version-bookmark-label").fill(bookmarkLabel);
        await page.getByTestId("version-bookmark-confirm").click();
        await expect(page.getByTestId("version-bookmark-dialog")).toBeHidden();

        // Naming the current state writes a new explicit version, or names the
        // newest one when nothing changed: either way the top row carries it.
        const top = rows.first();
        await expect(top).toContainText(bookmarkLabel);
        await expect(top).toContainText("Bookmarked");
        await expect(top).toHaveAttribute("data-version-kind", "explicit");

        // The kind is spelled out in the row's details, folded by default.
        // Asserted on `aria-expanded`: a closed Collapse is zero height, not
        // display:none, so its content would still count as visible.
        const details = top.getByTestId("version-details-toggle");
        await expect(details).toHaveAttribute("aria-expanded", "false");
        await details.click();
        await expect(details).toHaveAttribute("aria-expanded", "true");
        await expect(top.getByTestId("version-kind")).toContainText("Saved");
        await details.click();
        await expect(details).toHaveAttribute("aria-expanded", "false");
      });

      await closeSettings(page);

      await test.step("edit the dashboard and capture the change", async () => {
        await renameTab(request, id, changedTitle);
        await nameCurrentState(request, id, changedLabel);
        await openEditor(page, id);
        await openHistory(page);
        const changed = rows.filter({ hasText: changedLabel });
        await expect(changed).toHaveCount(1);
        const changedSeq = Number(await changed.getAttribute("data-version-seq"));
        const bookmarkSeq = Number(
          await rows.filter({ hasText: bookmarkLabel }).getAttribute("data-version-seq"),
        );
        expect(changedSeq).toBeGreaterThan(bookmarkSeq);
        expect(await storedTitle(request, id)).toBe(changedTitle);
      });

      await test.step("restore the bookmark without a page reload", async () => {
        // A marker on `window` survives an in-app refetch and dies with a
        // navigation or a reload.
        await page.evaluate(() => {
          (window as unknown as { __e2eNoReload: number }).__e2eNoReload = 1;
        });

        const bookmarked = rows.filter({ hasText: bookmarkLabel });
        await bookmarked.getByTestId("version-restore").click();
        await expect(page.getByTestId("version-restore-dialog")).toBeVisible();

        const restored = page.waitForResponse(
          (res) =>
            res.request().method() === "POST" &&
            /\/dashboards\/versions\/[^/]+\/restore$/.test(new URL(res.url()).pathname) &&
            res.ok(),
        );
        await page.getByTestId("version-restore-confirm").click();
        await restored;
        await expect(page.getByTestId("version-restore-dialog")).toBeHidden();

        // A restore row heads the history, and the state it replaced is still
        // listed (the changed version, now one step down).
        await expect(rows.first()).toHaveAttribute("data-version-kind", "restore");
        await expect(rows.filter({ hasText: changedLabel })).toHaveCount(1);

        expect(await storedTitle(request, id)).toBe(originalTitle);
        const marker = await page.evaluate(
          () => (window as unknown as { __e2eNoReload?: number }).__e2eNoReload,
        );
        expect(marker, "restoring must not reload the page").toBe(1);
        expect(new URL(page.url()).pathname).toBe(`/dashboard-edit/${id}`);
      });

      await test.step("undo by restoring the version the restore replaced", async () => {
        const changed = rows.filter({ hasText: changedLabel });
        // Restore is unavailable on the current row only, and the current row
        // is now the restore, not this one.
        await expect(changed.getByTestId("version-restore")).not.toHaveAttribute(
          "aria-disabled",
          "true",
        );
        await changed.getByTestId("version-restore").click();
        await expect(page.getByTestId("version-restore-dialog")).toBeVisible();
        await page.getByTestId("version-restore-confirm").click();
        await expect(page.getByTestId("version-restore-dialog")).toBeHidden();
        await expect(rows.first()).toHaveAttribute("data-version-kind", "restore");

        await expect
          .poll(() => storedTitle(request, id), { message: "the change should be back" })
          .toBe(changedTitle);
        const marker = await page.evaluate(
          () => (window as unknown as { __e2eNoReload?: number }).__e2eNoReload,
        );
        expect(marker, "the undo must not reload the page either").toBe(1);
      });

      await test.step("preview an older version read-only in the viewer", async () => {
        const before = (await listVersions(request, id)).total;
        const older = rows.filter({ hasText: bookmarkLabel });
        const menu = await openRowMenu(page, older);
        const popup = context.waitForEvent("page");
        await menu.getByTestId("version-preview").click();
        const preview = await popup;

        await expect(preview).toHaveURL(new RegExp(`/dashboard/${id}\\?version=`), {
          timeout: 30_000,
        });
        await expect(preview.getByTestId("version-banner")).toBeVisible({ timeout: 30_000 });
        // No editing affordances in a past version.
        await expect(preview.getByTestId("add-component")).toHaveCount(0);
        await expect(preview.getByTestId("add-section")).toHaveCount(0);
        await expect(preview.locator("[data-tour-id='editor-save']")).toHaveCount(0);
        // The banner is the way out, and the version param stays in the URL.
        await expect(preview.getByTestId("version-banner-exit")).toBeVisible();
        expect(new URL(preview.url()).searchParams.get("version")).toBeTruthy();
        await preview.close();

        // Selecting a version for preview must never write anything.
        expect((await listVersions(request, id)).total).toBe(before);
      });

      await test.step("the Data version section renders", async () => {
        await page.getByTestId("settings-nav-data-version").click();
        await expect(page.getByTestId("settings-section-data-version")).toBeVisible();
        await expect(page.getByTestId("data-version-panel")).toBeVisible();
        await expect(page.getByTestId("data-version-status")).toContainText(
          "Showing current data",
        );
        // Whether any version recorded a data version depends on the stack's
        // Delta history, so only check the picker is coherent either way.
        const select = page.getByTestId("data-version-select");
        await expect(select).toBeVisible();
        if (await select.isDisabled()) {
          await expect(select).toHaveAttribute("placeholder", "No version recorded its data");
          await expect(page.getByTestId("data-version-use")).toBeDisabled();
        } else {
          // Nothing is picked yet, so there is nothing to apply.
          await expect(page.getByTestId("data-version-use")).toBeDisabled();
        }
        // Not time-travelling, so there is no way back to offer.
        await expect(page.getByTestId("data-version-clear")).toHaveCount(0);
      });

      await test.step("delete a version the test created", async () => {
        await page.getByTestId("settings-nav-history").click();
        const target = rows.filter({ hasText: changedLabel });
        const count = await rows.count();
        const menu = await openRowMenu(page, target);
        await menu.getByTestId("version-delete").click();
        await expect(page.getByTestId("version-delete-dialog")).toBeVisible();
        await page.getByTestId("version-delete-confirm").click();
        await expect(page.getByTestId("version-delete-dialog")).toBeHidden();
        await expect(rows).toHaveCount(count - 1);
        await expect(rows.filter({ hasText: changedLabel })).toHaveCount(0);
      });
    } finally {
      // The dashboard goes with its whole version ledger.
      await deleteDashboardViaApi(request, id);
    }
  });

  test("opening the editor records no version", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    await loginAsAdmin();
    const { id } = await createOwnDashboard(page, request, "E2E Versions Open");

    try {
      // Two text tiles stacked on one cell, keyed `box-<index>` the way an import
      // writes them. react-grid-layout compacts that as soon as it mounts, and
      // the editor used to save what it reported: one version per open.
      const headers = await authHeaders(request);
      const getRes = await request.get(`${API_URL}${API_PREFIX}/dashboards/get/${id}`, {
        headers,
      });
      expect(getRes.ok(), "reading the dashboard should succeed").toBe(true);
      const doc = (await getRes.json()) as Record<string, unknown>;
      const tiles = [crypto.randomUUID(), crypto.randomUUID()];
      doc.stored_metadata = tiles.map((index, n) => ({
        index,
        component_type: "text",
        title: `Stacked tile ${n + 1}`,
        body: "Placed on the same cell as its neighbour.",
      }));
      doc.right_panel_layout_data = tiles.map((index) => ({
        i: `box-${index}`,
        x: 0,
        y: 0,
        w: 6,
        h: 2,
      }));
      doc.notes_content = "";
      const saveRes = await request.post(`${API_URL}${API_PREFIX}/dashboards/save/${id}`, {
        headers,
        data: doc,
      });
      expect(saveRes.ok(), "storing the stacked layout should succeed").toBe(true);

      const shape = (list: VersionList) =>
        list.versions.map((v) => ({ seq: v.seq, kind: v.kind, saves: v.save_count }));
      const before = shape(await listVersions(request, id));

      await openEditor(page, id);
      await expect(page.locator(".react-grid-item")).toHaveCount(2);
      // Past the 500 ms layout debounce and the notes editor's 1 s one.
      await page.waitForTimeout(3_000);

      expect(
        shape(await listVersions(request, id)),
        "opening the editor must neither add a version nor save into one",
      ).toEqual(before);
    } finally {
      await deleteDashboardViaApi(request, id);
    }
  });

  test("mobile: the History section is reachable from the nav select", async ({
    page,
    request,
    loginAsAdmin,
  }) => {
    test.setTimeout(120_000);
    await loginAsAdmin();
    // Created at the desktop width: the creation modal is not what is tested.
    const { id } = await createOwnDashboard(page, request, "E2E Versions Mobile");

    try {
      await nameCurrentState(request, id, "e2e mobile version");

      await page.setViewportSize({ width: 375, height: 812 });
      await openEditor(page, id);
      await openSettings(page);

      // At 640px and below the rail becomes a Select.
      await expect(page.getByTestId("settings-nav-history")).toHaveCount(0);
      await page.getByTestId("settings-nav-select").click();
      await page.getByRole("option", { name: "History", exact: true }).click();

      await expect(page.getByTestId("settings-section-history")).toBeVisible();
      await expect(page.getByTestId("version-history-panel")).toBeVisible();
      const rows = page.getByTestId("version-row");
      await expect(rows.first()).toBeVisible();
      await expect(rows.filter({ hasText: "e2e mobile version" })).toBeVisible();

      const fits = await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      );
      expect(fits, "the page should not scroll horizontally").toBe(true);
    } finally {
      await deleteDashboardViaApi(request, id);
    }
  });
});
