/**
 * Dashboard → Quarto export (settings → Export → modal → download).
 *
 * Runs against the seeded Palmer Penguins dashboard. Checks the preflight
 * (every tile gets a verdict), the download (a `.qmd` that opens on its YAML
 * front matter), and the preflight API contract directly.
 */

import { API_PREFIX, API_URL, apiOnlyToken, expect, test } from "@fixtures/auth";

const PENGUINS_DASHBOARD_ID = "6824cb3b89d2b72169309738";

test.describe("Notebook export", () => {
  test("exports the penguins dashboard as a Quarto document from the settings", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto(`/dashboard/${PENGUINS_DASHBOARD_ID}`);
    await expect(page.locator("[data-testid='dashboard-content']")).toBeAttached({
      timeout: 30_000,
    });

    // `exact`: every tile carries its own "… settings" button.
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await page.locator("[data-testid='settings-nav-export']").click();
    const exportButton = page.locator("[data-testid='export-notebook']");
    await expect(exportButton).toBeVisible({ timeout: 15_000 });
    await exportButton.click();

    const modal = page.locator("[data-testid='notebook-export-modal']");
    await expect(modal).toBeVisible();
    // Preflight: every tile has a verdict, and none of penguins' is left out.
    await expect(modal.locator("[data-testid='notebook-export-counts']")).toBeVisible({
      timeout: 30_000,
    });
    const codeRows = modal.locator("[data-testid='notebook-export-row-code']");
    expect(await codeRows.count()).toBeGreaterThan(5);
    expect(await modal.locator("[data-testid='notebook-export-row-omitted']").count()).toBe(0);

    const downloadPromise = page.waitForEvent("download");
    await modal.locator("[data-testid='notebook-export-download']").click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.qmd$/);
    const path = await download.path();
    expect(path).not.toBeNull();
    const fs = await import("node:fs");
    const content = fs.readFileSync(path!, "utf8");
    expect(content.startsWith("---\ntitle: ")).toBe(true);
    expect(content).toContain("jupyter: python3");
    expect(content).toContain("```{python}");
    expect(content).toContain("client = DepictioClient()");
    // The title lives in the front matter once; the body no longer repeats it.
    expect(content).toContain("title: Penguins Species Analysis");
    expect(content).not.toContain("\n# Penguins Species Analysis");
    await expect(modal.locator("[data-testid='notebook-export-done']")).toBeVisible();
  });

  test("preflight API classifies every tile", async ({ request }) => {
    const { access_token } = await apiOnlyToken(request, "adminUser");
    const res = await request.post(
      `${API_URL}${API_PREFIX}/dashboards/notebook_export/${PENGUINS_DASHBOARD_ID}/preflight`,
      {
        headers: { Authorization: `Bearer ${access_token}` },
        data: {
          state: { version: 1, context: { dashboard_id: PENGUINS_DASHBOARD_ID } },
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
