/**
 * AI assistant surfaces, fully deterministic: every /ai/* call and the
 * status feature flags are intercepted, so these tests run with
 * DEPICTIO_AI_ENABLED=false and no LLM key in CI.
 *
 * Covered:
 *  1. Feature off ⇒ zero AI affordances anywhere.
 *  2. Feature on ⇒ analyze panel answers and applying the plan surfaces
 *     the "AI filters" chip (expr-only filter injection).
 *  3. "Add component → With AI…" lands on the builder's Design step with
 *     the validated component pre-filled.
 */

import type { Page } from "@playwright/test";

import { expect, test } from "@fixtures/auth";

const STATUS_GLOB = "**/depictio/api/v1/utils/status";

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

/** Opens the first seeded dashboard card; returns its id from the URL. */
async function openFirstDashboard(page: Page): Promise<string> {
  await page.goto("/dashboards");
  const cards = page.locator("[data-testid='dashboard-card']");
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

test.describe("AI assistant", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "AI surfaces are exercised with an authenticated owner session.",
  );

  test("feature off: no AI affordances anywhere", async ({
    loginAsAdmin,
    page,
  }) => {
    await mockFeatures(page, false);
    await loginAsAdmin();
    await openFirstDashboard(page);

    await expect(page.locator(".react-grid-item").first()).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("Ask the dashboard")).toHaveCount(0);
    await expect(page.locator("[data-testid^='ai-summarize-']")).toHaveCount(0);
    await expect(page.locator("[data-testid='add-with-ai']")).toHaveCount(0);
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
    await page.getByRole("radio", { name: "Update dashboard" }).click();
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

  test("Add component → With AI… pre-fills the builder's Design step", async ({
    loginAsAdmin,
    page,
  }) => {
    await mockFeatures(page, true);
    await mockAIHealth(page);
    await page.route("**/depictio/api/v1/ai/component-from-prompt", (route) =>
      route.fulfill({
        json: {
          component_type: "card",
          yaml: "component_type: card\naggregation: count\ncolumn_name: variety\ncolumn_type: object\ntitle: Sample count\n",
          parsed: {
            component_type: "card",
            aggregation: "count",
            column_name: "variety",
            column_type: "object",
            title: "Sample count",
          },
          explanation: "Sample count",
          validation_attempts: 1,
        },
      }),
    );

    await loginAsAdmin();
    const dashboardId = await openFirstDashboard(page);
    await page.goto(`/dashboard-edit/${dashboardId}`);

    // Nested menu: "Add" > "Component" submenu holds the AI entry.
    const addButton = page.locator("[data-tour-id='editor-add-component']");
    await expect(addButton).toBeEnabled({ timeout: 20_000 });
    await addButton.click();
    await page.locator("[data-testid='add-component-submenu']").click();
    await page.locator("[data-testid='add-with-ai']").click();

    const modal = page.getByText("Add component with AI");
    await expect(modal).toBeVisible();

    await page
      .getByPlaceholder(/Histogram of read length/)
      .fill("count of samples per variety");
    await page.getByRole("button", { name: "Generate", exact: true }).click();

    // Hand-off: create page, Design step, AI value pre-filled.
    await expect(page).toHaveURL(/\/component\/add\//, { timeout: 15_000 });
    await expect(page.getByText("Component Design")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Refine with AI")).toBeVisible();
  });

  test("figure suggestions land in the builder's Design step", async ({
    loginAsAdmin,
    page,
  }) => {
    await mockFeatures(page, true);
    await mockAIHealth(page);
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

    await loginAsAdmin();
    const dashboardId = await openFirstDashboard(page);
    await page.goto(`/dashboard-edit/${dashboardId}`);

    const addButton = page.locator("[data-tour-id='editor-add-component']");
    await expect(addButton).toBeEnabled({ timeout: 20_000 });
    await addButton.click();
    await page.locator("[data-testid='add-component-submenu']").click();
    await page.locator("[data-testid='add-with-ai']").click();
    await expect(page.getByText("Add component with AI")).toBeVisible();

    // Figure is the default type; flip to suggestions mode and fetch.
    await page.getByRole("radio", { name: "Suggestions" }).click();
    await page.locator("[data-testid='ai-suggest-run']").click();

    await expect(page.getByText("Depth distribution")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Depth vs coverage")).toBeVisible();

    // Picking one reuses the component-from-prompt hand-off.
    await page
      .locator("[data-testid='ai-suggestion-0']")
      .getByRole("button", { name: "Use this" })
      .click();
    await expect(page).toHaveURL(/\/component\/add\//, { timeout: 15_000 });
    await expect(page.getByText("Component Design")).toBeVisible({
      timeout: 15_000,
    });
  });
});
