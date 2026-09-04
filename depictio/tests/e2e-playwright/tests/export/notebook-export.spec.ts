/**
 * Dashboard → notebook export (settings drawer → Export → modal → download).
 *
 * Runs against the seeded Palmer Penguins dashboard. Checks the preflight
 * (every tile gets a verdict), the marimo download (a Python file starting
 * with `import marimo`), and the preflight API contract directly.
 */

import { test, expect } from "@fixtures/auth";

const PENGUINS_DASHBOARD_ID = "6824cb3b89d2b72169309738";

test.describe("Notebook export", () => {
  test("exports the penguins dashboard as a marimo notebook from the drawer", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto(`/dashboard/${PENGUINS_DASHBOARD_ID}`);
    await expect(page.locator("[data-testid='dashboard-content']")).toBeAttached({
      timeout: 30_000,
    });

    await page.getByRole("button", { name: "Settings" }).click();
    const exportButton = page.locator("[data-testid='export-notebook']");
    await expect(exportButton).toBeVisible({ timeout: 15_000 });
    await exportButton.click();

    const modal = page.locator("[data-testid='notebook-export-modal']");
    await expect(modal).toBeVisible();
    // Preflight: every tile has a verdict; penguins is fully expressible as code.
    await expect(modal.locator("[data-testid='notebook-export-counts']")).toBeVisible({
      timeout: 30_000,
    });
    const codeRows = modal.locator("[data-testid='notebook-export-row-code']");
    expect(await codeRows.count()).toBeGreaterThan(5);
    expect(await modal.locator("[data-testid='notebook-export-row-omitted']").count()).toBe(0);

    const downloadPromise = page.waitForEvent("download");
    await modal.locator("[data-testid='notebook-export-download']").click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.py$/);
    const path = await download.path();
    expect(path).not.toBeNull();
    const fs = await import("node:fs");
    const content = fs.readFileSync(path!, "utf8");
    expect(content.startsWith("import marimo")).toBe(true);
    expect(content).toContain("client = DepictioClient()");
    expect(content).toContain("# Penguins Species Analysis");
    await expect(modal.locator("[data-testid='notebook-export-done']")).toBeVisible();
  });

  test("preflight API classifies every tile", async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    const token = await page.evaluate(() => {
      const raw = window.localStorage.getItem("local-store");
      return raw ? (JSON.parse(raw).access_token as string) : null;
    });
    expect(token).not.toBeNull();
    const res = await page.request.post(
      `/depictio/api/v1/dashboards/notebook_export/${PENGUINS_DASHBOARD_ID}/preflight`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          state: { version: 1, context: { dashboard_id: PENGUINS_DASHBOARD_ID } },
          format: "marimo",
        },
      },
    );
    expect(res.ok()).toBe(true);
    const body = await res.json();
    expect(body.components.length).toBeGreaterThan(10);
    for (const c of body.components) {
      expect(["code", "api", "omitted"]).toContain(c.status);
    }
    expect(body.dcs.length).toBeGreaterThan(0);
    expect(body.stages).toEqual([]);
  });
});
