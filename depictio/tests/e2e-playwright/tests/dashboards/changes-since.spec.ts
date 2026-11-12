/**
 * "Changed since your last visit" (#1397): what a returning reader sees.
 *
 * A reader mark is per-reader state: the first visit stores the baseline (the
 * viewer records a visit 10 s after the page opens), and later opens show what
 * other people changed since. The spec drives that with two accounts: the seeded
 * admin edits, a freshly registered reader looks. It covers:
 *
 *   1. a first visit shows nothing, whatever the dashboard's history;
 *   2. another user's edit: pill, panel (with the author), the tile's dot, and
 *      "Mark as seen" clearing them; the author, who visited before editing,
 *      sees none of it (a reader's own changes never count);
 *   3. new data: a run appended to a MultiQC collection the dashboard reads
 *      shows in the Data section, with its new samples;
 *   4. neither a `?version=` preview nor the editor moves a mark.
 *
 * Everything the spec creates is its own and is deleted at the end: a public
 * project (so the reader may view it without a share), one MultiQC collection
 * built from `fixtures/data/changes_since/`, its dashboards and the reader.
 * The seeded projects are never written to; the MultiQC append in particular
 * re-processes every report of its collection, which a shared one must not
 * undergo while the catalog walk renders it.
 *
 * The visit is real: the reader's browser opens the dashboard and the spec waits
 * for the server to hold the mark (`first_visit` turns false), the same call the
 * viewer's 10 s timer makes. The admin's mark is written through the API
 * (`PUT .../visit`) instead of a second 10 s wait; it is the very request the
 * viewer sends.
 *
 * Needs `DEPICTIO_DASHBOARD_VERSIONS_CHANGES_SINCE_ENABLED=true` (the spec skips
 * itself on `features.changes_since` being absent from `/utils/server-info`) and
 * the standard auth mode: it registers an account, which single-user and public
 * mode do not allow.
 */

import { randomBytes, randomUUID } from "crypto";
import { existsSync, readFileSync } from "fs";
import { join } from "path";
import type { APIRequestContext, Browser, BrowserContext, Locator, Page } from "@playwright/test";
import {
  test,
  expect,
  apiLogin,
  apiOnlyToken,
  getAuthMode,
  seedTokenInStorage,
  API_URL,
  API_PREFIX,
  type TokenBundle,
} from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

const API = `${API_URL}${API_PREFIX}`;
const DATA_ROOT = join(__dirname, "../../fixtures/data/changes_since");
const READER_PASSWORD = "Test123!reader";

/** The viewer records a visit this long after the page opens (VISIT_DELAY_MS). */
const VISIT_DELAY_MS = 10_000;

interface ChangeSet {
  first_visit: boolean;
  since: string | null;
  server_held: boolean;
  data: Array<Record<string, unknown>>;
  dashboard: Array<{ kind: string; authors: string[]; component_title?: string; key?: string }>;
  comments: unknown[];
  changed_components: Record<string, string[]>;
}

interface Env {
  admin: TokenBundle;
  adminEmail: string;
  reader: { email: string; id: string };
  projectId: string;
  /** Dashboards created by the spec, deleted at the end. */
  dashboards: string[];
}

let env: Env | null = null;
let skipReason = "the spec's setup did not run";

const bearer = (tokens: TokenBundle): Record<string, string> => ({
  Authorization: `Bearer ${tokens.access_token}`,
});

const objectId = (): string => randomBytes(12).toString("hex");

/** The environment, or a skip of the calling test when the stack cannot run it. */
function ready(): Env {
  test.skip(!env, skipReason);
  return env!;
}

// ── API helpers ─────────────────────────────────────────────────────────────

async function createProject(request: APIRequestContext, admin: TokenBundle): Promise<string> {
  const id = objectId();
  const res = await request.post(`${API}/projects/create`, {
    headers: bearer(admin),
    data: {
      _id: id,
      name: `e2e-changes-since-${Date.now()}`,
      project_type: "basic",
      // Public: a signed-in reader gets the viewer floor without a share.
      is_public: true,
      permissions: {
        owners: [{ _id: admin.user_id, email: admin.email, is_admin: true }],
        editors: [],
        viewers: [],
      },
      workflows: [],
    },
  });
  const body = (await res.json()) as { success?: boolean; message?: string };
  expect(res.ok() && body.success !== false, `creating the project: ${body.message ?? res.status()}`).toBe(
    true,
  );
  return id;
}

/** A main-tab dashboard in `projectId`, owned by the admin (what the listing's
 *  "New Dashboard" sends). */
async function createDashboardViaApi(
  request: APIRequestContext,
  e: Env,
  title: string,
): Promise<string> {
  const id = objectId();
  const res = await request.post(`${API}/dashboards/save/${id}`, {
    headers: bearer(e.admin),
    data: {
      dashboard_id: id,
      version: 1,
      title,
      subtitle: "",
      icon: "mdi:view-dashboard",
      icon_color: "orange",
      icon_variant: "filled",
      workflow_system: "none",
      notes_content: "",
      permissions: {
        owners: [{ _id: e.admin.user_id, email: e.admin.email, is_admin: true }],
        editors: [],
        viewers: [],
      },
      last_saved_ts: "",
      project_id: e.projectId,
      is_main_tab: true,
      tab_order: 0,
    },
  });
  expect(res.ok(), `creating the dashboard: ${res.status()}`).toBe(true);
  e.dashboards.push(id);
  return id;
}

/** Replaces the dashboard's components and saves, which captures a version. */
async function saveComponents(
  request: APIRequestContext,
  admin: TokenBundle,
  id: string,
  components: Array<Record<string, unknown>>,
): Promise<void> {
  const headers = bearer(admin);
  const getRes = await request.get(`${API}/dashboards/get/${id}`, { headers });
  expect(getRes.ok(), "reading the dashboard should succeed").toBe(true);
  const doc = (await getRes.json()) as Record<string, unknown>;
  doc.stored_metadata = components;
  doc.right_panel_layout_data = components.map((c, n) => ({
    i: c.index,
    x: 0,
    y: n * 2,
    w: 6,
    h: 2,
  }));
  doc.notes_content = "";
  const saveRes = await request.post(`${API}/dashboards/save/${id}`, { headers, data: doc });
  expect(saveRes.ok(), `saving the dashboard: ${saveRes.status()}`).toBe(true);
}

const textTile = (index: string, body: string) => ({
  index,
  component_type: "text",
  title: "Notes tile",
  body,
});

async function changeSet(
  request: APIRequestContext,
  tokens: TokenBundle,
  id: string,
): Promise<ChangeSet> {
  const res = await request.post(`${API}/changes/dashboard/${id}`, {
    headers: bearer(tokens),
    data: {},
  });
  expect(res.ok(), `reading the change set: ${res.status()}`).toBe(true);
  return (await res.json()) as ChangeSet;
}

/** Waits until the server holds the caller's mark for the dashboard: the
 *  viewer's visit timer fired. */
async function waitForMark(
  request: APIRequestContext,
  tokens: TokenBundle,
  id: string,
): Promise<void> {
  await expect
    .poll(async () => (await changeSet(request, tokens, id)).first_visit, {
      timeout: VISIT_DELAY_MS * 4,
      intervals: [1_000],
      message: "the viewer should record the reader's visit and the server hold the mark",
    })
    .toBe(false);
}

async function listVersionIds(
  request: APIRequestContext,
  admin: TokenBundle,
  id: string,
): Promise<string[]> {
  const res = await request.get(`${API}/dashboards/${id}/versions?limit=200`, {
    headers: bearer(admin),
  });
  expect(res.ok(), "listing versions should succeed").toBe(true);
  const body = (await res.json()) as { versions: Array<{ version_id: string; seq: number }> };
  return [...body.versions].sort((a, b) => a.seq - b.seq).map((v) => v.version_id);
}

// ── MultiQC data (cases that need new data) ─────────────────────────────────

/** The fixture parquet of a run, or null where the checkout lacks it. */
function runParquet(group: "two_runs" | "new_run", run: string): Buffer | null {
  const path = join(DATA_ROOT, group, run, "multiqc", "multiqc_data", "multiqc.parquet");
  return existsSync(path) ? readFileSync(path) : null;
}

/** `files` of an upload: one `multiqc.parquet` per run. The name carries the
 *  run as its folder (`<run>/multiqc_data/multiqc.parquet`), which is how the
 *  server tells reports apart. */
function addRuns(form: FormData, runs: Array<[string, Buffer]>): void {
  for (const [run, bytes] of runs) {
    form.append(
      "files",
      new Blob([new Uint8Array(bytes)], { type: "application/octet-stream" }),
      `${run}/multiqc_data/multiqc.parquet`,
    );
  }
}

async function postForm(admin: TokenBundle, path: string, form: FormData): Promise<unknown> {
  const res = await fetch(`${API}${path}`, { method: "POST", headers: bearer(admin), body: form });
  const text = await res.text();
  expect(res.ok, `POST ${path}: ${res.status} ${text.slice(0, 300)}`).toBe(true);
  return JSON.parse(text);
}

/** A MultiQC collection holding the `two_runs` reports, in the spec's project. */
async function createMultiqcCollection(
  admin: TokenBundle,
  projectId: string,
  name: string,
  runs: Array<[string, Buffer]>,
): Promise<{ dcId: string; workflowId: string }> {
  const form = new FormData();
  form.append("project_id", projectId);
  form.append("name", name);
  form.append("description", "Created by the changes-since e2e spec.");
  addRuns(form, runs);
  const body = (await postForm(admin, "/datacollections/create_multiqc_from_upload", form)) as {
    data_collection_id: string;
    workflow_id: string;
  };
  return { dcId: body.data_collection_id, workflowId: body.workflow_id };
}

async function appendRun(admin: TokenBundle, dcId: string, run: [string, Buffer]): Promise<void> {
  const form = new FormData();
  addRuns(form, [run]);
  await postForm(admin, `/multiqc/reports/data-collection/${dcId}/append`, form);
}

// ── browser helpers ─────────────────────────────────────────────────────────

/** A second, signed-in browser session: the reader's. Its tokens are its own
 *  login, never the API token the spec polls with (the SPA rotates its own). */
async function openAsReader(
  browser: Browser,
  request: APIRequestContext,
  e: Env,
): Promise<{ context: BrowserContext; page: Page }> {
  const tokens = await apiLogin(request, e.reader.email, READER_PASSWORD);
  tokens.email = e.reader.email;
  const context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 1920, height: 1080 },
  });
  const page = await context.newPage();
  await seedTokenInStorage(page, tokens);
  return { context, page };
}

/** Opens the viewer and returns the change set the page fetched. The walkthrough
 *  is switched off: its backdrop would cover a new account's first page. */
async function openViewer(page: Page, id: string, query = ""): Promise<ChangeSet> {
  const fetched = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname.includes("/changes/dashboard/") &&
      r.ok(),
    { timeout: 45_000 },
  );
  await page.goto(`/dashboard/${id}?no-walkthrough=1${query}`);
  return (await (await fetched).json()) as ChangeSet;
}

const pill = (page: Page): Locator => page.getByTestId("changes-pill").first();
const tile = (page: Page, index: string): Locator =>
  page.locator(`[data-component-index="${index}"]`).first();
const dot = (page: Page, index: string): Locator =>
  tile(page, index).getByTestId("component-updated-dot");

/** Lets the page act on a change set it has just received. Used only before an
 *  *absence* assertion, which would otherwise pass before anything rendered. */
const settle = (page: Page): Promise<void> => page.waitForTimeout(750);

/** The pill's panel, open. */
async function openPanel(page: Page): Promise<Locator> {
  await expect(pill(page)).toBeVisible({ timeout: 30_000 });
  await pill(page).click();
  const panel = page.getByTestId("changes-panel");
  await expect(panel).toBeVisible();
  return panel;
}

// ── the spec ────────────────────────────────────────────────────────────────

test.describe("Changed since your last visit", () => {
  // One project, one reader, tests that build on the stack's state in order.
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ request }) => {
    // Hooks take their budget from the project timeout, not from a test's own.
    test.setTimeout(180_000);
    if (process.env.UNAUTHENTICATED_MODE === "true") {
      skipReason = "Dashboards and accounts need an authenticated stack.";
      return;
    }
    const mode = await getAuthMode();
    if (mode.is_single_user_mode || mode.is_public_mode || mode.is_demo_mode) {
      skipReason = "Needs the standard auth mode: a second account is registered.";
      return;
    }
    const info = await request.get(`${API}/utils/server-info`);
    const features = info.ok()
      ? ((await info.json()) as { features?: { changes_since?: boolean } }).features
      : undefined;
    if (!features?.changes_since) {
      skipReason =
        "features.changes_since is off: set DEPICTIO_DASHBOARD_VERSIONS_CHANGES_SINCE_ENABLED=true.";
      return;
    }

    const admin = await apiOnlyToken(request, "adminUser");
    const email = `e2e-changes-${Date.now()}@example.com`;
    const reg = await request.post(`${API}/auth/register`, {
      data: { email, password: READER_PASSWORD, is_admin: false },
      headers: { "Content-Type": "application/json" },
    });
    if (reg.status() === 403) {
      skipReason = "Registration is closed on this stack: the reader account cannot be made.";
      return;
    }
    expect(reg.ok(), `registering the reader: ${reg.status()}`).toBe(true);
    const reader = await apiLogin(request, email, READER_PASSWORD);

    env = {
      admin,
      adminEmail: admin.email ?? credentials.adminUser.email,
      reader: { email, id: reader.user_id },
      projectId: await createProject(request, admin),
      dashboards: [],
    };
  });

  test.afterAll(async ({ request }) => {
    test.setTimeout(120_000);
    if (!env) return;
    const headers = bearer(env.admin);
    for (const id of env.dashboards) {
      await request.delete(`${API}/dashboards/delete/${id}`, { headers });
    }
    await request.delete(`${API}/projects/delete?project_id=${env.projectId}`, { headers });
    await request.delete(`${API}/auth/delete/${env.reader.id}`, { headers });
  });

  test("a first visit shows no marks", async ({ browser, request }) => {
    test.setTimeout(120_000);
    const e = ready();
    const id = await createDashboardViaApi(request, e, "E2E Changes first visit");
    const tileId = randomUUID();
    // The dashboard already has a history by someone else: a first visit must
    // not read it as news.
    await saveComponents(request, e.admin, id, [textTile(tileId, "First wording")]);
    await saveComponents(request, e.admin, id, [textTile(tileId, "Second wording")]);

    const { context, page } = await openAsReader(browser, request, e);
    try {
      const cs = await openViewer(page, id);
      expect(cs.first_visit, "the reader has never opened this dashboard").toBe(true);
      expect(cs.dashboard).toHaveLength(0);
      await expect(tile(page, tileId)).toBeVisible({ timeout: 30_000 });
      await settle(page);
      await expect(page.getByTestId("changes-pill")).toHaveCount(0);
      await expect(page.getByTestId("component-updated-dot")).toHaveCount(0);
    } finally {
      await context.close();
    }
  });

  test("another user's edit shows as a pill, a panel row and a dot, until seen", async ({
    browser,
    request,
    page,
    loginAsAdmin,
  }) => {
    test.setTimeout(240_000);
    const e = ready();
    const id = await createDashboardViaApi(request, e, "E2E Changes edit");
    const tileId = randomUUID();
    const stamp = Date.now();
    await saveComponents(request, e.admin, id, [textTile(tileId, `Before ${stamp}`)]);
    // The author has visited too, before editing: their own mark exists, so the
    // self-exclusion below is a real test and not "no mark, nothing shown".
    const adminVisit = await request.put(`${API}/changes/dashboard/${id}/visit`, {
      headers: bearer(e.admin),
    });
    expect(adminVisit.ok(), "the admin's visit").toBe(true);

    const reader = await openAsReader(browser, request, e);
    try {
      await test.step("the reader's first visit stores the mark", async () => {
        const first = await openViewer(reader.page, id);
        expect(first.first_visit).toBe(true);
        await expect(tile(reader.page, tileId)).toBeVisible({ timeout: 30_000 });
        // Server-side proof, with the reader's own identity: a fresh login.
        const readerApi = await apiLogin(request, e.reader.email, READER_PASSWORD);
        await waitForMark(request, readerApi, id);
      });

      await saveComponents(request, e.admin, id, [textTile(tileId, `After ${stamp}`)]);
      const readerApi = await apiLogin(request, e.reader.email, READER_PASSWORD);

      await test.step("the reader sees it on the next open", async () => {
        const cs = await openViewer(reader.page, id);
        expect(cs.first_visit).toBe(false);
        expect(cs.dashboard.map((c) => c.kind)).toContain("component_edited");
        expect(cs.dashboard.flatMap((c) => c.authors)).toContain(e.adminEmail);

        const panel = await openPanel(reader.page);
        await expect(panel.getByTestId("changes-section-dashboard")).toBeVisible();
        const row = panel.getByTestId("changes-dashboard-row").first();
        await expect(row).toContainText("Notes tile");
        await expect(row).toContainText(e.adminEmail);
        // Nothing moved in the data, and no one commented.
        await expect(panel.getByTestId("changes-section-data")).toHaveCount(0);
        await expect(panel.getByTestId("changes-section-comments")).toHaveCount(0);
        await expect(panel.getByTestId("changes-mark-seen")).toBeVisible();
        await reader.page.keyboard.press("Escape");

        const marked = dot(reader.page, tileId);
        await expect(marked).toBeVisible({ timeout: 15_000 });
        await expect(marked).toHaveAttribute("data-change-reasons", /definition/);
      });

      await test.step("a dot dismisses its tile and keeps the rest", async () => {
        await tile(reader.page, tileId).hover();
        await dot(reader.page, tileId).click();
        await expect(reader.page.getByTestId("component-updated-menu")).toBeVisible();
        await expect(reader.page.getByTestId("component-updated-before-now")).toBeVisible();
        const dismissed = reader.page.waitForResponse(
          (r) => r.request().method() === "PUT" && /\/changes\/dashboard\/[^/]+\/seen$/.test(r.url()),
        );
        await reader.page.getByTestId("component-updated-seen").click();
        expect((await dismissed).ok()).toBe(true);
        await expect(dot(reader.page, tileId)).toHaveCount(0);

        // The dismissal is stored: a reload keeps the tile quiet while the
        // dashboard still lists the edit.
        await openViewer(reader.page, id);
        await expect(pill(reader.page)).toBeVisible({ timeout: 30_000 });
        await expect(dot(reader.page, tileId)).toHaveCount(0);
      });

      await test.step("Mark as seen moves the mark", async () => {
        const panel = await openPanel(reader.page);
        const seen = reader.page.waitForResponse(
          (r) => r.request().method() === "PUT" && /\/changes\/dashboard\/[^/]+\/seen$/.test(r.url()),
        );
        await panel.getByTestId("changes-mark-seen").click();
        expect((await seen).ok()).toBe(true);
        await expect(pill(reader.page)).toBeHidden();

        const cs = await openViewer(reader.page, id);
        expect(cs.first_visit).toBe(false);
        expect(cs.dashboard).toHaveLength(0);
        await expect(tile(reader.page, tileId)).toBeVisible({ timeout: 30_000 });
        await settle(reader.page);
        await expect(reader.page.getByTestId("changes-pill")).toHaveCount(0);
        await expect(reader.page.getByTestId("component-updated-dot")).toHaveCount(0);
        expect((await changeSet(request, readerApi, id)).changed_components).toEqual({});
      });
    } finally {
      await reader.context.close();
    }

    await test.step("the author sees none of their own edit", async () => {
      const cs = await changeSet(request, e.admin, id);
      expect(cs.first_visit, "the admin's mark was stored before the edit").toBe(false);
      expect(cs.dashboard).toHaveLength(0);
      expect(cs.changed_components).toEqual({});

      await loginAsAdmin();
      const fetched = await openViewer(page, id);
      expect(fetched.first_visit).toBe(false);
      await expect(tile(page, tileId)).toBeVisible({ timeout: 30_000 });
      await expect(tile(page, tileId)).toContainText(`After ${stamp}`);
      await settle(page);
      await expect(page.getByTestId("changes-pill")).toHaveCount(0);
      await expect(page.getByTestId("component-updated-dot")).toHaveCount(0);
    });
  });

  test("new data in a collection the dashboard reads shows in the Data section", async ({
    browser,
    request,
  }) => {
    // A MultiQC collection is built and then re-processed: both go through the
    // same pipeline the upload dialog uses.
    test.setTimeout(420_000);
    const e = ready();
    const runA = runParquet("two_runs", "run_a");
    const runB = runParquet("two_runs", "run_b");
    const runC = runParquet("new_run", "run_c");
    test.skip(
      !runA || !runB || !runC,
      "fixtures/data/changes_since/ is missing its multiqc.parquet files.",
    );

    const stamp = Date.now();
    const collectionTag = `e2e-mqc-${stamp}`;
    const { dcId, workflowId } = await createMultiqcCollection(e.admin, e.projectId, collectionTag, [
      ["run_a", runA!],
      ["run_b", runB!],
    ]);

    const id = await createDashboardViaApi(request, e, "E2E Changes data");
    const mqcId = randomUUID();
    await saveComponents(request, e.admin, id, [
      {
        index: mqcId,
        component_type: "multiqc",
        title: "Sequencing QC",
        wf_id: workflowId,
        dc_id: dcId,
        data_collection_tag: collectionTag,
        dc_config: { type: "multiqc", metatype: "metadata", data_collection_tag: collectionTag },
      },
    ]);

    const reader = await openAsReader(browser, request, e);
    try {
      await test.step("the reader's first visit stores the mark", async () => {
        const first = await openViewer(reader.page, id);
        expect(first.first_visit).toBe(true);
        const readerApi = await apiLogin(request, e.reader.email, READER_PASSWORD);
        await waitForMark(request, readerApi, id);
      });

      await test.step("the admin appends a run", async () => {
        await appendRun(e.admin, dcId, ["run_c", runC!]);
      });

      const readerApi = await apiLogin(request, e.reader.email, READER_PASSWORD);
      await test.step("the change set names the collection and its new samples", async () => {
        const cs = await changeSet(request, readerApi, id);
        expect(cs.dashboard, "no one edited the dashboard").toHaveLength(0);
        expect(cs.data).toHaveLength(1);
        const change = cs.data[0];
        expect(change.dc_id).toBe(dcId);
        expect(change.reports_added as number).toBeGreaterThanOrEqual(1);
        expect(change.new_sample_count as number).toBeGreaterThan(0);
        const key = Object.keys(cs.changed_components).find((k) => k.endsWith(`:${mqcId}`));
        expect(key, "the tile reading the collection is marked").toBeTruthy();
        expect(cs.changed_components[key!]).toContain("data");
      });

      await test.step("the reader sees it on the next open", async () => {
        const cs = await openViewer(reader.page, id);
        expect(cs.data).toHaveLength(1);

        const panel = await openPanel(reader.page);
        await expect(panel.getByTestId("changes-section-data")).toBeVisible();
        await expect(panel.getByTestId("changes-section-dashboard")).toHaveCount(0);
        const row = panel.getByTestId("changes-data-row");
        await expect(row).toHaveCount(1);
        await expect(row).toHaveAttribute("data-dc-id", dcId);
        await expect(row).toContainText(collectionTag);
        await expect(row.getByTestId("changes-samples")).toBeVisible();
        await reader.page.keyboard.press("Escape");

        await expect(dot(reader.page, mqcId)).toHaveAttribute("data-change-reasons", /data/, {
          timeout: 15_000,
        });
      });
    } finally {
      await reader.context.close();
    }
  });

  test("a ?version= preview and the editor do not move a mark", async ({
    browser,
    request,
    page,
    loginAsAdmin,
  }) => {
    test.setTimeout(240_000);
    const e = ready();
    const id = await createDashboardViaApi(request, e, "E2E Changes preview");
    const tileId = randomUUID();
    await saveComponents(request, e.admin, id, [textTile(tileId, "Original wording")]);

    const reader = await openAsReader(browser, request, e);
    try {
      const readerApi = await apiLogin(request, e.reader.email, READER_PASSWORD);
      await openViewer(reader.page, id);
      await waitForMark(request, readerApi, id);

      await saveComponents(request, e.admin, id, [textTile(tileId, "Edited wording")]);
      const before = await changeSet(request, readerApi, id);
      expect(before.dashboard.length, "the edit is news to the reader").toBeGreaterThan(0);
      expect(before.since).toBeTruthy();

      // The admin has no mark on this dashboard, and the editor must not make one.
      const adminBefore = await changeSet(request, e.admin, id);
      expect(adminBefore.first_visit).toBe(true);

      const writes: string[] = [];
      const watch = (p: Page) =>
        p.on("request", (r) => {
          if (new URL(r.url()).pathname.includes("/changes/")) writes.push(`${r.method()} ${r.url()}`);
        });
      watch(reader.page);
      watch(page);

      const [oldest] = await listVersionIds(request, e.admin, id);
      await reader.page.goto(`/dashboard/${id}?version=${oldest}&no-walkthrough=1`);
      await expect(reader.page.getByTestId("version-banner")).toBeVisible({ timeout: 30_000 });

      await loginAsAdmin();
      await page.goto(`/dashboard-edit/${id}?no-walkthrough=1`);
      await expect(page.getByRole("button", { name: "Settings", exact: true })).toBeVisible({
        timeout: 30_000,
      });

      // Past the viewer's visit timer: a normal open would have recorded one by now.
      await reader.page.waitForTimeout(VISIT_DELAY_MS + 3_000);

      expect(writes, "neither view may call the changes API").toEqual([]);
      const after = await changeSet(request, readerApi, id);
      expect(after.since, "the reader's mark did not move").toBe(before.since);
      expect(after.dashboard.length).toBe(before.dashboard.length);
      expect((await changeSet(request, e.admin, id)).first_visit, "the editor stored no mark").toBe(true);
    } finally {
      await reader.context.close();
    }
  });
});
