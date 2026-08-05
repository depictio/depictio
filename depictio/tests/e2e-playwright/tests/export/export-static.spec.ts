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
 *   - single-user: everyone resolves to the admin, so the non-owner test skips;
 *                  the rest runs.
 *   - public/demo: exports are owner-only and the visitor is a temporary
 *                  non-owner — owner flows skip; one cheap test asserts the
 *                  temp user's POST is refused with 404.
 *
 * The full-flow test self-skips when the worker reports the static-runtime
 * template is missing ("static-runtime bundle not built" — see
 * depictio/serverless/producer_b.py::render_bundle_html): that is stack
 * infrastructure (only the single-user CI leg builds the template), not a
 * product bug.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { APIRequestContext } from "@playwright/test";

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

/** Worker-level token cache — one login per user per worker (rate limiter). */
const _tokens = new Map<UserType, string>();

async function bearerFor(
  request: APIRequestContext,
  userType: UserType,
): Promise<{ Authorization: string }> {
  let token = _tokens.get(userType);
  if (!token) {
    const user = credentials[userType];
    token = (await apiLogin(request, user.email, user.password)).access_token;
    _tokens.set(userType, token);
  }
  return { Authorization: `Bearer ${token}` };
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

  test("export button visible for owner", async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    await page.goto(`/dashboard/${IRIS_DASHBOARD_ID}`);

    const btn = page.locator("[data-testid='export-static-btn']");
    await expect(btn).toBeVisible({ timeout: 15_000 });
    await expect(btn).toBeEnabled();

    // Light smoke only: the modal opens with the tier table and a confirm
    // action — the API test above covers the actual export job.
    // (ExportStaticModal.tsx: Mantine Modal titled "Export static dashboard",
    // confirm button data-testid="confirm-export-static-btn" — enabled only
    // once the preflight resolves, so assert visibility, not enablement.)
    await btn.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog).toContainText(/export/i);
    await expect(
      dialog.locator("[data-testid='confirm-export-static-btn']"),
    ).toBeVisible();
  });
});

test.describe("Static export in public/demo mode", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(!is_public_mode, "Not running in public/demo mode.");
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
