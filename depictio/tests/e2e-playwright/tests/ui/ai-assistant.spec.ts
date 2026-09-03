/**
 * AI assistant surfaces, fully deterministic: every /ai/* call and the
 * status feature flags are intercepted, so these tests run with
 * DEPICTIO_AI_ENABLED=false and no LLM key in CI.
 *
 * Covered:
 *  1. Feature off: zero AI affordances anywhere, including no
 *     "Describe with AI" tile on the Add-component chooser.
 *  2. Feature on: analyze panel answers and applying the plan surfaces
 *     the "AI filters" chip (expr-only filter injection).
 *  3. "Describe with AI" is the third tile on the Add-component chooser and
 *     is prompt first: a two-step stepper (Describe, Component Design) with
 *     no Component Type grid and no Data Source step. The type is a row of
 *     tiles and the collection a row of chips, both on "Auto" by default
 *     and routed server-side; Generate POSTs /ai/component-from-prompt with
 *     nulls for whatever was left to the AI and lands on Component Design,
 *     where the routing notice says what was picked and the AI button reads
 *     "Refine with AI". Back returns to Describe with the used values
 *     pinned.
 *  4. Pinned type + collection are sent as is (routing.source 'user', no
 *     "chosen by the AI" reason); Text makes the collection picker inert
 *     ("Not needed for text") and posts no DC id; figure suggestions
 *     ("suggest" mode) take the same hand-off into Component Design.
 *
 * The seeded dashboard's collection ids are never hard-coded: the project
 * payload is sniffed as the SPA loads it and the collection the mock
 * answers with is read off the live chips (`ai-describe-dc-<dcId>`).
 */

import type { Locator, Page, Request } from "@playwright/test";

import { expect, test } from "@fixtures/auth";

const STATUS_GLOB = "**/depictio/api/v1/utils/status";
const COMPONENT_FROM_PROMPT_GLOB = "**/depictio/api/v1/ai/component-from-prompt";
const PROJECT_FROM_DASHBOARD_GLOB = "**/depictio/api/v1/projects/get/from_dashboard_id/*";

/** One data collection of the dashboard's project, as the Describe step's
 *  chips list it and as the routed answer names it. */
interface Collection {
  id: string;
  tag: string;
  wfId: string;
}

/** Mirrors RoutingInfo on ComponentFromPromptResponse. */
interface Routing {
  source: "user" | "single" | "auto";
  reason: string;
  alternatives: unknown[];
}

/** Rewrites the status payload's feature flags, keeping the real
 *  status/version so the header badge stays truthful. */
async function mockFeatures(page: Page, ai: boolean): Promise<void> {
  await page.route(STATUS_GLOB, async (route) => {
    const res = await route.fetch();
    const json = (await res.json()) as Record<string, unknown>;
    json.features = { ai, ai_user_keys: ai };
    await route.fulfill({ json });
  });
}

async function mockAIHealth(page: Page): Promise<void> {
  await page.route("**/depictio/api/v1/ai/health", (route) =>
    route.fulfill({
      json: {
        status: "ok",
        model: "test/canned-model",
        allow_user_keys: true,
        // Unlocks the panels without typing a key into the settings drawer.
        server_key_configured: true,
      },
    }),
  );
}

/** Pass-through on the project endpoint the Describe step reads its
 *  collections from (`fetchProjectFromDashboard`), recording every
 *  workflow/DC pair so a test can name a REAL collection (id, tag, workflow)
 *  in its canned answer. The list fills as the page loads; read it only
 *  after the chips have rendered. */
async function sniffProjectCollections(page: Page): Promise<Collection[]> {
  const found: Collection[] = [];
  await page.route(PROJECT_FROM_DASHBOARD_GLOB, async (route) => {
    const res = await route.fetch();
    const json = (await res.json()) as Record<string, unknown>;
    const project = (json.project ?? json) as {
      workflows?: {
        _id?: string;
        id?: string;
        data_collections?: { _id?: string; id?: string; data_collection_tag?: string }[];
      }[];
    };
    for (const wf of project.workflows ?? []) {
      const wfId = String(wf._id ?? wf.id);
      for (const dc of wf.data_collections ?? []) {
        const id = String(dc._id ?? dc.id);
        if (!found.some((c) => c.id === id)) {
          found.push({ id, tag: dc.data_collection_tag ?? id, wfId });
        }
      }
    }
    await route.fulfill({ json });
  });
  return found;
}

/** Canned /ai/component-from-prompt answer for one validated component.
 *  Mirrors ComponentFromPromptResponse: the raw YAML the LLM "emitted", the
 *  parsed dict the builder store hydrates from, and the routing result (the
 *  collection the server authored against plus how it was decided).
 *  `target` is resolved per request, so a test can pick the collection off
 *  the live chips before the mock needs it. */
async function mockComponentFromPrompt(
  page: Page,
  parsed: Record<string, unknown> & { component_type: string },
  target: () => { dc: Collection | null; routing: Routing | null },
): Promise<void> {
  const yaml = Object.entries(parsed)
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join("\n");
  await page.route(COMPONENT_FROM_PROMPT_GLOB, (route) => {
    const { dc, routing } = target();
    return route.fulfill({
      json: {
        component_type: parsed.component_type,
        yaml: `${yaml}\n`,
        parsed,
        explanation: String(parsed.title ?? ""),
        validation_attempts: 1,
        data_collection_id: dc?.id ?? null,
        workflow_id: dc?.wfId ?? null,
        routing,
      },
    });
  });
}

/** Resolves with the next POST to /ai/component-from-prompt. Arm it BEFORE
 *  clicking Generate so the request cannot slip past the listener. */
function nextComponentFromPromptRequest(page: Page): Promise<Request> {
  return page.waitForRequest(
    (req) =>
      req.method() === "POST" && req.url().includes("/ai/component-from-prompt"),
    { timeout: 15_000 },
  );
}

interface ComponentFromPromptBody {
  prompt: string;
  component_type: string | null;
  data_collection_id: string | null;
  dashboard_id: string;
  current?: unknown;
}

/** Opens the first seeded dashboard card; returns its id from the URL. */
async function openFirstDashboard(page: Page): Promise<string> {
  await page.goto("/dashboards");
  const cards = page.locator("[data-testid='dashboard-card']");
  // The list is fetched after mount: wait for a card before deciding the
  // stack is empty, otherwise the count is read too early and the test skips.
  await cards.first().waitFor({ state: "visible", timeout: 15_000 }).catch(() => undefined);
  const count = await cards.count();
  test.skip(count === 0, "No dashboards seeded in this stack.");
  const openLink = cards
    .first()
    .getByRole("link")
    .filter({ has: page.getByRole("heading") });
  await openLink.click();
  await expect(page).toHaveURL(/\/dashboard\//, { timeout: 15_000 });
  const match = page.url().match(/\/dashboard\/([^/?#]+)/);
  return match![1];
}

/** Editor chrome → Add menu → Component: lands on the Add-component page's
 *  source chooser (manual / catalog / AI when the feature is on). The Add
 *  button is disabled until the dashboard has loaded and ownership resolved. */
async function openAddComponentChooser(page: Page, dashboardId: string): Promise<void> {
  await page.goto(`/dashboard-edit/${dashboardId}`);
  const addButton = page.locator("[data-tour-id='editor-add-component']");
  await expect(addButton).toBeEnabled({ timeout: 20_000 });
  await addButton.click();
  await page.locator("[data-testid='add-component']").click();
  await page.waitForURL(/\/component\/add\//, { timeout: 15_000 });
  await expect(page.locator("[data-testid='component-source-manual']")).toBeVisible();
}

/** Mantine's SegmentedControl keeps its radios visually hidden and binds a
 *  <label for> to each; clicking the input fails the viewport check, so click
 *  the label carrying the wanted value instead (same trick as flipSwitch in
 *  filters-into-builder.spec.ts). */
async function pickSegment(page: Page, testId: string, value: string): Promise<void> {
  const id = await page
    .locator(`[data-testid='${testId}'] input[value='${value}']`)
    .getAttribute("id");
  await page.locator(`label[for='${id}']`).click();
}

/** The stepper's current step. Mantine marks it with data-progress; the
 *  step label ("Component Design") lives inside the same button, which makes
 *  this assertion immune to the Design step's own heading (it repeats the
 *  words "Component Design" after the type label and would also match a
 *  page-wide text lookup). */
function activeStep(page: Page): Locator {
  return page.locator(
    "[data-tour-id='component-wizard-stepper'] .mantine-Stepper-step[data-progress]",
  );
}

/** Chooser → AI tile. The AI flow opens straight on Describe: no type grid,
 *  no Data Source step, two steps in the stepper. */
async function startDescribeFlow(page: Page): Promise<void> {
  await page.locator("[data-testid='component-source-ai']").click();
  await expect(activeStep(page)).toContainText("Describe");
  await expect(page.locator("[data-testid='ai-describe-prompt']")).toBeVisible();
  await expect(page.locator("[data-testid^='component-type-']")).toHaveCount(0);
  await expect(
    page.locator("[data-tour-id='component-wizard-stepper'] .mantine-Stepper-step"),
  ).toHaveCount(2);
}

/** The one-line summaries under the type tiles and the collection chips:
 *  what will be used unless pinned ("Auto: ..."), else the pinned choice. */
function describeSummary(page: Page, which: "type" | "dc"): Locator {
  return page.locator(`[data-testid='ai-describe-${which}-summary']`);
}

/** Pins a component type by clicking its tile; the summary echoes the label. */
async function pickType(page: Page, type: string, label: string): Promise<void> {
  await page.locator(`[data-testid='ai-describe-type-${type}']`).click();
  await expect(describeSummary(page, "type")).toHaveText(label);
}

const DC_CHIP_PREFIX = "ai-describe-dc-";

/** Mantine Chip: `data-testid`, `value` and `id` sit on a visually hidden
 *  <input>; the visible, clickable part is its <label for=id>. */
async function chipLabel(page: Page, input: Locator): Promise<Locator> {
  const id = await input.getAttribute("id");
  return page.locator(`label[for='${id}']`);
}

/** The picker's "Auto" chip (no test id of its own; value 'auto'). */
function autoCollectionChip(page: Page): Locator {
  return page.locator("[data-testid='ai-describe-dc'] input[value='auto']");
}

/** The first collection chip, i.e. the first one shown directly: the
 *  dashboard's own collections come first in DOM order, the rest of the
 *  project sits inside the collapsed "N other collections" fold. Its dc id
 *  is the test id minus the prefix; tag and workflow come from the sniffed
 *  project. With `select: true` the chip is pinned (clicked); otherwise it
 *  is only read, so the Auto test learns which collection a realistic
 *  routed answer would name without pinning it. */
async function firstDashboardCollection(
  page: Page,
  collections: Collection[],
  opts: { select: boolean },
): Promise<Collection> {
  const chip = page
    .locator(`[data-testid='ai-describe-dc'] input[data-testid^='${DC_CHIP_PREFIX}']`)
    .first();
  // Chips render once the project has loaded.
  await expect(chip).toBeAttached({ timeout: 15_000 });
  const id = ((await chip.getAttribute("data-testid")) ?? "").slice(DC_CHIP_PREFIX.length);
  const label = await chipLabel(page, chip);
  // A folded "other" collection would be hidden: the first chip must be a
  // dashboard one for the test to mean what it says.
  await expect(label).toBeVisible();
  const tag = ((await label.textContent()) ?? "").trim();
  if (opts.select) {
    await label.click();
    await expect(chip).toBeChecked();
    await expect(describeSummary(page, "dc")).toHaveText(tag);
  } else {
    await expect(autoCollectionChip(page)).toBeChecked();
  }
  const known = collections.find((c) => c.id === id);
  expect(known, `chip "${tag}" (${id}) is not in the project payload`).toBeTruthy();
  expect(known!.tag).toBe(tag);
  return known!;
}

/** Post-Generate hand-off: same create URL, Design step active, and the AI
 *  button reads "Refine with AI" because the config is pre-filled. */
async function expectLandedOnDesign(page: Page): Promise<void> {
  await expect(page).toHaveURL(/\/component\/add\//);
  await expect(activeStep(page)).toContainText("Component Design", {
    timeout: 15_000,
  });
  await expect(page.locator("[data-testid='ai-fill-open']")).toHaveText(
    "Refine with AI",
  );
}

test.describe("AI assistant", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "AI surfaces are exercised with an authenticated owner session.",
  );

  test("feature off: no AI affordances anywhere, no AI tile on the chooser", async ({
    loginAsAdmin,
    page,
  }) => {
    await mockFeatures(page, false);
    await loginAsAdmin();
    const dashboardId = await openFirstDashboard(page);

    await expect(page.locator(".react-grid-item").first()).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("Ask the dashboard")).toHaveCount(0);
    await expect(page.locator("[data-testid^='ai-summarize-']")).toHaveCount(0);

    // The Add-component chooser keeps its manual tile but grows no AI tile.
    await openAddComponentChooser(page, dashboardId);
    await expect(page.locator("[data-testid='component-source-manual']")).toBeVisible();
    await expect(page.locator("[data-testid='component-source-ai']")).toHaveCount(0);
  });

  test("analyze prompt answers and applying the plan raises the AI chips", async ({
    loginAsAdmin,
    page,
  }) => {
    await mockFeatures(page, true);
    await mockAIHealth(page);

    // The canned plan carries one expr filter plus one figure mutation.
    // The mutation must target a REAL figure on whatever dashboard is
    // seeded first (the host validates ids against stored_metadata), so we
    // sniff the dashboard payload as the app loads it and template the id
    // into the SSE body at request time.
    let figureId: string | null = null;
    await page.route("**/depictio/api/v1/dashboards/get/*", async (route) => {
      const res = await route.fetch();
      const json = (await res.json()) as {
        stored_metadata?: { index?: string; component_type?: string }[];
      };
      figureId =
        json.stored_metadata?.find((m) => m.component_type === "figure")?.index ??
        null;
      await route.fulfill({ json });
    });

    await page.route("**/depictio/api/v1/ai/analyze", (route) => {
      const mutations = figureId
        ? `[{"component_id":"${figureId}","dict_kwargs_patch":{"log_y":true},"reason":"log scale"}]`
        : "[]";
      const resolved =
        '[{"kind":"filter_expr","filter_expr":"col(\'depth\') >= 50.0","dc_id":null,"description":"depth at or above the median"}]';
      const sse = [
        'event: status\ndata: {"message":"thinking"}',
        'event: answer\ndata: {"answer":"Median depth is 50."}',
        `event: actions\ndata: {"filters":[],"figure_mutations":${mutations},"filter_proposals":[],"resolved_filters":${resolved},"warnings":[]}`,
        `event: result\ndata: {"answer":"Median depth is 50.","steps":[],"actions":{"filters":[],"figure_mutations":${mutations},"filter_proposals":[]},"resolved_filters":${resolved}}`,
        "event: done\ndata: {}",
      ].join("\n\n");
      return route.fulfill({
        contentType: "text/event-stream",
        body: `${sse}\n\n`,
      });
    });

    await loginAsAdmin();
    await openFirstDashboard(page);

    const panel = page.getByText("Ask the dashboard");
    await expect(panel).toBeVisible({ timeout: 20_000 });

    // The prompt has two levels; only "Update dashboard" may propose
    // actions. Interpret is the default, so flip the toggle first.
    await pickSegment(page, "ai-prompt-mode", "mutate");
    await page
      .getByPlaceholder(/Show the top 3%/)
      .fill("median depth then filter to it");
    await page.getByRole("button", { name: "Ask", exact: true }).click();

    await expect(page.getByText("Median depth is 50.")).toBeVisible({
      timeout: 15_000,
    });

    // The proposed plan renders with the resolved expr; apply it.
    await expect(page.getByText("Proposed dashboard actions")).toBeVisible();
    await page.getByRole("button", { name: "Apply", exact: true }).click();

    await expect(page.locator("[data-testid='ai-filters-chip']")).toBeVisible();
    await expect(page.getByText("AI filters (1)")).toBeVisible();

    // The figure mutation becomes a transient override with its own chip.
    // `figureId` was sniffed while the dashboard loaded (long before Apply),
    // so it reliably tells us whether the plan carried a mutation at all.
    if (figureId) {
      await expect(page.getByText("AI figure tweaks (1)")).toBeVisible();
      await page.getByText("AI figure tweaks (1)").click();
      await expect(
        page.locator("[data-testid='ai-figure-overrides-chip']"),
      ).toHaveCount(0);
    }

    // Clearing the chip removes the injected filter group.
    await page.getByText("AI filters (1)").click();
    await expect(page.locator("[data-testid='ai-filters-chip']")).toHaveCount(0);
  });

  test("read-only analysis renders a report and never an Apply affordance", async ({
    loginAsAdmin,
    page,
  }) => {
    await mockFeatures(page, true);
    await mockAIHealth(page);

    // Canned read-only run: plan → budget → step → answer → report.
    // Even though the report cites steps, the surface must offer no way
    // to apply anything — the server stripped actions and the modal has
    // no Apply code path at all.
    await page.route("**/depictio/api/v1/ai/analyze", (route) => {
      const step =
        '{"thought":"count deep rows","code":"df.filter(pl.col(\'depth\') >= 50).height","output":"51",' +
        '"status":"success","dc_tag":"obs","rows_in":100,"rows_out":null,"seconds":0.1}';
      const report =
        '{"id":"r1","dashboard_id":"d1","created_at":"2026-08-06T12:00:00+00:00","model":"test-model",' +
        '"prompt":"how many deep rows?","status":"complete",' +
        '"findings":[{"claim":"51 of 100 rows are at or above the median depth","evidence_step_ids":[0],"confidence":"high"}],' +
        `"steps":[${step}],"narrative_md":"51 rows are deep.","budget_spent":{"steps":1,"tokens":150,"seconds":2.0},"warnings":[]}`;
      const sse = [
        'event: status\ndata: {"message":"reading data collections"}',
        'event: plan\ndata: {"plan":"Count rows at or above the median."}',
        'event: budget\ndata: {"steps_used":0,"tokens_used":150,"seconds":1,"max_steps":20,"max_tokens":200000,"max_seconds":300}',
        `event: step\ndata: ${step}`,
        'event: answer\ndata: {"answer":"51 rows are deep."}',
        `event: report\ndata: ${report}`,
        `event: result\ndata: {"answer":"51 rows are deep.","steps":[${step}],"mode":"analyze",` +
          '"actions":{"filters":[],"figure_mutations":[],"filter_proposals":[]},"resolved_filters":[],"warnings":[]}',
        "event: done\ndata: {}",
      ].join("\n\n");
      return route.fulfill({
        contentType: "text/event-stream",
        body: `${sse}\n\n`,
      });
    });
    await page.route("**/depictio/api/v1/ai/analyses/*", (route) =>
      route.fulfill({ json: { analyses: [] } }),
    );

    await loginAsAdmin();
    await openFirstDashboard(page);

    await expect(page.getByText("Ask the dashboard")).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole("button", { name: "Analyze", exact: true }).click();

    const modal = page.getByRole("dialog");
    await expect(modal.getByText("Analyze this dashboard")).toBeVisible();
    await modal.getByLabel("Question").fill("how many deep rows?");
    await modal.getByRole("button", { name: "Analyze", exact: true }).click();

    // The report: narrative, evidence-pinned finding, execution trace.
    await expect(modal.getByText("51 rows are deep.")).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      modal.getByText("51 of 100 rows are at or above the median depth"),
    ).toBeVisible();
    await expect(modal.getByText("evidence: #0")).toBeVisible();

    // The read-only contract, asserted literally.
    await expect(modal.getByRole("button", { name: "Apply" })).toHaveCount(0);
    await expect(modal.getByText("Proposed dashboard actions")).toHaveCount(0);
  });

  test("Describe with AI: Auto type and data → Generate routes and lands on Component Design", async ({
    loginAsAdmin,
    page,
  }) => {
    test.setTimeout(120_000);
    await mockFeatures(page, true);
    await mockAIHealth(page);
    const collections = await sniffProjectCollections(page);

    // Nothing pinned: the canned answer plays the router and names a real
    // collection of the dashboard (read off the chips below) as its pick.
    const reason =
      "The request names a per-species average, which is a card on the measurements table.";
    let routed: Collection | null = null;
    await mockComponentFromPrompt(
      page,
      {
        component_type: "card",
        column_name: "flipper_length_mm",
        aggregation: "average",
        title: "Average flipper length",
      },
      () => ({ dc: routed, routing: { source: "auto", reason, alternatives: [] } }),
    );

    await loginAsAdmin();
    const dashboardId = await openFirstDashboard(page);
    await openAddComponentChooser(page, dashboardId);

    // Feature on: the chooser grows its third tile.
    await expect(page.locator("[data-testid='component-source-ai']")).toBeVisible();
    await startDescribeFlow(page);

    // Prompt first: the type tiles and the collection chips both start on
    // Auto, and the summaries say so.
    await expect(describeSummary(page, "type")).toHaveText("Auto: chosen from the prompt");
    await expect(describeSummary(page, "dc")).toHaveText(/^Auto/);
    await expect(autoCollectionChip(page)).toBeChecked();
    // Auto type is not a figure: no prompt/suggest mode switch on this step.
    await expect(page.locator("[data-testid='ai-figure-mode']")).toHaveCount(0);

    routed = await firstDashboardCollection(page, collections, { select: false });

    const promptBox = page.locator("[data-testid='ai-describe-prompt']");
    await promptBox.fill("average flipper length per species");
    const requestPromise = nextComponentFromPromptRequest(page);
    await page.locator("[data-testid='ai-describe-generate']").click();

    // Auto on both sides is sent as nulls, with the dashboard for routing,
    // from scratch (no `current` revision target).
    const body = (await requestPromise).postDataJSON() as ComponentFromPromptBody;
    expect(body.prompt).toBe("average flipper length per species");
    expect(body.component_type).toBeNull();
    expect(body.data_collection_id).toBeNull();
    expect(body.dashboard_id).toBe(dashboardId);
    expect(body.current ?? null).toBeNull();

    await expectLandedOnDesign(page);

    // The routing notice names what the AI picked and why.
    const notice = page.locator("[data-testid='ai-routing-notice']");
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("Card");
    await expect(notice).toContainText(routed.tag);
    await expect(notice).toContainText(reason);

    // Back returns to Describe with the used type and collection pinned, so
    // a wrong guess is one change away.
    await page.getByRole("button", { name: "Back" }).click();
    await expect(activeStep(page)).toContainText("Describe");
    await expect(describeSummary(page, "type")).toHaveText("Card");
    await expect(describeSummary(page, "dc")).toHaveText(routed.tag);
    await expect(
      page.locator(`input[data-testid='${DC_CHIP_PREFIX}${routed.id}']`),
    ).toBeChecked();
  });

  test("Describe with AI: pinned type and data are sent as is", async ({
    loginAsAdmin,
    page,
  }) => {
    test.setTimeout(120_000);
    await mockFeatures(page, true);
    await mockAIHealth(page);
    const collections = await sniffProjectCollections(page);

    // Both pinned: the server echoes the pick with routing.source 'user'.
    // The reason is deliberately distinctive so its absence on the Design
    // step is a real assertion (nothing was chosen by the AI).
    const reason = "Both were pinned by the user; nothing was routed.";
    let pinned: Collection | null = null;
    await mockComponentFromPrompt(
      page,
      {
        component_type: "card",
        column_name: "body_mass_g",
        aggregation: "median",
        title: "Median body mass",
      },
      () => ({ dc: pinned, routing: { source: "user", reason, alternatives: [] } }),
    );

    await loginAsAdmin();
    const dashboardId = await openFirstDashboard(page);
    await openAddComponentChooser(page, dashboardId);
    await startDescribeFlow(page);

    await pickType(page, "card", "Card");
    pinned = await firstDashboardCollection(page, collections, { select: true });

    await page.locator("[data-testid='ai-describe-prompt']").fill("median body mass");
    const requestPromise = nextComponentFromPromptRequest(page);
    await page.locator("[data-testid='ai-describe-generate']").click();

    const body = (await requestPromise).postDataJSON() as ComponentFromPromptBody;
    expect(body.component_type).toBe("card");
    expect(body.data_collection_id).toBe(pinned.id);
    expect(body.dashboard_id).toBe(dashboardId);

    await expectLandedOnDesign(page);

    // The notice may still name the type and collection, but carries no
    // "chosen by the AI" reason: nothing was routed.
    const notice = page.locator("[data-testid='ai-routing-notice']");
    if (await notice.isVisible().catch(() => false)) {
      await expect(notice).toContainText("Card");
      await expect(notice).toContainText(pinned.tag);
    }
    await expect(page.getByText(reason)).toHaveCount(0);
  });

  test("Describe with AI: text needs no data collection", async ({
    loginAsAdmin,
    page,
  }) => {
    test.setTimeout(120_000);
    await mockFeatures(page, true);
    await mockAIHealth(page);
    await mockComponentFromPrompt(
      page,
      {
        component_type: "text",
        title: "Intro",
        body: "Hello **there**",
      },
      // Text binds to no collection: no dc, no workflow, and no routing.
      () => ({ dc: null, routing: null }),
    );

    await loginAsAdmin();
    const dashboardId = await openFirstDashboard(page);
    await openAddComponentChooser(page, dashboardId);
    await startDescribeFlow(page);

    // Pinning Text makes the collection picker inert; the summary says why.
    await pickType(page, "text", "Text");
    await expect(describeSummary(page, "dc")).toHaveText("Not needed for text");

    await page
      .locator("[data-testid='ai-describe-prompt']")
      .fill("a short intro for this dashboard");
    const requestPromise = nextComponentFromPromptRequest(page);
    await page.locator("[data-testid='ai-describe-generate']").click();

    const body = (await requestPromise).postDataJSON() as ComponentFromPromptBody;
    expect(body.component_type).toBe("text");
    expect(body.data_collection_id).toBeNull();
    expect(body.dashboard_id).toBe(dashboardId);

    await expectLandedOnDesign(page);
  });

  test("Describe with AI: figure suggestions → Use this lands on Component Design", async ({
    loginAsAdmin,
    page,
  }) => {
    test.setTimeout(120_000);
    await mockFeatures(page, true);
    await mockAIHealth(page);
    const collections = await sniffProjectCollections(page);
    await page.route("**/depictio/api/v1/ai/suggest-figures", (route) =>
      route.fulfill({
        json: {
          suggestions: [
            {
              visu_type: "histogram",
              dict_kwargs: { x: "depth" },
              title: "Depth distribution",
              explanation: "Shows how sequencing depth spreads across samples.",
              code: 'px.histogram(df, x="depth")',
            },
            {
              visu_type: "scatter",
              dict_kwargs: { x: "depth", y: "coverage" },
              title: "Depth vs coverage",
              explanation: "Correlation between depth and coverage.",
              code: 'px.scatter(df, x="depth", y="coverage")',
            },
          ],
        },
      }),
    );
    // "Use this" hydrates the builder client-side, but the prompt mode of
    // the same step stays reachable, so its mock stays mounted too.
    let pinned: Collection | null = null;
    await mockComponentFromPrompt(
      page,
      {
        component_type: "figure",
        visu_type: "histogram",
        dict_kwargs: { x: "depth" },
        title: "Depth distribution",
      },
      () => ({ dc: pinned, routing: { source: "user", reason: "", alternatives: [] } }),
    );

    await loginAsAdmin();
    const dashboardId = await openFirstDashboard(page);
    await openAddComponentChooser(page, dashboardId);
    await startDescribeFlow(page);

    // Suggestions need a concrete collection before any answer exists:
    // pin Figure and a collection, and the prompt/suggest switch appears.
    await pickType(page, "figure", "Figure");
    pinned = await firstDashboardCollection(page, collections, { select: true });
    await expect(page.locator("[data-testid='ai-figure-mode']")).toBeVisible();

    await pickSegment(page, "ai-figure-mode", "suggest");
    await page.locator("[data-testid='ai-suggest-run']").click();

    const first = page.locator("[data-testid='ai-suggestion-0']");
    await expect(first).toContainText("Depth distribution", { timeout: 15_000 });
    await expect(page.locator("[data-testid='ai-suggestion-1']")).toContainText(
      "Depth vs coverage",
    );

    await page.locator("[data-testid='ai-suggestion-use-0']").click();
    await expectLandedOnDesign(page);
  });
});
