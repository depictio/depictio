/**
 * Session annotations: the Annotate panel on a dashboard.
 *
 * Against the seeded Penguins dashboard, whose table (`penguins_complete`) is
 * keyed by `individual_id`:
 *   - a reader adds an annotation, labels rows, picks it in "Compare by", and
 *     each label becomes a group of the Analysis panel;
 *   - a reload keeps the annotations (account storage for a signed-in user);
 *   - a CSV dropped on the grid is read in the browser: no request carries it;
 *   - Save to table runs the add_columns merge (dry run, then apply) and takes
 *     the annotation out of the session — the merge route is stubbed, because
 *     the seeded table is a join, which no one may edit;
 *   - a temporary account (public mode only) keeps annotations in the browser
 *     and sees the account-only controls disabled.
 *
 * Skips itself when the Penguins dashboard is not seeded.
 */

import { Page, Request } from "@playwright/test";
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

/** Drop the page session's annotations. Through the page, not `request`: in
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
  const button = page.locator("[data-testid='annotate-button']");
  await expect(button).toBeVisible({ timeout: 30_000 });
  await button.click();
  await expect(page.locator("[data-testid='annotation-grid'] .ag-row").first()).toBeVisible({
    timeout: 30_000,
  });
}

async function addAnnotation(page: Page, name: string): Promise<void> {
  await page.locator("[data-testid='annotation-new-name']").fill(name);
  await page.locator("[data-testid='annotation-add']").click();
  await expect(page.locator("[data-testid='annotation-grid'] .ag-header-cell-text", { hasText: name })).toBeVisible();
}

/** Type a label into the annotation `column` of the row at `rowIndex`. */
async function label(page: Page, column: string, rowIndex: number, value: string): Promise<void> {
  const grid = page.locator("[data-testid='annotation-grid']");
  const colId = await grid
    .locator(".ag-header-cell", { has: page.locator(".ag-header-cell-text", { hasText: new RegExp(`^${column}$`) }) })
    .getAttribute("col-id");
  const cell = grid.locator(`.ag-center-cols-container [row-index='${rowIndex}'] [col-id='${colId}']`);
  await cell.click();
  await page.keyboard.type(value);
  await page.keyboard.press("Enter");
  await expect(cell).toHaveText(value);
}

async function compareBy(page: Page, name: string): Promise<void> {
  await page.locator("[data-testid='annotation-compare-by']").click();
  await page.getByRole("option", { name: new RegExp(`^${name} \\(`) }).click();
}

test.describe("Session annotations", () => {
  // One account's annotations on one dashboard: the tests must not overlap.
  test.describe.configure({ mode: "serial" });

  test("labels become Analysis groups and survive a reload", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "Penguins dashboard not seeded on this stack");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    await openPanel(page);
    await expect(page.locator("[data-testid='annotation-storage-note']")).toContainText(
      "Kept on your account",
    );
    await addAnnotation(page, "response");
    await label(page, "response", 0, "responder");
    await label(page, "response", 1, "non-responder");
    await label(page, "response", 2, "responder");

    const saved = page.waitForResponse(
      (r) => r.url().startsWith(ANNOTATIONS_URL) && r.request().method() === "PUT" && r.ok(),
    );
    await compareBy(page, "response");
    await saved;

    await page.locator("[data-testid='annotation-open-analysis']").click();
    const analysis = page.getByRole("dialog", { name: /^Analysis/ });
    await expect(analysis).toBeVisible();
    await expect(analysis).toContainText("responder");
    await expect(analysis).toContainText("non-responder");

    // Account storage: a reload (a fresh read) brings them back.
    await openPanel(page);
    await expect(page.locator("[data-testid='annotation-panel']")).toContainText("response · 3");
    await expect(page.locator("[data-testid='annotation-compare-by']")).toHaveValue(/^response/);

    await clearAnnotations(page);
  });

  test("a dropped CSV is read in the browser and never sent", async ({ page, request, loginAsAdmin }) => {
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
    // Armed before the drop: the debounced account save may land quickly.
    const saved = page.waitForResponse(
      (r) => r.url().startsWith(ANNOTATIONS_URL) && r.request().method() === "PUT",
      { timeout: 15_000 },
    );
    await page.locator("[data-testid='annotation-drop-zone']").evaluate((zone, text) => {
      const dt = new DataTransfer();
      dt.items.add(new File([text], "cohorts.csv", { type: "text/csv" }));
      zone.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
    }, csv);

    const report = page.locator("[data-testid='annotation-drop-report']");
    await expect(report).toContainText("in your browser");
    await expect(report).toContainText("2 rows");
    await expect(report).toContainText("not_a_penguin");
    await expect(page.locator("[data-testid='annotation-panel']")).toContainText("cohort_from_file · 2");

    // Let the debounced account save go out, then look at everything sent.
    await saved;
    for (const r of sent) {
      const headers = r.headers();
      expect(headers["content-type"] ?? "", `${r.url()} sent a form`).not.toContain("multipart/form-data");
      expect(r.postData() ?? "", `${r.url()} carried the file`).not.toContain("individual_id,cohort_from_file");
      expect(r.url()).not.toContain("merge_file");
    }

    await clearAnnotations(page);
  });

  test("Save to table merges the labels as a new column", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(120_000);
    const api = await seeded(request);
    test.skip(!api, "Penguins dashboard not seeded on this stack");
    await signIn(loginAsAdmin);
    await noWalkthrough(page);
    await clearAnnotations(page);

    // The seeded table is a join, which no one may edit: answer as for a table
    // a user added, and stub the merge so the stack's data stays as it is.
    await page.route("**/datacollections/*/edit_status", (route) =>
      route.fulfill({
        json: { table_editable: true, can_edit: true, role_can_edit: true, code: null, reason: null, max_rows: 100000 },
      }),
    );
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
    await addAnnotation(page, "status");
    await label(page, "status", 0, "kept");
    await label(page, "status", 1, "dropped");

    await page.locator("[data-testid='annotation-save-to-table']").click();
    await page.getByRole("menuitem", { name: "status" }).click();
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
    await expect(page.locator("[data-testid='annotation-panel']")).not.toContainText("status · 2");

    await clearAnnotations(page);
  });

  test("a temporary account keeps annotations in the browser", async ({ page }) => {
    test.setTimeout(120_000);
    const mode = await getAuthMode();
    test.skip(!mode.is_public_mode, "temporary accounts exist in public mode only");

    // Public mode hands the visitor a temporary account on arrival.
    await noWalkthrough(page);
    await page.goto(`/dashboard/${PENGUINS}`);
    const button = page.locator("[data-testid='annotate-button']");
    const visible = await button.isVisible({ timeout: 30_000 }).catch(() => false);
    test.skip(!visible, "the Penguins dashboard is not public on this stack");
    await button.click();

    await expect(page.locator("[data-testid='annotation-storage-note']")).toContainText(
      "Kept in this browser",
    );
    await expect(page.locator("[data-testid='annotation-edit-tab']")).toBeDisabled();
    await addAnnotation(page, "mine");
    await label(page, "mine", 0, "a");
    await expect(page.locator("[data-testid='annotation-save-to-table']")).toBeDisabled();

    const stored = await page.evaluate(
      (id) => window.localStorage.getItem(`depictio.annotations.${id}`),
      PENGUINS,
    );
    expect(stored).toContain('"mine"');
  });
});
