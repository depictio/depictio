/**
 * Session labels: the Labels tab of the Analysis panel.
 *
 * Against the seeded Penguins dashboard, whose table (`penguins_complete`) is
 * keyed by `individual_id`:
 *   - a reader adds a label column with "+", types labels, picks "Compare in
 *     the charts" in the column menu, and each label becomes an Analysis group;
 *   - a reload keeps the labels (account storage for a signed-in user);
 *   - a CSV dropped on the tab opens a preview, is read in the browser, and its
 *     labels stay there (no request carries them) until kept on the account;
 *   - "Save to table" in a column menu runs the add_columns merge;
 *   - a table cell edited in the grid is saved to the table from the bar below;
 *   - a temporary account (public mode only) keeps labels in the browser.
 *
 * The seeded table is a join, which no one may edit, so the write tests answer
 * as for a table a user added and stub the writes: the stack's data never changes.
 * Skips itself when the Penguins dashboard is not seeded.
 */

import { Page, Request, Route } from "@playwright/test";
import { test, expect, API_URL, API_PREFIX, apiOnlyToken, getAuthMode } from "@fixtures/auth";

const PENGUINS = "6824cb3b89d2b72169309738";
const ANNOTATIONS_URL = `${API_URL}${API_PREFIX}/dashboards/annotations/${PENGUINS}`;

type Api = Parameters<typeof apiOnlyToken>[0];

/** Headers for API calls as the admin, or null when the dashboard is not seeded.
 *  Single-user mode needs no token: every call is the one user's. */
async function seeded(request: Api): Promise<Record<string, string> | null> {
  try {
    const headers: Record<string, string> = (await getAuthMode()).is_single_user_mode
      ? {}
      : { Authorization: `Bearer ${(await apiOnlyToken(request, "adminUser")).access_token}` };
    const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/get/${PENGUINS}`, { headers });
    return res.ok() ? headers : null;
  } catch {
    return null;
  }
}

/** Drop the page session's labels. Through the page, not `request`: in
 *  single-user mode the SPA holds the admin's token, while a call without one
 *  is the anonymous user's, so only the page reaches the document it wrote. */
async function clearAnnotations(page: Page): Promise<void> {
  if (!page.url().includes("/dashboard/")) await page.goto(`/dashboard/${PENGUINS}`);
  const status = await page.evaluate(async (url) => {
    let token = "";
    try {
      token = JSON.parse(window.localStorage.getItem("local-store") ?? "{}").access_token ?? "";
    } catch {
      token = "";
    }
    // Labels from a dropped file live in the browser.
    window.localStorage.removeItem(`depictio.annotations.${url.split("/").pop()}`);
    const res = await fetch(url, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return res.status;
  }, ANNOTATIONS_URL);
  expect(status).toBe(204);
}

/** Sign in as the admin, except in single-user mode, where there is no sign-in. */
async function signIn(loginAsAdmin: () => Promise<unknown>): Promise<void> {
  if (!(await getAuthMode()).is_single_user_mode) await loginAsAdmin();
}

/** The real `/auth/me/optional` answer with the first-run walkthrough off: its
 *  backdrop would cover the page on a stack that enables it. */
const walkthroughOff = new WeakSet<Page>();
async function noWalkthrough(page: Page): Promise<void> {
  if (walkthroughOff.has(page)) return;
  walkthroughOff.add(page);
  await page.route("**/api/v1/auth/me/optional**", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown> | null;
    await route.fulfill({ response, json: { ...(body ?? {}), walkthrough_disabled: true } });
  });
}

async function openPanel(page: Page): Promise<void> {
  await noWalkthrough(page);
  await page.goto(`/dashboard/${PENGUINS}`);
  const button = page.locator("[data-testid='analysis-button']");
  await expect(button).toBeVisible({ timeout: 30_000 });
  await button.click();
  await page.locator("[data-testid='analysis-tabs']").getByText("Labels", { exact: true }).click();
  await expect(page.locator("[data-testid='annotation-grid'] .ag-row").first()).toBeVisible({
    timeout: 30_000,
  });
}

async function addLabelColumn(page: Page, name: string): Promise<void> {
  await page.locator("[data-testid='label-add']").click();
  await page.locator("[data-testid='label-name-input']").fill(name);
  await page.locator("[data-testid='label-name-save']").click();
  await expect(page.locator(`[data-testid='label-menu-${name}']`)).toBeVisible();
}

/** The AG Grid column id of the column whose header reads `name`. */
async function columnId(page: Page, name: string): Promise<string> {
  const grid = page.locator("[data-testid='annotation-grid']");
  const id = await grid
    .locator(".ag-header-cell", { hasText: new RegExp(`^\\s*${name}\\s*$`) })
    .first()
    .getAttribute("col-id");
  expect(id, `no column ${name}`).toBeTruthy();
  return id!;
}

/** Type `value` into the `column` cell of the row at `rowIndex`. */
async function typeCell(page: Page, column: string, rowIndex: number, value: string): Promise<void> {
  const grid = page.locator("[data-testid='annotation-grid']");
  const id = await columnId(page, column);
  const cell = grid.locator(`.ag-center-cols-container [row-index='${rowIndex}'] [col-id='${id}']`);
  await cell.click();
  await page.keyboard.press("Control+A");
  await page.keyboard.type(value);
  await page.keyboard.press("Enter");
  await expect(cell).toHaveText(value);
}

async function columnMenu(page: Page, name: string, item: string): Promise<void> {
  await page.locator(`[data-testid='label-menu-${name}']`).click();
  await page.getByRole("menuitem", { name: new RegExp(`^${item}`) }).click();
}

/** Answer as for a table a user added: editable, read whole by the edit route
 *  (built from the real preview so the rows are the seeded ones). */
async function editableTable(page: Page, deltaVersion: number): Promise<void> {
  await page.route("**/datacollections/*/edit_status", (route) =>
    route.fulfill({
      json: { table_editable: true, can_edit: true, role_can_edit: true, code: null, reason: null, max_rows: 100000 },
    }),
  );
  await page.route("**/datacollections/*/edit_data", async (route: Route) => {
    const dcId = route.request().url().split("/datacollections/")[1].split("/")[0];
    // The table is read again after each write; the test may have ended by then.
    let body: { columns: string[]; rows: Record<string, unknown>[] };
    try {
      const preview = await route.fetch({
        url: `${API_URL}${API_PREFIX}/deltatables/preview/${dcId}?limit=10000`,
        method: "GET",
      });
      body = (await preview.json()) as typeof body;
    } catch {
      return;
    }
    await route.fulfill({
      json: {
        data_collection_id: dcId,
        delta_version: deltaVersion,
        row_count: body.rows.length,
        max_rows: 100000,
        columns: body.columns.map((name) => ({ name, dtype: "String", kind: "text", editable: true })),
        rows: body.rows,
      },
    });
  });
}

test.describe("Session labels", () => {
  // One account's labels on one dashboard: the tests must not overlap.
  test.describe.configure({ mode: "serial" });

  test("labels become Analysis groups and survive a reload", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "Penguins dashboard not seeded on this stack");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    await openPanel(page);
    // A signed-in account says nothing about storage: it is the normal case.
    await expect(page.locator("[data-testid='annotation-storage-note']")).toHaveCount(0);
    await addLabelColumn(page, "response");
    await typeCell(page, "response", 0, "responder");
    await typeCell(page, "response", 1, "non-responder");
    await typeCell(page, "response", 2, "responder");

    const saved = page.waitForResponse(
      (r) => r.url().startsWith(ANNOTATIONS_URL) && r.request().method() === "PUT" && r.ok(),
    );
    await columnMenu(page, "response", "Compare in the charts");
    await saved;
    await expect(page.locator("[data-testid='label-compared']")).toHaveCount(1);

    await page.locator("[data-testid='analysis-tabs']").getByText("Groups", { exact: true }).click();
    const analysis = page.getByRole("dialog", { name: /^Analysis/ });
    await expect(analysis).toContainText("responder");
    await expect(analysis).toContainText("non-responder");

    // Account storage: a reload (a fresh read) brings them back.
    await openPanel(page);
    await expect(page.locator("[data-testid='label-menu-response']")).toBeVisible();
    await expect(page.locator("[data-testid='label-compared']")).toHaveCount(1);

    await clearAnnotations(page);
  });

  test("a dropped CSV stays in the browser until kept on the account", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "Penguins dashboard not seeded on this stack");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    const csv = "individual_id,cohort_from_file\nadelie_1,early\nadelie_2,late\nnot_a_penguin,early\n";
    const sent: Request[] = [];
    page.on("request", (r) => {
      if (r.method() !== "GET") sent.push(r);
    });

    await openPanel(page);
    await page.locator("[data-testid='annotation-drop-zone']").evaluate((zone, text) => {
      const dt = new DataTransfer();
      dt.items.add(new File([text], "cohorts.csv", { type: "text/csv" }));
      zone.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
    }, csv);

    // A preview first, with the table editor's modes; nothing changes before Apply.
    const preview = page.locator("[data-testid='annotation-drop-preview']");
    await expect(preview).toContainText("Read in your browser");
    await expect(preview).toContainText("2 rows");
    await expect(preview).toContainText("not_a_penguin");
    await expect(preview).toContainText("New: cohort_from_file");
    await expect(page.locator("[data-testid='label-menu-cohort_from_file']")).toHaveCount(0);
    await page.locator("[data-testid='annotation-drop-apply']").click();
    await expect(page.locator("[data-testid='label-menu-cohort_from_file']")).toBeVisible();

    // Past the save debounce: nothing of the file left the browser.
    await page.waitForTimeout(2_500);
    for (const r of sent) {
      const body = r.postData() ?? "";
      expect(r.headers()["content-type"] ?? "", `${r.url()} sent a form`).not.toContain("multipart/form-data");
      expect(body, `${r.url()} carried the file`).not.toContain("cohort_from_file");
      expect(r.url()).not.toContain("merge_file");
    }
    const stored = await page.evaluate(
      (id) => window.localStorage.getItem(`depictio.annotations.${id}`),
      PENGUINS,
    );
    expect(stored).toContain("cohort_from_file");

    // A reload brings it back from the browser.
    await openPanel(page);
    await expect(page.locator("[data-testid='label-menu-cohort_from_file']")).toBeVisible();

    // Kept on the account only on the reader's explicit choice.
    const kept = page.waitForRequest(
      (r) =>
        r.url().startsWith(ANNOTATIONS_URL) &&
        r.method() === "PUT" &&
        (r.postData() ?? "").includes("cohort_from_file"),
    );
    await columnMenu(page, "cohort_from_file", "Keep on my account");
    await kept;

    await clearAnnotations(page);
  });

  test("Save to table merges a label column as a new column", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "Penguins dashboard not seeded on this stack");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    await editableTable(page, 7);
    const merges: { dryRun: string | null; mode: string | null; body: string }[] = [];
    await page.route("**/datacollections/*/merge_file", async (route) => {
      const body = route.request().postData() ?? "";
      const field = (name: string) => body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]*)`))?.[1] ?? null;
      merges.push({ dryRun: field("dry_run"), mode: field("mode"), body });
      await route.fulfill({
        json: {
          dry_run: field("dry_run") === "true",
          mode: "add_columns",
          suggested_mode: "add_columns",
          key: "individual_id",
          key_candidates: [],
          delta_version: 7,
          table_rows: 344,
          file_rows: 2,
          row_count: 344,
          matched_rows: 2,
          unmatched_file_rows: 0,
          unmatched_file_sample: [],
          filled_cells: 2,
          conflicts: 0,
          new_columns: ["status"],
          ignored_columns: [],
          removed_columns: [],
          warnings: [],
          can_apply: true,
          reason: null,
          changed: [],
          columns: [],
          rows: [],
        },
      });
    });

    await openPanel(page);
    await addLabelColumn(page, "status");
    await typeCell(page, "status", 0, "kept");
    await typeCell(page, "status", 1, "dropped");

    await columnMenu(page, "status", "Save to table");
    await expect(page.locator("[data-testid='annotation-save-modal']")).toContainText("2 of 344 rows");
    await page.locator("[data-testid='annotation-save-apply']").click();

    await expect.poll(() => merges.length).toBe(2);
    expect(merges.map((m) => [m.mode, m.dryRun])).toEqual([
      ["add_columns", "true"],
      ["add_columns", "false"],
    ]);
    expect(merges[1].body).toContain('name="base_version"\r\n\r\n7');
    expect(merges[1].body).toContain("individual_id,status");
    expect(merges[1].body).toContain("adelie_1,kept");
    // The column is now the table's: it leaves the session.
    await expect(page.locator("[data-testid='label-menu-status']")).toHaveCount(0);

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await clearAnnotations(page);
  });

  test("a table cell edited in the grid is saved to the table", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "Penguins dashboard not seeded on this stack");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    await editableTable(page, 7);
    let patched: { base_version: number; edits: { row: number; column: string; value: unknown }[] } | null = null;
    await page.route("**/datacollections/*/cells", async (route) => {
      patched = JSON.parse(route.request().postData() ?? "{}");
      await route.fulfill({ json: { success: true, data_collection_id: "x", delta_version: 8 } });
    });

    await openPanel(page);
    await typeCell(page, "bill_length_mm", 0, "41.5");
    const bar = page.locator("[data-testid='annotation-cell-bar']");
    await expect(bar).toContainText("1 change to the table");

    const refreshed = page.waitForRequest((r) => r.url().includes("/edit_data"));
    await page.locator("[data-testid='annotation-cell-save']").click();
    await expect.poll(() => patched).not.toBeNull();
    expect(patched!.base_version).toBe(7);
    expect(patched!.edits).toEqual([{ row: 0, column: "bill_length_mm", value: "41.5" }]);
    // The table is read again after the write.
    await refreshed;
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a temporary account keeps labels in the browser", async ({ page }) => {
    test.setTimeout(120_000);
    const mode = await getAuthMode();
    test.skip(!mode.is_public_mode, "temporary accounts exist in public mode only");

    // Public mode hands the visitor a temporary account on arrival.
    await noWalkthrough(page);
    await page.goto(`/dashboard/${PENGUINS}`);
    const button = page.locator("[data-testid='analysis-button']");
    const visible = await button.isVisible({ timeout: 30_000 }).catch(() => false);
    test.skip(!visible, "the Penguins dashboard is not public on this stack");
    await button.click();
    await page.locator("[data-testid='analysis-tabs']").getByText("Labels", { exact: true }).click();

    await expect(page.locator("[data-testid='annotation-storage-note']")).toContainText("in this browser");
    await addLabelColumn(page, "mine");
    await typeCell(page, "mine", 0, "a");

    const stored = await page.evaluate(
      (id) => window.localStorage.getItem(`depictio.annotations.${id}`),
      PENGUINS,
    );
    expect(stored).toContain('"mine"');
  });
});
