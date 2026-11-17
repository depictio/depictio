/**
 * "Map coordinates…" on a table's page: mark the latitude/longitude columns
 * that make the table a Map source, then remove them again.
 *
 * A real table is uploaded to the seeded Iris project through the API (no
 * marking), driven through the window, and deleted afterwards. Runs for
 * admins; skipped in public mode and on stacks without the Iris seed.
 */

import { test, expect, getAuthMode, loginAsTestUserWithToken, apiOnlyToken, API_URL, API_PREFIX } from "@fixtures/auth";
import { IRIS_PROJECT_ID } from "@fixtures/projects";

const CSV = ["site,latitude,longitude,depth", "a,48.14,11.58,3", "b,52.52,13.40,5", "c,45.76,4.84,2"].join("\n");

test.describe("Table map coordinates", () => {
  let dcId: string | null = null;

  test.beforeEach(async ({ page, request }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Marking coordinates needs a project owner account.");
    const { access_token } = await apiOnlyToken(request, "adminUser");
    const res = await request.post(`${API_URL}${API_PREFIX}/datacollections/create_from_upload`, {
      headers: { Authorization: `Bearer ${access_token}` },
      multipart: {
        project_id: IRIS_PROJECT_ID,
        name: `sites_${Date.now()}`,
        description: "",
        data_type: "table",
        file_format: "csv",
        separator: ",",
        compression: "none",
        has_header: "true",
        file: { name: "sites.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) },
      },
    });
    expect(res.ok(), await res.text()).toBeTruthy();
    dcId = ((await res.json()) as { data_collection_id?: string }).data_collection_id ?? null;
    expect(dcId).toBeTruthy();
    await loginAsTestUserWithToken(page, request, "adminUser");
  });

  test.afterEach(async ({ request }) => {
    if (!dcId) return;
    const { access_token } = await apiOnlyToken(request, "adminUser");
    await request.delete(`${API_URL}${API_PREFIX}/datacollections/${dcId}`, {
      headers: { Authorization: `Bearer ${access_token}` },
    });
    dcId = null;
  });

  test("detects the columns, saves them and removes them", async ({ page }) => {
    await page.goto(`/projects/${IRIS_PROJECT_ID}?table=${dcId}&no-walkthrough=1`);
    const viewer = page.getByTestId("dc-viewer");
    await expect(viewer.getByText("Geomap")).toHaveCount(0, { timeout: 20_000 });

    // Suggested, not applied: the review button opens the window.
    await expect(page.getByTestId("table-coordinates-suggestion")).toContainText("latitude");
    await page.getByTestId("table-coordinates-suggestion-open").click();
    const modal = page.getByTestId("table-coordinates-modal");
    // Detected from the column names.
    await expect(modal.getByTestId("table-coordinates-lat")).toHaveValue("latitude");
    await expect(modal.getByTestId("table-coordinates-lon")).toHaveValue("longitude");
    await expect(modal.getByTestId("table-coordinates-preview").getByText("Showing 3 points")).toBeVisible({
      timeout: 20_000,
    });
    await expect(modal.getByTestId("table-coordinates-remove")).toHaveCount(0);

    await modal.getByTestId("table-coordinates-save").click();
    await expect(page.getByTestId("table-coordinates-lat")).toHaveCount(0);
    await expect(viewer.getByText("Geomap")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("dc-section-preview")).toBeVisible();
    await expect(page.getByTestId("table-coordinates-suggestion")).toHaveCount(0);

    await page.getByTestId("table-coordinates-open").click();
    await expect(page.getByTestId("table-coordinates-lat")).toHaveValue("latitude");
    await page.getByTestId("table-coordinates-remove").click();
    await expect(page.getByTestId("table-coordinates-lat")).toHaveCount(0);
    await expect(viewer.getByText("Geomap")).toHaveCount(0, { timeout: 20_000 });
  });

  for (const keep of [true, false]) {
  test(`Add data flags the coordinates of a dropped CSV (${keep ? "kept" : "unticked"})`, async ({ page, request }) => {
    await page.goto(`/projects/${IRIS_PROJECT_ID}?no-walkthrough=1`);
    await page.getByTestId("add-data-btn").first().click();
    const tag = `stations_${Date.now()}`;
    await page
      .getByTestId("files-input")
      .setInputFiles({ name: `${tag}.csv`, mimeType: "text/csv", buffer: Buffer.from(CSV) });

    // Flagged as soon as the file is identified, ticked by default.
    const flag = page.getByTestId("files-item-0-coordinates");
    await expect(flag).toBeChecked({ timeout: 10_000 });
    await expect(page.getByTestId("files-item-0")).toContainText("latitude");
    if (!keep) await flag.uncheck();
    await page.getByTestId("add-data-submit").click();
    await expect(page.getByTestId("add-data-file-result-0")).toHaveAttribute("data-status", "created", {
      timeout: 30_000,
    });

    // Clean up the table this test added through the UI.
    const { access_token } = await apiOnlyToken(request, "adminUser");
    const res = await request.get(
      `${API_URL}${API_PREFIX}/projects/get/from_id?project_id=${IRIS_PROJECT_ID}`,
      { headers: { Authorization: `Bearer ${access_token}` } },
    );
    const body = (await res.json()) as { project?: Record<string, unknown> } & Record<string, unknown>;
    const project = (body.project ?? body) as { workflows: Array<{ data_collections: Array<Record<string, unknown>> }> };
    const added = project.workflows
      .flatMap((w) => w.data_collections)
      .find((dc) => String(dc.data_collection_tag).startsWith(tag));
    const props = (added?.config as { dc_specific_properties?: Record<string, unknown> } | undefined)
      ?.dc_specific_properties;
    await request.delete(`${API_URL}${API_PREFIX}/datacollections/${added?._id ?? added?.id}`, {
      headers: { Authorization: `Bearer ${access_token}` },
    });
    if (keep) expect(props).toMatchObject({ lat_column: "latitude", lon_column: "longitude" });
    else expect(props?.lat_column).toBeUndefined();
  });
  }

  test("shows the server's refusal for a text column", async ({ page }) => {
    await page.goto(`/projects/${IRIS_PROJECT_ID}?table=${dcId}&no-walkthrough=1`);
    await page.getByTestId("table-coordinates-open").click();
    const lat = page.getByTestId("table-coordinates-lat");
    await lat.click();
    await page.getByRole("option", { name: "site", exact: true }).click();
    await page.getByTestId("table-coordinates-save").click();
    await expect(page.getByTestId("table-coordinates-error")).toContainText("not numbers");
  });
});
