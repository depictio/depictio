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

  test("analyze prompt answers and applying the plan raises the AI filters chip", async ({
    loginAsAdmin,
    page,
  }) => {
    await mockFeatures(page, true);
    await mockAIHealth(page);

    const sse = [
      'event: status\ndata: {"message":"thinking"}',
      'event: answer\ndata: {"answer":"Median depth is 50."}',
      'event: actions\ndata: {"filters":[],"figure_mutations":[],"filter_proposals":[],"resolved_filters":[{"kind":"filter_expr","filter_expr":"col(\'depth\') >= 50.0","dc_id":null,"description":"depth at or above the median"}],"warnings":[]}',
      'event: result\ndata: {"answer":"Median depth is 50.","steps":[],"actions":{"filters":[],"figure_mutations":[],"filter_proposals":[]},"resolved_filters":[{"kind":"filter_expr","filter_expr":"col(\'depth\') >= 50.0","dc_id":null,"description":"depth at or above the median"}]}',
      "event: done\ndata: {}",
    ].join("\n\n");
    await page.route("**/depictio/api/v1/ai/analyze", (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: `${sse}\n\n`,
      }),
    );

    await loginAsAdmin();
    await openFirstDashboard(page);

    const panel = page.getByText("Ask the dashboard");
    await expect(panel).toBeVisible({ timeout: 20_000 });

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

    // Clearing the chip removes the injected filter group.
    await page.getByText("AI filters (1)").click();
    await expect(page.locator("[data-testid='ai-filters-chip']")).toHaveCount(0);
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

    // Split menu: "Add component" opens a dropdown with the AI entry.
    const addButton = page.locator("[data-tour-id='editor-add-component']");
    await expect(addButton).toBeEnabled({ timeout: 20_000 });
    await addButton.click();
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
});
