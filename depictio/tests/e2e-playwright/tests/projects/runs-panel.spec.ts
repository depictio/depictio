/**
 * The project page's Runs tab: an unfolded run lists its files, says what the
 * picked scan did to each (and, for a changed file, what changed), narrows to
 * what that scan changed, and opens a file onto its first rows.
 *
 * The session and the seeded Iris project are real. The project is read as a
 * pipeline project (patched `projects/get/from_id`), and the runs, their
 * files and the file preview are stubbed, so no run folder is needed.
 */

import { Page, Route } from "@playwright/test";
import { test, expect, getAuthMode, loginAsTestUserWithToken } from "@fixtures/auth";
import { IRIS_PROJECT_ID } from "@fixtures/projects";

const PROJECT_URL = `/projects/${IRIS_PROJECT_ID}`;
const FOLDER = "/data/runs/run_02";

const RUN = {
  run_tag: "run_02",
  workflow: "nf-core/ampliseq",
  run_location: FOLDER,
  folder_created: "2026-11-01T10:00:00",
  folder_modified: "2026-11-02T10:00:00",
  registered: "2026-11-02T11:00:00",
  run_hash: null,
  status: "ok",
  files: 2,
  dc_files: { multiqc_data: 1, samplesheet: 1, asv_table: 0 },
  scans: [
    { scan_time: "2026-11-02T11:00:00", files_total: 1, files_new: 1, files_updated: 0, files_skipped: 0, files_failed: 0 },
    { scan_time: "2026-11-05T09:00:00", files_total: 2, files_new: 1, files_updated: 1, files_skipped: 0, files_failed: 0 },
  ],
};

const file = (id: string, dc_tag: string, location: string, added_in: number, extra: Record<string, unknown> = {}) => ({
  id,
  dc_id: `dc-${dc_tag}`,
  dc_tag,
  filename: location.split("/").pop(),
  location,
  size: 2048,
  modified: "2026-11-05T08:00:00",
  registered: "2026-11-02T11:00:00",
  added_in,
  changed_in: [],
  failed_in: [],
  changes: [],
  report_change: null,
  ...extra,
});

const FILES = {
  run_tag: "run_02",
  scans: [
    { scan_time: "2026-11-02T11:00:00", new: 1, changed: 0, failed: 0 },
    { scan_time: "2026-11-05T09:00:00", new: 1, changed: 1, failed: 0 },
  ],
  files: [
    file("f1", "multiqc_data", `${FOLDER}/multiqc/multiqc_data/multiqc.parquet`, 0, {
      changed_in: [1],
      changes: [{ scan: 1, size: [1024, 2048], modified: ["2026-11-01T08:00:00", "2026-11-05T08:00:00"] }],
      report_change: { samples_added: ["S3"], samples_removed: [], modules_added: [], modules_removed: ["fastp"] },
    }),
    file("f2", "samplesheet", `${FOLDER}/pipeline_info/samplesheet.valid.csv`, 1),
  ],
  truncated: false,
};

async function stubRuns(page: Page): Promise<void> {
  await page.route("**/projects/get/from_id**", async (route: Route) => {
    const response = await route.fetch();
    const body = (await response.json()) as { project: Record<string, unknown> };
    body.project = {
      ...body.project,
      layout: null,
      workflows: [
        {
          name: "ampliseq",
          engine: { name: "nextflow", version: "24.04" },
          data_collections: [],
          runs: { run_02: {} },
        },
      ],
    };
    await route.fulfill({ response, json: body });
  });
  await page.route(`**/projects/project-runs/${IRIS_PROJECT_ID}/files**`, (route) =>
    route.fulfill({ json: FILES }),
  );
  await page.route(`**/projects/project-runs/${IRIS_PROJECT_ID}`, (route) =>
    route.fulfill({ json: { runs: [RUN] } }),
  );
  await page.route("**/projects/run_file_preview", (route) =>
    route.fulfill({
      json: {
        location: FILES.files[1].location,
        name: "samplesheet.valid.csv",
        size: 2048,
        format: "table",
        columns: ["sample", "fastq_1"],
        rows: [["S1", "S1_R1.fastq.gz"]],
        columns_total: 2,
        rows_total: 1,
        text: null,
        truncated: false,
      },
    }),
  );
}

test.describe("Runs tab", () => {
  test.beforeEach(async ({ page, request }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "The Runs tab is read as the project owner.");
    await loginAsTestUserWithToken(page, request, "adminUser");
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("an unfolded run lists its files and what the picked scan did to them", async ({ page }) => {
    await stubRuns(page);
    await page.goto(`${PROJECT_URL}?no-walkthrough=1`);
    await page.getByTestId("project-tab-runs").click();
    await page.getByTestId("run-row-run_02").click();

    const details = page.getByTestId("run-details-run_02");
    await expect(details).toBeVisible();
    // The latest scan is picked, narrowed to what it changed.
    await expect(details.getByTestId("run-scan").first()).toHaveAttribute("data-active", "true");
    const files = details.getByTestId("run-file");
    await expect(files).toHaveCount(2);
    const report = details.locator('[data-testid="run-file"][data-filename="multiqc.parquet"]');
    await expect(report).toHaveAttribute("data-state", "changed");
    // What changed: size before → after, and what the report gained or lost.
    const change = report.getByTestId("run-file-change");
    await expect(change).toContainText("1.0 KB → 2.0 KB");
    await expect(change).toContainText("+1 sample (S3)");
    await expect(change).toContainText("−1 module (fastp)");
    await expect(
      details.locator('[data-testid="run-file"][data-filename="samplesheet.valid.csv"]'),
    ).toHaveAttribute("data-state", "new");
    // A collection that found nothing in the run still shows, first.
    await expect(details.getByTestId("run-collection-asv_table")).toContainText("Nothing found");

    // The first scan brought only the report; the sample sheet came later.
    await details.getByTestId("run-scan").nth(1).click();
    await expect(files).toHaveCount(1);
    await expect(files.first()).toHaveAttribute("data-state", "new");
    await expect(files.first()).toHaveAttribute("data-filename", "multiqc.parquet");
    await expect(files.first().getByTestId("run-file-change")).toHaveCount(0);

    // Back on the latest scan, a file opens onto its first rows.
    await details.getByTestId("run-scan").first().click();
    const sheet = details.locator('[data-testid="run-file"][data-filename="samplesheet.valid.csv"]');
    await sheet.getByTestId("run-file-preview-toggle").click();
    await expect(sheet.getByTestId("file-preview-table")).toContainText("S1_R1.fastq.gz");
  });
});
