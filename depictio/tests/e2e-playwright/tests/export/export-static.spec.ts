/**
 * E2E for the serverless static-export API (phase 8).
 *
 * Contract under `${API_URL}/depictio/api/v1/serverless`
 * (depictio/api/v1/endpoints/serverless_endpoints/routes.py):
 *
 *   GET  /export-static/{dashboardId}/preflight  → tier table (viewer access)
 *   POST /export-static/{dashboardId}            → {job_id, status:"pending"}
 *                                                  (owner-only; 404 anti-enumeration)
 *   GET  /export-static/status/{jobId}           → pending | done+result | failed+error
 *   GET  /export-static/download/{jobId}         → text/html attachment; 409 if not ready
 *
 * Auth-mode behaviour:
 *   - standard:    everything runs (owner = admin, non-owner = test_user).
 *   - single-user: everyone resolves to the admin, so the non-owner tests skip;
 *                  the rest runs.
 *   - public/demo: exports are owner-only and the visitor is a temporary
 *                  non-owner — owner flows skip; the visitor's POST is refused
 *                  with 404, and the UI shows the action disabled.
 *
 * The full-flow test self-skips when the worker reports the static-runtime
 * template is missing ("static-runtime bundle not built" — see
 * depictio/serverless/producer_b.py::render_bundle_html): that is stack
 * infrastructure (only the single-user CI leg builds the template), not a
 * product bug.
 *
 * UI contract, on top of the API one: the export action is DISABLED for a
 * non-owner, never hidden (SettingsDrawer.tsx — "disable write actions, keep
 * the affordance discoverable"). Reaching that state needs a session that can
 * *view* a dashboard it does not own, which the reference seeds do not
 * provide: the Iris dashboard is owned by the bootstrap admin and its project
 * lists no viewers, so test_user gets a 403 on the document rather than a
 * disabled button. Each mode therefore builds the state its own way — a
 * throwaway project shared with test_user in standard mode, the auto-minted
 * temporary visitor in public/demo mode.
 */

import { randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { APIRequestContext } from "@playwright/test";

import type { TokenBundle } from "@fixtures/auth";
import {
  API_PREFIX,
  API_URL,
  apiLogin,
  expect,
  getAuthMode,
  test,
} from "@fixtures/auth";
import { credentials, UserType } from "@fixtures/credentials";
import { IRIS_DASHBOARD_ID } from "@fixtures/projects";

import { blockNetwork } from "../static-runtime/helpers";

const EXPORT_BASE = `${API_URL}${API_PREFIX}/serverless/export-static`;
const TIERS = ["live", "partial", "frozen", "omitted"];

/** Worker-level session cache — one login per user per worker (rate limiter).
 *  The whole bundle rather than just the token: the fixture project below has
 *  to name its members by user id, and the login response is the only source
 *  for those that cannot drift from the stack under test. */
const _sessions = new Map<UserType, TokenBundle>();

async function sessionFor(
  request: APIRequestContext,
  userType: UserType,
): Promise<TokenBundle> {
  let session = _sessions.get(userType);
  if (!session) {
    const user = credentials[userType];
    session = await apiLogin(request, user.email, user.password);
    _sessions.set(userType, session);
  }
  return session;
}

async function bearerFor(
  request: APIRequestContext,
  userType: UserType,
): Promise<{ Authorization: string }> {
  const { access_token } = await sessionFor(request, userType);
  return { Authorization: `Bearer ${access_token}` };
}

/** ObjectId-shaped id, minted client-side exactly as the viewer's own
 *  createProject / createDashboard calls do. */
function newObjectId(): string {
  return randomBytes(12).toString("hex");
}

/**
 * A dashboard the *admin* owns inside a project test_user may only view —
 * i.e. the one state the seeds cannot produce, and the only one in which the
 * viewer can render a dashboard whose export it is not allowed to run.
 *
 * Its own project rather than the shared Iris one on purpose: granting Iris a
 * viewer would write the same document project-permissions.spec.ts adds and
 * removes rows in, and the two files can run concurrently (workers: 2).
 *
 * Returns both ids; the caller must delete the project (cascades to the
 * dashboard) whatever the assertions do.
 */
async function createNonOwnedDashboard(
  request: APIRequestContext,
  adminHeaders: { Authorization: string },
  admin: TokenBundle,
  viewer: TokenBundle,
): Promise<{ projectId: string; dashboardId: string }> {
  const projectId = newObjectId();
  const dashboardId = newObjectId();
  const owners = [
    { _id: admin.user_id, email: credentials.adminUser.email, is_admin: true },
  ];

  const project = await request.post(`${API_URL}${API_PREFIX}/projects/create`, {
    headers: adminHeaders,
    data: {
      _id: projectId,
      // Unique: /projects/create refuses a duplicate name, and a failed run
      // may have left one behind.
      name: `e2e static export non-owner ${projectId}`,
      project_type: "basic",
      is_public: false,
      workflows: [],
      permissions: {
        owners,
        editors: [],
        viewers: [
          {
            _id: viewer.user_id,
            email: credentials.testUser.email,
            is_admin: false,
          },
        ],
      },
    },
  });
  expect(project.status(), "fixture project could not be created").toBe(200);
  const projectBody = (await project.json()) as { success: boolean; message?: string };
  expect(projectBody.success, `fixture project rejected: ${projectBody.message}`).toBe(
    true,
  );

  // Component-free on purpose: the export gate is about who owns the
  // dashboard, and an empty one loads without touching S3 or Delta.
  const dashboard = await request.post(
    `${API_URL}${API_PREFIX}/dashboards/save/${dashboardId}`,
    {
      headers: adminHeaders,
      data: {
        dashboard_id: dashboardId,
        version: 1,
        title: "Static export non-owner fixture",
        subtitle: "",
        icon: "mdi:view-dashboard",
        icon_color: "orange",
        icon_variant: "filled",
        workflow_system: "none",
        notes_content: "",
        permissions: { owners, editors: [], viewers: [] },
        is_public: false,
        last_saved_ts: "",
        project_id: projectId,
        is_main_tab: true,
        tab_order: 0,
      },
    },
  );
  expect(dashboard.status(), "fixture dashboard could not be created").toBe(200);

  return { projectId, dashboardId };
}

interface StatusPayload {
  job_id: string;
  status: "pending" | "done" | "failed";
  result?: {
    s3_key: string;
    bucket: string;
    size_bytes: number;
    built_at: string;
    download_url: string | null;
  } | null;
  error?: string | null;
}

test.describe("Static export (owner flows)", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(
      is_public_mode,
      "Public/demo mode: visitor is a temporary non-owner — owner-only export flows do not apply.",
    );
  });

  test("preflight returns the tier table", async ({ request }) => {
    const headers = await bearerFor(request, "adminUser");
    const res = await request.get(
      `${EXPORT_BASE}/${IRIS_DASHBOARD_ID}/preflight`,
      { headers },
    );
    expect(res.status()).toBe(200);

    const body = (await res.json()) as {
      dashboard_id: string;
      tiers: Array<{ component_id: string; tier: string }>;
      links: unknown[];
      counts: Record<string, number>;
    };
    expect(body.dashboard_id).toBe(IRIS_DASHBOARD_ID);
    expect(Array.isArray(body.tiers)).toBe(true);
    expect(body.tiers.length).toBeGreaterThan(0);
    for (const row of body.tiers) {
      expect(row.component_id).toBeTruthy();
      expect(TIERS).toContain(row.tier);
    }
    expect(Array.isArray(body.links)).toBe(true);
    const countSum = TIERS.reduce((sum, t) => sum + (body.counts[t] ?? 0), 0);
    expect(countSum).toBe(body.tiers.length);
  });

  test("non-owner cannot dispatch an export", async ({ request }) => {
    const { is_single_user_mode } = await getAuthMode();
    test.skip(
      is_single_user_mode,
      "Single-user mode: every request resolves to the admin — there is no non-owner.",
    );

    const headers = await bearerFor(request, "testUser");
    const res = await request.post(`${EXPORT_BASE}/${IRIS_DASHBOARD_ID}`, {
      headers,
    });
    // 404, not 403 — the endpoint must not confirm the dashboard exists.
    expect(res.status()).toBe(404);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.job_id).toBeUndefined();
    expect(String(body.detail)).toMatch(/not found or access denied/i);
  });

  test("full export flow: POST → poll → download → offline render", async ({
    page,
    request,
  }) => {
    // Celery build + polling budget: well past the worker's 600 s soft limit
    // is pointless, but 5 min covers a cold worker on CI runners.
    test.setTimeout(300_000);
    const headers = await bearerFor(request, "adminUser");

    // 1. Dispatch.
    const dispatch = await request.post(`${EXPORT_BASE}/${IRIS_DASHBOARD_ID}`, {
      headers,
    });
    expect(dispatch.status()).toBe(200);
    const { job_id, status: initialStatus } = (await dispatch.json()) as {
      job_id: string;
      status: string;
    };
    expect(job_id).toBeTruthy();
    expect(initialStatus).toBe("pending");

    // 2. Download before completion → 409 (unless the job improbably already
    //    finished between the two requests, in which case there is nothing to
    //    assert about the not-ready path).
    const early = await request.get(`${EXPORT_BASE}/download/${job_id}`, {
      headers,
    });
    if (early.status() !== 200) {
      expect(early.status()).toBe(409);
    }

    // 3. Poll every 2 s until the job settles.
    const deadline = Date.now() + 240_000;
    let status: StatusPayload = { job_id, status: "pending" };
    while (Date.now() < deadline) {
      const res = await request.get(`${EXPORT_BASE}/status/${job_id}`, {
        headers,
      });
      expect(res.status()).toBe(200);
      status = (await res.json()) as StatusPayload;
      if (status.status !== "pending") break;
      await new Promise((r) => setTimeout(r, 2000));
    }

    if (
      status.status === "failed" &&
      /static-runtime bundle not built/i.test(status.error ?? "")
    ) {
      // Stack infrastructure: dist-static/static.html was not built before the
      // worker started (only the single-user CI leg builds it). Not a bug.
      test.skip(true, "static template not built in this stack");
    }
    expect(status.status, `export failed: ${status.error}`).toBe("done");

    const result = status.result!;
    expect(result.s3_key).toMatch(
      new RegExp(
        `^serverless-exports/${IRIS_DASHBOARD_ID}/\\d{8}T\\d{6}Z\\.html$`,
      ),
    );
    expect(result.bucket).toBeTruthy();
    expect(result.built_at).toBeTruthy();
    expect(result.size_bytes).toBeGreaterThan(1_000_000);

    // 4. Download the bundle through the API proxy.
    const dl = await request.get(`${EXPORT_BASE}/download/${job_id}`, {
      headers,
    });
    expect(dl.status()).toBe(200);
    expect(dl.headers()["content-type"]).toContain("text/html");
    expect(dl.headers()["content-disposition"] ?? "").toContain("attachment");
    const bundle = await dl.body();
    expect(bundle.length).toBeGreaterThan(1_000_000);

    // 5. Offline render: file:// origin, every network request blocked.
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "depictio-export-"));
    const bundlePath = path.join(dir, "bundle.html");
    fs.writeFileSync(bundlePath, bundle);

    const attempts = await blockNetwork(page);
    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(String(err)));

    await page.goto(`file://${bundlePath}`);
    await page.waitForSelector(".react-grid-item", { timeout: 30_000 });
    expect(await page.locator(".react-grid-item").count()).toBeGreaterThanOrEqual(1);

    expect(
      attempts,
      `bundle attempted network requests:\n${attempts.join("\n")}`,
    ).toHaveLength(0);
    expect(pageErrors, `page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
  });

  test("export action lives in the settings drawer and is enabled for the owner", async ({
    page,
    loginAsAdmin,
  }) => {
    await loginAsAdmin();
    await page.goto(`/dashboard/${IRIS_DASHBOARD_ID}`);

    const btn = page.locator("[data-testid='export-static-btn']");

    // The action moved out of the header into the Settings drawer
    // (SettingsDrawer.tsx, "Actions" section), so nothing is on screen until
    // the drawer is opened.
    const settingsBtn = page.getByRole("button", { name: "Settings" });
    await expect(settingsBtn).toBeVisible({ timeout: 15_000 });
    await expect(btn).toHaveCount(0);

    await settingsBtn.click();
    const drawer = page.getByRole("dialog").filter({
      hasText: "Dashboard settings",
    });
    await expect(drawer).toBeVisible({ timeout: 15_000 });
    await expect(btn).toBeVisible();
    await expect(btn).toBeEnabled();

    // Light smoke only: the modal opens with the tier table and a confirm
    // action — the API test above covers the actual export job.
    // (ExportStaticModal.tsx: Mantine Modal titled "Export static dashboard",
    // confirm button data-testid="confirm-export-static-btn" — enabled only
    // once the preflight resolves, so assert visibility, not enablement.)
    await btn.click();
    // The drawer hands off to the modal instead of stacking under it
    // (App.tsx closes it in the same click handler).
    await expect(drawer).toBeHidden();
    const modal = page
      .getByRole("dialog")
      .filter({ has: page.locator("[data-testid='confirm-export-static-btn']") });
    await expect(modal).toBeVisible({ timeout: 15_000 });
    await expect(modal).toContainText(/export/i);
    await expect(
      modal.locator("[data-testid='confirm-export-static-btn']"),
    ).toBeVisible();
  });
});

test.describe("Static export (non-owner)", () => {
  test("the settings drawer shows the export action disabled, never hidden", async ({
    page,
    request,
    loginAsUser,
  }) => {
    const { is_single_user_mode, is_public_mode } = await getAuthMode();
    test.skip(
      is_single_user_mode,
      "Single-user mode: every request resolves to the admin — there is no non-owner.",
    );
    test.skip(
      is_public_mode,
      "Public/demo mode: the temporary visitor covers this without a fixture project (below).",
    );

    const adminHeaders = await bearerFor(request, "adminUser");
    const admin = await sessionFor(request, "adminUser");
    const viewer = await sessionFor(request, "testUser");
    const fixture = await createNonOwnedDashboard(request, adminHeaders, admin, viewer);

    try {
      await loginAsUser();
      await page.goto(`/dashboard/${fixture.dashboardId}`);

      // The empty state is what proves the non-owner actually loaded the
      // dashboard: the header (Settings button included) renders over the
      // error branch too, so asserting on the button alone would also pass on
      // a 403.
      await expect(page.getByText("This dashboard is empty")).toBeVisible({
        timeout: 20_000,
      });
      // Same gate, one affordance over: editing is the owner's, so it is gone
      // from the empty state for this user.
      await expect(page.getByRole("link", { name: /start editing/i })).toHaveCount(0);

      await page.getByRole("button", { name: "Settings" }).click();
      const drawer = page.getByRole("dialog").filter({
        hasText: "Dashboard settings",
      });
      await expect(drawer).toBeVisible({ timeout: 15_000 });

      const btn = page.locator("[data-testid='export-static-btn']");
      // Present and readable, but inert — and the reason is on screen, not in
      // a tooltip a disabled button would never fire.
      await expect(btn).toBeVisible();
      await expect(btn).toBeDisabled();
      await expect(drawer).toContainText(/only export dashboards you own/i);
    } finally {
      // Cascading delete — takes the fixture dashboard with it.
      await request.delete(
        `${API_URL}${API_PREFIX}/projects/delete?project_id=${fixture.projectId}`,
        { headers: adminHeaders },
      );
    }
  });
});

test.describe("Static export in public/demo mode", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(!is_public_mode, "Not running in public/demo mode.");
  });

  test("temporary user sees the export action disabled, never hidden", async ({
    page,
  }) => {
    // No fixture needed here: the reference dashboards are public in this mode
    // and the auto-minted visitor owns none of them.
    await page.goto(`/dashboard/${IRIS_DASHBOARD_ID}`);

    const grid = page.locator(".react-grid-item").first();
    // App.tsx renders the document-fetch failure as bare red text; match its
    // wording (404 / 403 detail) rather than a loose "failed", which the
    // dashboard's own content could contain.
    const failed = page.getByText(/not found|have permission/i).first();
    await expect(grid.or(failed)).toBeVisible({ timeout: 30_000 });
    test.skip(
      await failed.isVisible(),
      "Iris reference dashboard not seeded in this stack.",
    );

    await page.getByRole("button", { name: "Settings" }).click();
    const drawer = page.getByRole("dialog").filter({
      hasText: "Dashboard settings",
    });
    await expect(drawer).toBeVisible({ timeout: 15_000 });

    const btn = page.locator("[data-testid='export-static-btn']");
    await expect(btn).toBeVisible();
    await expect(btn).toBeDisabled();
    await expect(drawer).toContainText(/only export dashboards you own/i);
  });

  test("temporary user cannot dispatch an export (404)", async ({
    page,
    request,
  }) => {
    // The SPA auto-mints a temporary session at bootstrap; pull its token out
    // of localStorage (same pattern as public-mode.spec.ts).
    await page.goto("/dashboards");
    await expect
      .poll(async () =>
        page.evaluate(() => {
          try {
            const raw = window.localStorage.getItem("local-store");
            return raw ? ((JSON.parse(raw).access_token as string) ?? "") : "";
          } catch {
            return "";
          }
        }),
      )
      .not.toBe("");
    const token = await page.evaluate(
      () =>
        JSON.parse(window.localStorage.getItem("local-store")!)
          .access_token as string,
    );

    const res = await request.post(`${EXPORT_BASE}/${IRIS_DASHBOARD_ID}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.status()).toBe(404);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.job_id).toBeUndefined();
  });
});
