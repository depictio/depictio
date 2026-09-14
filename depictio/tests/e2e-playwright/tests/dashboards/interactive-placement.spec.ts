/**
 * Where an interactive component renders.
 *
 * Interactive components never take a grid tile: both apps filter them out of
 * the grid and route them to the left filter panel (placement 'left', the model
 * default) or to the top band (placement 'top', allow-listed to Timeline).
 *
 * The catalog walk is the other spec that touches this contract, but it skips
 * itself entirely on a stack with no ingested tool output, so it cannot be the
 * only thing guarding it. This one runs against whichever seeded dashboard
 * carries filters — on a default stack, the iris one, which has both a bare
 * control and a grouped pair.
 */

import { test, expect, apiLogin, API_URL, API_PREFIX } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

const FILTER_PANEL = "[data-tour-id='filter-panel']";
const GRID = "[data-testid='dashboard-content']";
/** How many dashboards to open before giving up on finding one with filters. */
const SCAN_LIMIT = 15;

interface StoredComponent {
  index: string;
  component_type?: string;
  column_name?: string;
  placement?: string;
}

interface DashboardEntry {
  dashboard_id: string;
  title?: string;
}

async function findDashboardWithFilters(
  request: Parameters<typeof apiLogin>[0],
): Promise<{ id: string; title: string; controls: StoredComponent[] } | null> {
  const admin = credentials.adminUser;
  let token: string;
  try {
    token = (await apiLogin(request, admin.email, admin.password)).access_token;
  } catch {
    return null;
  }
  const headers = { Authorization: `Bearer ${token}` };
  const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/list`, { headers });
  if (!res.ok()) return null;
  const body = (await res.json()) as { dashboards?: DashboardEntry[] } | DashboardEntry[];
  const entries = Array.isArray(body) ? body : (body.dashboards ?? []);

  // The listing does not carry stored_metadata, so the components have to be
  // read one document at a time. Bounded: this is a guard, not a survey.
  for (const entry of entries.slice(0, SCAN_LIMIT)) {
    const doc = await request.get(
      `${API_URL}${API_PREFIX}/dashboards/get/${entry.dashboard_id}`,
      { headers },
    );
    if (!doc.ok()) continue;
    const { stored_metadata = [] } = (await doc.json()) as {
      stored_metadata?: StoredComponent[];
    };
    const controls = stored_metadata.filter(
      (m) => m.component_type === "interactive" && m.placement !== "top",
    );
    if (controls.length) {
      return { id: entry.dashboard_id, title: entry.title ?? entry.dashboard_id, controls };
    }
  }
  return null;
}

test.describe("Interactive component placement", () => {
  test("filters render in the panel, never on the grid", async ({
    page,
    request,
    loginAsAdmin,
  }) => {
    // One dashboard load plus the scan that precedes it; the seeded dashboards
    // this picks from carry a couple of dozen tiles.
    test.setTimeout(120_000);

    const found = await findDashboardWithFilters(request);
    test.skip(!found, "no seeded dashboard carries an interactive component on this stack");

    await loginAsAdmin();
    await page.goto(`/dashboard/${found!.id}`);

    const panel = page.locator(FILTER_PANEL).first();
    await expect(panel).toBeVisible({ timeout: 30_000 });

    // Sections are an accordion, and Mantine unmounts a folded one — so a
    // control in a folded section is legitimately absent from the DOM rather
    // than misplaced. Open them all before asking where anything lives.
    const sections = panel.locator(".depictio-section-control");
    for (let i = 0; i < (await sections.count()); i++) {
      const control = sections.nth(i);
      if ((await control.getAttribute("aria-expanded")) === "false") {
        await control.click();
      }
    }
    await expect(
      panel.locator('.depictio-section-control[aria-expanded="false"]'),
      "every filter section should be open before the placement check",
    ).toHaveCount(0);

    for (const control of found!.controls) {
      const what = `${control.column_name ?? control.index} on ${found!.title}`;
      await expect(
        panel.locator(`[data-component-id='${control.index}']`),
        `${what}: should be in the filter panel`,
      ).toBeVisible({ timeout: 30_000 });
      await expect(
        page.locator(`${GRID} [data-component-id='${control.index}']`),
        `${what}: should not take a grid tile`,
      ).toHaveCount(0);
    }
  });
});
