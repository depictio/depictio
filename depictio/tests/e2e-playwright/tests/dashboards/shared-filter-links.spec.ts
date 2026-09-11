/**
 * Shareable listing views: /dashboards and /projects read their filters out of
 * the URL and write them back, so a link narrowed to one pipeline template can
 * be handed to a reviewer.
 *
 * The template assertions need a project seeded from a template; they skip
 * themselves when the target stack has none (not every CI leg seeds the
 * nf-core projects). The search-scope assertions are data-independent and
 * always run.
 */

import { test, expect, apiLogin, API_URL, API_PREFIX } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

interface ProjectEntry {
  name: string;
  template_origin?: { template_id?: string } | string | null;
}

/** `source/repo` of the first templated project on the stack, or null. */
async function findTemplateScope(
  request: Parameters<typeof apiLogin>[0],
): Promise<string | null> {
  const admin = credentials.adminUser;
  let token: string;
  try {
    token = (await apiLogin(request, admin.email, admin.password)).access_token;
  } catch {
    return null;
  }
  const res = await request.get(`${API_URL}${API_PREFIX}/projects/get/all`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) return null;
  const projects = (await res.json()) as ProjectEntry[];
  for (const p of projects ?? []) {
    const origin = p.template_origin;
    const raw = typeof origin === "string" ? origin : (origin?.template_id ?? "");
    const parts = raw.split("/").filter(Boolean);
    // Drop a trailing version segment: the filter is version-agnostic.
    if (parts.length >= 3) parts.pop();
    if (parts.length >= 2) return `${parts[0]}/${parts[1]}`;
  }
  return null;
}

const banner = "[data-testid=shared-view-banner]";

test.describe("Shareable filter links", () => {
  test("a bare listing shows no shared-view banner", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/dashboards");
    await expect(page.getByTestId("new-dashboard-btn")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator(banner)).toHaveCount(0);
  });

  test("a search param scopes the page and can be cleared", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/dashboards?q=iris");

    const scoped = page.locator(banner);
    await expect(scoped).toBeVisible({ timeout: 30_000 });
    await expect(scoped).toContainText('"iris"');
    // The search box is filled from the URL, not just the filter state.
    await expect(page.getByPlaceholder("Search dashboards…")).toHaveValue("iris");

    await scoped.getByRole("button", { name: "Show everything" }).click();
    await expect(page.locator(banner)).toHaveCount(0);
    // Clearing the filters clears the link too: the address bar is the view.
    await expect(page).not.toHaveURL(/[?&]q=/);
  });

  test("filtering in the UI writes the filter back into the URL", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/dashboards");
    await expect(page.getByTestId("new-dashboard-btn")).toBeVisible({
      timeout: 30_000,
    });

    await page.getByPlaceholder("Search dashboards…").fill("penguins");
    await expect(page).toHaveURL(/[?&]q=penguins/);

    // …and the share button offers that exact URL.
    await expect(page.getByTestId("share-view-btn")).toBeVisible();
  });

  test("a template link scopes both listings to that pipeline", async ({
    loginAsAdmin,
    page,
    request,
  }) => {
    const scope = await findTemplateScope(request);
    test.skip(!scope, "no templated project seeded on this stack");

    await loginAsAdmin();

    await page.goto(`/dashboards?template=${encodeURIComponent(scope!)}`);
    const dashboardBanner = page.locator(banner);
    await expect(dashboardBanner).toBeVisible({ timeout: 30_000 });
    await expect(dashboardBanner).toContainText(/of \d+ dashboards/);

    // The same scope reads on the projects listing, one hop away.
    await dashboardBanner
      .getByRole("link", { name: /See the matching projects/ })
      .click();
    await expect(page).toHaveURL(/\/projects\?template=/);

    const projectBanner = page.locator(banner);
    await expect(projectBanner).toBeVisible({ timeout: 30_000 });
    await expect(projectBanner).toContainText(/of \d+ projects/);
  });
});
