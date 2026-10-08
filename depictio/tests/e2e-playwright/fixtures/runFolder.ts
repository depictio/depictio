/**
 * Shared stubs for the "From a run folder" specs (create-from-run and the
 * folder browser).
 *
 * The session stays real; everything the run tab reads about folders and
 * templates is stubbed, so the specs hold the same folders, the same
 * catalog and the same detections whatever the deployment ships, and need no
 * S3 bucket nor a folder on the runner's disk.
 */

import { Page, Route } from "@playwright/test";

export const AMPLISEQ = "Ampliseq Microbial Community Analysis";

const AMPLISEQ_VARIABLES = [
  {
    name: "DATA_ROOT",
    description: "Root directory containing ampliseq output",
    required: true,
    default: null,
  },
  {
    name: "GROUP_COL",
    description: "Metadata column for grouping",
    required: false,
    default: null,
  },
];

function template(templateId: string, name: string, extra: Record<string, unknown> = {}) {
  const segments = templateId.split("/");
  return {
    template_id: templateId,
    name,
    description: `${name} template`,
    version: "1.0.0",
    manifest_capable: false,
    variables: [],
    dashboards: ["dashboards/base.yaml"],
    run_folder_capable: true,
    source: segments[0],
    pipeline: segments.slice(0, 2).join("/"),
    engine: "nextflow",
    ...extra,
  };
}

/** Three versions of one pipeline (which the picker must show as ONE entry),
 *  another nf-core pipeline, a generic run-folder template, and a
 *  manifest-only one the run tab must leave out. */
export const TEMPLATES = {
  templates: [
    template("nf-core/ampliseq/2.14.0", AMPLISEQ, { variables: AMPLISEQ_VARIABLES }),
    template("nf-core/ampliseq/2.16.0", AMPLISEQ, { variables: AMPLISEQ_VARIABLES }),
    template("nf-core/ampliseq/2.18.0", AMPLISEQ, { variables: AMPLISEQ_VARIABLES }),
    template("nf-core/rnaseq/3.26.0", "RNA-seq Expression Analysis"),
    template("generic/folder-tables/1", "Folder Tables", { engine: null }),
    template("generic/manifest-tables/1", "Manifest Tables", {
      manifest_capable: true,
      run_folder_capable: false,
      engine: null,
    }),
  ],
};

export async function mockTemplates(page: Page): Promise<void> {
  await page.route("**/api/v1/projects/templates**", (route) =>
    route.fulfill({ json: TEMPLATES }),
  );
}

/** Pass the real `/auth/me/optional` answer through with the run-folder
 *  capability flags forced, and the first-run walkthrough off (its backdrop
 *  would cover the page on a stack that enables it). */
export async function setRunFolderFlags(
  page: Page,
  flags: { local: boolean; remote: boolean },
): Promise<void> {
  await page.route("**/api/v1/auth/me/optional**", async (route: Route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown> | null;
    await route.fulfill({
      response,
      json: {
        ...(body ?? {}),
        local_data_roots_enabled: flags.local,
        remote_browse_enabled: flags.remote,
        walkthrough_disabled: true,
      },
    });
  });
}

/** What `folder_inspect` / `from_run` say they recognised. */
export function detected(overrides: Record<string, unknown> = {}) {
  return {
    template_id: "nf-core/ampliseq/2.16.0",
    template_version: "2.16.0",
    pipeline: "nf-core/ampliseq",
    version: "2.16.0",
    engine: "nextflow",
    match: "exact",
    ...overrides,
  };
}

/** A `folder_inspect` answer for `location`. */
export function inspection(location: string, overrides: Record<string, unknown> = {}) {
  const name = location.replace(/\/+$/, "").split("/").pop() ?? location;
  return {
    location,
    source: location.startsWith("s3://") ? "s3" : "local",
    name,
    looks_like_run: false,
    markers: [],
    folders: { count: 0, names: [] },
    files: { count: 0, names: [] },
    truncated: false,
    detected: null,
    ...overrides,
  };
}

export type StubAnswer = { status?: number; json: unknown; delayMs?: number };

/** Answer a GET by one query parameter: `answers[value]` (`""` when the
 *  parameter is absent), else `fallback`, else a 404. Returns the values
 *  asked for, in order. */
export async function stubByParam(
  page: Page,
  urlPattern: string,
  param: string,
  answers: Record<string, StubAnswer>,
  fallback?: (value: string) => StubAnswer | null,
): Promise<string[]> {
  const asked: string[] = [];
  await page.route(urlPattern, async (route: Route) => {
    const value = new URL(route.request().url()).searchParams.get(param) ?? "";
    asked.push(value);
    const answer = answers[value] ?? fallback?.(value) ?? {
      status: 404,
      json: { detail: "This folder does not exist.", code: "local_path_missing" },
    };
    if (answer.delayMs) await new Promise((resolve) => setTimeout(resolve, answer.delayMs));
    try {
      await route.fulfill({ status: answer.status ?? 200, json: answer.json });
    } catch {
      // The page cancelled the request meanwhile (a newer selection).
    }
  });
  return asked;
}

/** Open /projects, launch the create modal and switch to the run tab. */
export async function openRunTab(page: Page): Promise<void> {
  await page.goto("/projects");
  await page.locator("[data-tour-id='projects-create']").click();
  await page.getByRole("tab", { name: "From a run folder" }).click();
}
