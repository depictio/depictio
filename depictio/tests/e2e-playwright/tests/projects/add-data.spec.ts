/**
 * The project page's "Add data" menu (AddDataButton): its items, the
 * "From a folder or bucket" dialog and the "Add a run" dialog.
 *
 * The session and the seeded Iris project are real. What decides the menu
 * (the project's workflows and `template_origin`) is patched into the
 * `projects/get/from_id` answer, and both POST routes the dialogs call
 * (`add_tables_from_folder`, `attach_run`) are stubbed, so no folder, bucket
 * or pipeline run is needed. Runs for admins; skipped in public mode and on
 * stacks without the Iris seed.
 */

import { Page, Route } from "@playwright/test";
import { test, expect, getAuthMode, loginAsTestUserWithToken } from "@fixtures/auth";
import { IRIS_PROJECT_ID } from "@fixtures/projects";
import { setRunFolderFlags } from "@fixtures/runFolder";

const PROJECT_URL = `/projects/${IRIS_PROJECT_ID}`;
const FOLDER = "s3://lab-bucket/survey/";

/** Make the project page read the project as a pipeline project (or not). */
async function shapeProject(page: Page, pipeline: boolean): Promise<void> {
  await page.route("**/projects/get/from_id**", async (route: Route) => {
    const response = await route.fetch();
    const body = (await response.json()) as { project: Record<string, unknown> };
    body.project = {
      ...body.project,
      layout: null,
      workflows: pipeline
        ? [
            {
              name: "rnaseq",
              engine: { name: "nextflow", version: "23.10" },
              data_collections: [],
              runs: { run_01: {} },
            },
          ]
        : [],
      template_origin: pipeline
        ? { template_id: "nf-core/rnaseq/3.14.0", template_version: "3.14.0" }
        : null,
    };
    await route.fulfill({ response, json: body });
  });
}

async function openModal(page: Page): Promise<void> {
  const button = page.getByTestId("add-data-btn").first();
  await expect(button).toBeEnabled({ timeout: 20_000 });
  await button.click();
}

test.describe("Add data", () => {
  test.beforeEach(async ({ page, request }) => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "Adding data needs a project owner account.");
    await loginAsTestUserWithToken(page, request, "adminUser");
    await setRunFolderFlags(page, { local: false, remote: false });
  });

  test("offers files and a folder on one screen, whatever the project", async ({ page }) => {
    await shapeProject(page, false);
    await page.goto(PROJECT_URL);
    await openModal(page);
    await expect(page.getByTestId("files-dropzone")).toBeVisible();
    await expect(page.getByTestId("add-data-location-input")).toBeVisible();
    await expect(page.getByTestId("add-data-submit")).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByTestId("add-data-reason")).toContainText("Drop files");
  });

  test("folder dialog disables tables already in the project and keeps results until Done", async ({ page }) => {
    await shapeProject(page, false);
    await page.route("**/projects/*/add_tables_from_folder", async (route: Route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const base = { location: FOLDER, source: "s3", truncated: false };
      if (body.dry_run) {
        await route.fulfill({
          json: {
            ...base,
            created: [],
            dry_run: true,
            files: [
              { path: "samples.csv", name: "samples", format: "csv", size: 2048, table: true, reason: null, compression: null, existing: { data_collection_id: "dc0", data_collection_tag: "samples" } },
              { path: "new.csv", name: "new", format: "csv", size: 1024, table: true, reason: null, compression: null, existing: null },
            ],
          },
        });
        return;
      }
      await route.fulfill({
        json: {
          ...base,
          dry_run: false,
          files: [],
          created: [
            { path: "new.csv", data_collection_id: "dc1", data_collection_tag: "new", status: "ingested", error: null },
          ],
        },
      });
    });
    await page.goto(PROJECT_URL);
    await openModal(page);
    await page.getByTestId("add-data-location-input").fill(FOLDER);
    await expect(page.getByTestId("folder-tables-file-samples.csv")).toBeDisabled({ timeout: 10_000 });
    await expect(page.getByTestId("add-data-submit")).toHaveText("Add 1 table");
    await page.getByTestId("add-data-submit").click();
    await expect(page.getByTestId("folder-tables-results")).toBeVisible();
    await page.getByTestId("add-data-done").click();
    await expect(page.getByTestId("add-data-modal")).toHaveCount(0);
  });

  test("folder dialog lists the files and sends the ticked paths", async ({ page }) => {
    await shapeProject(page, false);
    let sent: Record<string, unknown> | null = null;
    await page.route("**/projects/*/add_tables_from_folder", async (route: Route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      if (body.dry_run) {
        await route.fulfill({
          json: {
            location: FOLDER,
            source: "s3",
            truncated: false,
            created: [],
            dry_run: true,
            files: [
              { path: "samples.csv", name: "samples", format: "csv", size: 2048, table: true, reason: null, compression: null },
              { path: "measurements.tsv", name: "measurements", format: "tsv", size: 4096, table: true, reason: null, compression: null },
              { path: "notes.txt", name: "notes", format: null, size: 12, table: false, reason: "not a table", compression: null },
            ],
          },
        });
        return;
      }
      sent = body;
      await route.fulfill({
        json: {
          location: FOLDER,
          source: "s3",
          truncated: false,
          dry_run: false,
          files: [],
          created: [
            { path: "measurements.tsv", data_collection_id: "dc1", data_collection_tag: "measurements", status: "ingested", error: null },
          ],
        },
      });
    });

    await page.goto(PROJECT_URL);
    await openModal(page);
    await page.getByTestId("add-data-location-input").fill(FOLDER);

    const samples = page.getByTestId("folder-tables-file-samples.csv");
    await expect(samples).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("folder-tables-file-notes.txt")).toBeDisabled();
    await expect(page.getByTestId("add-data-submit")).toHaveText("Add 2 tables");

    // Untick one table: the button follows and only the other path is sent.
    await samples.uncheck();
    await expect(page.getByTestId("add-data-submit")).toHaveText("Add 1 table");
    await page.getByTestId("add-data-submit").click();

    await expect(page.getByTestId("folder-tables-result-measurements.tsv")).toHaveAttribute(
      "data-status",
      "ingested",
    );
    expect((sent as Record<string, unknown> | null)?.files).toEqual(["measurements.tsv"]);
    expect((sent as Record<string, unknown> | null)?.dry_run).toBe(false);
  });

  test("run dialog shows a cannot_attach refusal as the disabled reason", async ({ page }) => {
    await shapeProject(page, true);
    const message = "This folder holds no collection of this project's pipeline.";
    await page.route("**/projects/*/attach_run", (route: Route) =>
      route.fulfill({ status: 422, json: { detail: message, code: "cannot_attach" } }),
    );
    // Not a run, and no table to offer instead: the refusal is the answer.
    await page.route("**/projects/*/add_tables_from_folder", (route: Route) =>
      route.fulfill({
        json: { location: "s3://lab-bucket/rnaseq/run_13/", source: "s3", truncated: false, created: [], dry_run: true, files: [] },
      }),
    );

    await page.goto(PROJECT_URL);
    await openModal(page);
    await page.getByTestId("add-data-location-input").fill("s3://lab-bucket/rnaseq/run_13/");

    await expect(page.getByTestId("attach-run-refusal")).toContainText(message, { timeout: 10_000 });
    await expect(page.getByTestId("attach-run-refusal")).toHaveAttribute("data-code", "cannot_attach");
    // Shown once: the alert carries the message, not the line under the button.
    await expect(page.getByTestId("add-data-reason")).toHaveCount(0);
    await expect(page.getByTestId("use-own-credentials")).toBeVisible();
    await expect(page.getByTestId("run-private-bucket-toggle")).toHaveCount(0);
    await expect(page.getByTestId("add-data-submit")).toHaveAttribute("aria-disabled", "true");
  });
});
