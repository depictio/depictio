/**
 * `depictio local up`: the container-free server, booted from the wheel.
 *
 * Runs only in the local-server workflow (.github/workflows/local-server-smoke.yaml),
 * which sets LOCAL_MODE_E2E=1 and points both PLAYWRIGHT_BASE_URL and
 * PLAYWRIGHT_API_URL at the one uvicorn process: FastAPI serves the viewer
 * bundle shipped in the wheel. The stack is seeded with the iris example only.
 *
 * What this adds over the curl checks in that workflow: the dashboard seeds,
 * the viewer bundle and the data path (worker → SeaweedFS → Delta → API) are
 * only proven together when a browser renders a dashboard and a filter
 * recomputes a card.
 */

import { test, expect } from "@fixtures/auth";
import { API_URL, API_PREFIX } from "@fixtures/auth";

const IRIS_DASHBOARD_ID = "6824cb3b89d2b72169309737";
const IRIS_DC_ID = "646b0f3c1e4a2d7f8e5b8c9c";

test.describe("Local mode (depictio local up)", () => {
  test.skip(!process.env.LOCAL_MODE_E2E, "Only runs against `depictio local up`.");

  // `up` returns once the API answers; the worker writes the iris Delta table a
  // few seconds later, and until then its cards and figures have nothing to read.
  test.beforeAll(async () => {
    test.setTimeout(150_000);
    await expect
      .poll(
        async () =>
          (await fetch(`${API_URL}${API_PREFIX}/deltatables/specs/${IRIS_DC_ID}`)).status,
        { timeout: 120_000, intervals: [2_000] },
      )
      .toBe(200);
  });

  // Fail on any server error the page runs into, not only on what it shows.
  let serverErrors: string[] = [];
  test.beforeEach(async ({ page }) => {
    serverErrors = [];
    page.on("response", (res) => {
      if (res.status() >= 500) serverErrors.push(`${res.status()} ${res.url()}`);
    });
  });
  test.afterEach(() => {
    expect(serverErrors).toEqual([]);
  });

  test("runs in single-user mode as the bootstrap admin", async ({ request }) => {
    const res = await request.get(`${API_URL}${API_PREFIX}/auth/me/optional`);
    expect(res.ok()).toBeTruthy();
    const body = (await res.json()) as {
      auth_mode: string;
      user: { email: string; is_admin: boolean };
    };
    expect(body.auth_mode).toBe("single_user");
    expect(body.user.email).toBe("admin@example.com");
    expect(body.user.is_admin).toBe(true);
  });

  test("the iris table is stored as Delta and queryable", async ({ request }) => {
    const res = await request.get(`${API_URL}${API_PREFIX}/deltatables/specs/${IRIS_DC_ID}`);
    expect(res.ok()).toBeTruthy();
    expect(JSON.stringify(await res.json())).toContain("variety");
  });

  test("the seeded iris dashboard is listed", async ({ page }) => {
    await page.goto("/dashboards");
    await expect(
      page.locator("[data-testid='dashboard-card']").filter({ hasText: "Iris" }).first(),
    ).toBeVisible({ timeout: 30_000 });
  });

  test("the iris dashboard renders and its filter recomputes a card", async ({ page }) => {
    await page.goto(`/dashboard/${IRIS_DASHBOARD_ID}`);

    // First visit on a fresh stack: the onboarding tour overlays the page.
    const skipTour = page.getByRole("button", { name: "Skip tour" });
    await skipTour.click({ timeout: 15_000 }).catch(() => {});

    await expect(page.locator("[data-testid='dashboard-content']")).toBeVisible({
      timeout: 30_000,
    });

    // Figures mount when scrolled into view.
    const figure = page
      .locator(".react-grid-item")
      .filter({ hasText: "Petal Length by Variety" })
      .first();
    await figure.scrollIntoViewIfNeeded({ timeout: 30_000 });
    await expect(figure.locator(".js-plotly-plot")).toBeVisible({ timeout: 60_000 });

    const flowers = page
      .locator(".react-grid-item")
      .filter({ has: page.getByText("Flowers", { exact: true }) })
      .first();
    await expect(flowers).toContainText("100% of 150", { timeout: 30_000 });

    await page.getByPlaceholder("Select variety…").first().click();
    await page.getByRole("option", { name: "Setosa" }).first().click();
    await page.keyboard.press("Escape");

    await expect(flowers).toContainText("33% of 150", { timeout: 30_000 });
  });
});
