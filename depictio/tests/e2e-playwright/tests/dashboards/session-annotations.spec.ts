/**
 * Session labels: the Metadata panel.
 *
 * Only a metadata table linked to the data carries labels. Against the seeded
 * ampliseq dashboard, whose `samplesheet` (no metatype, keyed by `sampleID`)
 * and `metadata` sheet both link to the data:
 *   - the Metadata button opens a grid on a metadata table; Analysis keeps its
 *     groups only (no tabs);
 *   - a reader adds a label column with "+", types labels, picks "Compare in
 *     the charts" in the column menu, and each label becomes an Analysis group;
 *   - a reload keeps the labels (account storage for a signed-in user);
 *   - labels belong to their table: switching table shows that table's own;
 *   - a CSV dropped on the panel opens a preview, is read in the browser, and
 *     its labels stay there (no request carries them) until kept on the account;
 *   - "Save to table" in a column menu runs the add_columns merge;
 *   - a table cell edited in the grid is saved to the table from the bar below;
 *   - a label column shared on the dashboard comes back after a reload, is
 *     read-only for a reader who may not change it (who can copy it to their
 *     own), and goes back to its editor's own on "Stop sharing";
 *   - Export downloads the table's rows with the label columns, built in the
 *     browser;
 *   - the Penguins dashboard, whose tables are joined, has no Metadata button;
 *   - a temporary account (public mode only) keeps labels in the browser.
 *
 * The write tests answer as for a table a user added and stub the writes, so
 * the stack's data never changes (the ampliseq tables come from a pipeline,
 * which no one may edit). Skips itself when the dashboard has no metadata
 * table. `SESSION_LABELS_DASHBOARD` points the suite at another dashboard
 * whose project has a linked metadata table (a stack without ampliseq); the
 * first metadata table and its first key column are read from the server.
 */

import { Page, Request, Route } from "@playwright/test";
import { test, expect, API_URL, API_PREFIX, apiOnlyToken, getAuthMode } from "@fixtures/auth";

const AMPLISEQ = "646b0f3c1e4a2d7f8e5b8ca2";
const DASHBOARD = process.env.SESSION_LABELS_DASHBOARD || AMPLISEQ;
/** Iris: one table and no link, so no metadata table to label. */
const IRIS = "6824cb3b89d2b72169309737";
const ANNOTATIONS_URL = `${API_URL}${API_PREFIX}/dashboards/annotations/${DASHBOARD}`;

interface Sheet {
  tag: string;
  key_columns: string[];
  row_count: number | null;
}
/** The dashboard's metadata tables, in the order the panel offers them. */
let sheets: Sheet[] = [];

type Api = Parameters<typeof apiOnlyToken>[0];

/** Headers for API calls as the admin, or null when the dashboard has no
 *  metadata table. Fills `sheets`.
 *  Single-user mode needs no token: every call is the one user's. */
async function seeded(request: Api): Promise<Record<string, string> | null> {
  try {
    const headers: Record<string, string> = (await getAuthMode()).is_single_user_mode
      ? {}
      : { Authorization: `Bearer ${(await apiOnlyToken(request, "adminUser")).access_token}` };
    const res = await request.get(`${ANNOTATIONS_URL}/tables`, { headers });
    if (!res.ok()) return null;
    const body = (await res.json()) as { tables: (Sheet & { eligible: boolean })[] };
    sheets = body.tables.filter((t) => t.eligible);
    return sheets.length > 0 ? headers : null;
  } catch {
    return null;
  }
}

/** Drop the page session's labels. Through the page, not `request`: in
 *  single-user mode the SPA holds the admin's token, while a call without one
 *  is the anonymous user's, so only the page reaches the document it wrote. */
async function clearAnnotations(page: Page): Promise<void> {
  if (!page.url().includes("/dashboard/")) await page.goto(`/dashboard/${DASHBOARD}`);
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

/** Replace the labels shared on the dashboard (none by default). Through the
 *  page, for the same reason as `clearAnnotations`. */
async function resetShared(page: Page): Promise<void> {
  if (!page.url().includes("/dashboard/")) await page.goto(`/dashboard/${DASHBOARD}`);
  const status = await page.evaluate(async (url) => {
    let token = "";
    try {
      token = JSON.parse(window.localStorage.getItem("local-store") ?? "{}").access_token ?? "";
    } catch {
      token = "";
    }
    const res = await fetch(`${url}/shared`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ columns: [] }),
    });
    return res.status;
  }, ANNOTATIONS_URL);
  expect(status).toBe(200);
}

/** Answer `/tables` as for a reader who may not change the shared labels. */
const TABLES_ROUTE = `**/dashboards/annotations/${DASHBOARD}/tables**`;
async function asReader(page: Page): Promise<void> {
  await page.route(TABLES_ROUTE, async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    await route.fulfill({ response, json: { ...body, can_share: false } });
  });
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
  await page.goto(`/dashboard/${DASHBOARD}`);
  const button = page.locator("[data-testid='metadata-button']");
  await expect(button).toBeVisible({ timeout: 30_000 });
  await button.click();
  await expect(page.locator("[data-testid='annotation-grid'] .ag-row").first()).toBeVisible({
    timeout: 30_000,
  });
}

/** Show the grid of the table tagged `tag` (the panel opens on the first one). */
async function pickTable(page: Page, tag: string): Promise<void> {
  await page.locator("[data-testid='annotation-table-select']").click();
  await page.getByRole("option", { name: tag, exact: true }).click();
  await expect(page.locator("[data-testid='annotation-grid'] .ag-row").first()).toBeVisible({
    timeout: 30_000,
  });
}

/** The key of the grid row at `rowIndex` (a real sample id of the seeded table). */
async function keyAt(page: Page, rowIndex: number): Promise<string> {
  const cell = page.locator(
    `[data-testid='annotation-grid'] .ag-pinned-left-cols-container [row-index='${rowIndex}'] [col-id='__key']`,
  );
  return ((await cell.textContent()) ?? "").trim();
}

/** A table column shown in the grid (after the key, the labels and "+"). */
async function editableColumn(page: Page): Promise<string> {
  const headers = page.locator("[data-testid='annotation-grid'] .ag-header-cell");
  const ids = await headers.evaluateAll((els) => els.map((e) => e.getAttribute("col-id") ?? ""));
  const id = ids.find((c) => c && c !== "__key" && c !== "__add" && !c.startsWith("ann:"));
  expect(id, "no table column in the grid").toBeTruthy();
  return id!;
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
  await cell.dblclick();
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
    test.skip(!api, "no metadata table on this dashboard");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);
    await resetShared(page);

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

    // Analysis lists them, as groups only: the panels share the right edge.
    await page.locator("[data-testid='analysis-button']").click();
    await expect(page.locator("[data-testid='metadata-panel']")).toBeHidden();
    const analysis = page.getByRole("dialog", { name: /^Analysis/ });
    await expect(analysis).toContainText("responder");
    await expect(analysis).toContainText("non-responder");
    // Said once at the top: the comparison is the reader's own, never saved.
    await expect(analysis.locator("[data-testid='analysis-temporary-note']")).toContainText("Temporary view");
    await expect(page.locator("[data-testid='analysis-tabs']")).toHaveCount(0);

    // Account storage: a reload (a fresh read) brings them back.
    await openPanel(page);
    await expect(page.locator("[data-testid='label-menu-response']")).toBeVisible();
    await expect(page.locator("[data-testid='label-compared']")).toHaveCount(1);

    await clearAnnotations(page);
  });

  test("a dropped CSV stays in the browser until kept on the account", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "no metadata table on this dashboard");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    const sent: Request[] = [];
    page.on("request", (r) => {
      if (r.method() !== "GET") sent.push(r);
    });

    await openPanel(page);
    const csv = `${sheets[0].key_columns[0]},cohort_from_file\n${await keyAt(page, 0)},early\n${await keyAt(page, 1)},late\nnot_a_sample,early\n`;
    await page.locator("[data-testid='annotation-drop-zone']").evaluate((zone, text) => {
      const dt = new DataTransfer();
      dt.items.add(new File([text], "cohorts.csv", { type: "text/csv" }));
      zone.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
    }, csv);

    // A preview first, with the table editor's modes; nothing changes before Apply.
    const preview = page.locator("[data-testid='annotation-drop-preview']");
    await expect(preview).toContainText("Read in your browser");
    await expect(preview).toContainText("2 rows");
    await expect(preview).toContainText("not_a_sample");
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
      DASHBOARD,
    );
    expect(stored).toContain("cohort_from_file");

    // A reload brings it back from the browser.
    await openPanel(page);
    await expect(page.locator("[data-testid='label-menu-cohort_from_file']")).toBeVisible();

    // Kept on the account only on the reader's explicit choice.
    const kept = page.waitForResponse(
      (r) =>
        r.url().startsWith(ANNOTATIONS_URL) &&
        r.request().method() === "PUT" &&
        (r.request().postData() ?? "").includes("cohort_from_file") &&
        r.ok(),
    );
    await columnMenu(page, "cohort_from_file", "Keep on my account");
    await kept;

    await clearAnnotations(page);
  });

  test("Save to table merges a label column as a new column", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "no metadata table on this dashboard");
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
          key: sheets[0].key_columns[0],
          key_candidates: [],
          delta_version: 7,
          table_rows: sheets[0].row_count,
          file_rows: 2,
          row_count: sheets[0].row_count,
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
    const first = await keyAt(page, 0);
    await addLabelColumn(page, "status");
    await typeCell(page, "status", 0, "kept");
    await typeCell(page, "status", 1, "dropped");

    await columnMenu(page, "status", "Save to table");
    await expect(page.locator("[data-testid='annotation-save-modal']")).toContainText(`2 of ${sheets[0].row_count} rows`);
    await page.locator("[data-testid='annotation-save-apply']").click();

    await expect.poll(() => merges.length).toBe(2);
    expect(merges.map((m) => [m.mode, m.dryRun])).toEqual([
      ["add_columns", "true"],
      ["add_columns", "false"],
    ]);
    expect(merges[1].body).toContain('name="base_version"\r\n\r\n7');
    expect(merges[1].body).toContain(`${sheets[0].key_columns[0]},status`);
    expect(merges[1].body).toContain(`${first},kept`);
    // The column is now the table's: it leaves the session.
    await expect(page.locator("[data-testid='label-menu-status']")).toHaveCount(0);

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await clearAnnotations(page);
  });

  test("a table cell edited in the grid is saved to the table", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "no metadata table on this dashboard");
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
    const column = await editableColumn(page);
    await typeCell(page, column, 0, "edited-value");
    const bar = page.locator("[data-testid='annotation-cell-bar']");
    await expect(bar).toContainText("1 change to the table");

    const refreshed = page.waitForRequest((r) => r.url().includes("/edit_data"));
    await page.locator("[data-testid='annotation-cell-save']").click();
    await expect.poll(() => patched).not.toBeNull();
    expect(patched!.base_version).toBe(7);
    expect(patched!.edits).toEqual([{ row: 0, column, value: "edited-value" }]);
    // The table is read again after the write.
    await refreshed;
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("labels belong to their table", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "no metadata table on this dashboard");
    test.skip(sheets.length < 2, "this dashboard has a single metadata table");
    const [first, second] = sheets.map((t) => t.tag);
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    await openPanel(page);
    await addLabelColumn(page, "on_sheet");
    await pickTable(page, second);
    await expect(page.locator("[data-testid='label-menu-on_sheet']")).toHaveCount(0);
    // Waited for, so the cleanup below is not undone by a save still pending.
    const saved = page.waitForResponse(
      (r) =>
        r.url().startsWith(ANNOTATIONS_URL) &&
        r.request().method() === "PUT" &&
        (r.request().postData() ?? "").includes("on_meta") &&
        r.ok(),
    );
    await addLabelColumn(page, "on_meta");
    await saved;
    await pickTable(page, first);
    await expect(page.locator("[data-testid='label-menu-on_sheet']")).toBeVisible();
    await expect(page.locator("[data-testid='label-menu-on_meta']")).toHaveCount(0);
    // Both are counted on the button.
    await expect(page.locator("[data-testid='metadata-panel']")).toContainText("2 label columns");

    await clearAnnotations(page);
  });

  test("a label shared on the dashboard is seen by every reader, read-only", async ({
    page,
    request,
    loginAsAdmin,
  }) => {
    test.setTimeout(180_000);
    const api = await seeded(request);
    test.skip(!api, "no metadata table on this dashboard");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);
    await resetShared(page);

    await openPanel(page);
    await addLabelColumn(page, "response");
    await typeCell(page, "response", 0, "responder");
    await typeCell(page, "response", 1, "non-responder");

    // Asked first, then written to the dashboard: the column leaves the reader's own.
    const shared = page.waitForResponse(
      (r) => r.url() === `${ANNOTATIONS_URL}/shared` && r.request().method() === "PUT" && r.ok(),
    );
    await columnMenu(page, "response", "Share on this dashboard");
    await expect(page.locator("[data-testid='annotation-confirm']")).toContainText("Everyone who can open");
    await page.locator("[data-testid='annotation-confirm-apply']").click();
    const body = (await (await shared).json()) as { shared: { name: string; values: Record<string, string> }[] };
    expect(body.shared.map((c) => c.name)).toEqual(["response"]);
    expect(Object.values(body.shared[0].values).sort()).toEqual(["non-responder", "responder"]);
    await expect(page.locator("[data-testid='label-kind-shared']")).toHaveCount(1);

    // A reload reads it from the dashboard; it can drive the comparison.
    await openPanel(page);
    await expect(page.locator("[data-testid='label-kind-shared']")).toHaveCount(1);
    const compared = page.waitForResponse(
      (r) =>
        r.url() === ANNOTATIONS_URL &&
        r.request().method() === "PUT" &&
        (r.request().postData() ?? "").includes('"activeColumnId":"') &&
        r.ok(),
    );
    await columnMenu(page, "response", "Compare in the charts");
    // Kept on the account although the reader has no column of their own.
    await compared;
    await expect(page.locator("[data-testid='label-compared']")).toHaveCount(1);

    // A reader without the right sees it read-only and may copy it.
    await asReader(page);
    await openPanel(page);
    await expect(page.locator("[data-testid='label-kind-shared-readonly']")).toHaveCount(1);
    await expect(page.locator("[data-testid='label-compared']")).toHaveCount(1);
    const id = await columnId(page, "response");
    const cell = page.locator(
      `[data-testid='annotation-grid'] .ag-center-cols-container [row-index='0'] [col-id='${id}']`,
    );
    await cell.dblclick();
    await expect(page.locator("[data-testid='annotation-grid'] .ag-cell-inline-editing")).toHaveCount(0);
    await page.locator("[data-testid='label-menu-response']").click();
    await expect(page.getByRole("menuitem", { name: /^Rename/ })).toHaveCount(0);
    await expect(page.getByRole("menuitem", { name: /^Delete/ })).toHaveCount(0);
    await expect(page.getByRole("menuitem", { name: /^Stop sharing/ })).toHaveCount(0);
    const copied = page.waitForResponse(
      (r) =>
        r.url() === ANNOTATIONS_URL &&
        r.request().method() === "PUT" &&
        (r.request().postData() ?? "").includes("response (copy)") &&
        r.ok(),
    );
    await page.getByRole("menuitem", { name: /^Copy to my labels/ }).click();
    await copied;
    await expect(page.locator("[data-testid='label-menu-response (copy)']")).toBeVisible();
    await expect(page.locator("[data-testid='label-kind-mine']")).toHaveCount(1);
    await page.unroute(TABLES_ROUTE);

    // Its editor stops sharing it: it is one of their own again.
    await clearAnnotations(page);
    await openPanel(page);
    const stopped = page.waitForResponse(
      (r) => r.url() === `${ANNOTATIONS_URL}/shared` && r.request().method() === "PUT" && r.ok(),
    );
    await columnMenu(page, "response", "Stop sharing");
    await page.locator("[data-testid='annotation-confirm-apply']").click();
    expect(((await (await stopped).json()) as { shared: unknown[] }).shared).toEqual([]);
    await expect(page.locator("[data-testid='label-kind-shared']")).toHaveCount(0);
    await expect(page.locator("[data-testid='label-kind-mine']")).toHaveCount(1);

    await resetShared(page);
    await clearAnnotations(page);
  });

  test("Export downloads the table's rows with the label columns", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "no metadata table on this dashboard");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    const sent: Request[] = [];
    await openPanel(page);
    const first = await keyAt(page, 0);
    await addLabelColumn(page, "cohort");
    await typeCell(page, "cohort", 0, "early");

    page.on("request", (r) => sent.push(r));
    await page.locator("[data-testid='annotation-export']").click();
    await expect(page.locator("[data-testid='annotation-export-modal']")).toContainText("cohort");
    const download = page.waitForEvent("download");
    await page.locator("[data-testid='annotation-export-apply']").click();
    const file = await download;
    expect(file.suggestedFilename()).toBe(`${sheets[0].tag}_with_labels.tsv`);
    const text = await (await import("node:fs/promises")).readFile((await file.path())!, "utf8");
    const [header, ...lines] = text.trim().split("\n");
    const columns = header.split("\t");
    expect(columns).toContain(sheets[0].key_columns[0]);
    expect(columns[columns.length - 1]).toBe("cohort");
    // Every row of the table, the labelled one carrying its label.
    expect(lines).toHaveLength(sheets[0].row_count!);
    const row = lines.find((l) => l.split("\t")[columns.indexOf(sheets[0].key_columns[0])] === first)!;
    expect(row.split("\t").at(-1)).toBe("early");
    // Built in the browser: no request carries it.
    expect(sent.filter((r) => (r.postData() ?? "").includes("early"))).toHaveLength(0);

    await clearAnnotations(page);
  });

  test("a dashboard without a linked metadata table has no Metadata button", async ({
    page,
    loginAsAdmin,
  }) => {
    test.setTimeout(60_000);
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await page.goto(`/dashboard/${IRIS}`);
    const analysis = page.locator("[data-testid='analysis-button']");
    // `isVisible` does not wait; the dashboard takes a moment to render.
    const seededIris = await analysis
      .waitFor({ state: "visible", timeout: 30_000 })
      .then(() => true)
      .catch(() => false);
    test.skip(!seededIris, "Iris dashboard not seeded on this stack");
    await expect(page.locator("[data-testid='metadata-button']")).toHaveCount(0);
  });

  test("a temporary account keeps labels in the browser", async ({ page }) => {
    test.setTimeout(120_000);
    const mode = await getAuthMode();
    test.skip(!mode.is_public_mode, "temporary accounts exist in public mode only");

    // Public mode hands the visitor a temporary account on arrival.
    await noWalkthrough(page);
    await page.goto(`/dashboard/${DASHBOARD}`);
    const button = page.locator("[data-testid='metadata-button']");
    const visible = await button
      .waitFor({ state: "visible", timeout: 30_000 })
      .then(() => true)
      .catch(() => false);
    test.skip(!visible, "the dashboard is not public on this stack");
    await button.click();

    await expect(page.locator("[data-testid='annotation-storage-note']")).toContainText("in this browser");
    await addLabelColumn(page, "mine");
    await typeCell(page, "mine", 0, "a");

    const stored = await page.evaluate(
      (id) => window.localStorage.getItem(`depictio.annotations.${id}`),
      DASHBOARD,
    );
    expect(stored).toContain('"mine"');
  });
});
