/**
 * Cross-tab persistent sections & global filters (issue #858).
 *
 * Against the seeded nf-core/ampliseq multi-tab dashboard:
 *   - the "Sample metadata" grid section (owned by the main tab, marked
 *     `persistent: true`) is present on a sibling tab via the fan-out host;
 *   - a value picked in the persistent "Sample filters" section survives the
 *     full-page navigation of a tab switch (sessionStorage hydration) and the
 *     control itself is present on the sibling tab.
 *
 * Skips itself when the ampliseq reference project is not seeded in the
 * target stack (not every CI leg seeds the nf-core projects).
 */

import { test, expect, apiLogin, API_URL, API_PREFIX } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

interface DashboardEntry {
  dashboard_id: string;
  title?: string;
  parent_dashboard_id?: string | null;
}

async function findAmpliseqFamily(
  request: Parameters<typeof apiLogin>[0],
): Promise<{ main: DashboardEntry; sibling: DashboardEntry } | null> {
  const admin = credentials.adminUser;
  let token: string;
  try {
    token = (await apiLogin(request, admin.email, admin.password)).access_token;
  } catch {
    return null;
  }
  const res = await request.get(
    `${API_URL}${API_PREFIX}/dashboards/list?include_child_tabs=true`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!res.ok()) return null;
  const body = (await res.json()) as { dashboards?: DashboardEntry[] } | DashboardEntry[];
  const entries = Array.isArray(body) ? body : (body.dashboards ?? []);
  const main = entries.find(
    (d) => d.title === "nf-core/ampliseq" && !d.parent_dashboard_id,
  );
  if (!main) return null;
  const sibling = entries.find((d) => d.parent_dashboard_id === main.dashboard_id);
  if (!sibling) return null;
  return { main, sibling };
}

test.describe("Cross-tab persistent sections & filters", () => {
  test("metadata section and sample filter survive a tab switch", async ({
    page,
    request,
    loginAsAdmin,
  }) => {
    // Two full loads of the ampliseq dashboard, each waiting on its data, sit
    // right at the suite's 60s budget — the run before this one passed only on
    // retry. The work is genuinely slow rather than stuck, so give it room.
    test.setTimeout(180_000);

    const family = await findAmpliseqFamily(request);
    test.skip(!family, "nf-core/ampliseq multi-tab dashboard not seeded on this stack");

    await loginAsAdmin();
    await page.goto(`/dashboard/${family!.main.dashboard_id}`);

    // The persistent grid section lives on the main tab itself, so here it is
    // rendered by its owner: its accordion header is the landing-slot for the
    // metadata table and the four metadata cards.
    await expect(page.getByText("Sample metadata", { exact: true })).toBeVisible({
      timeout: 30_000,
    });

    // Pick a sample in the persistent filter section (main tab owns it).
    const sampleSelect = page.getByPlaceholder("Select sample…").first();
    await expect(sampleSelect).toBeVisible({ timeout: 30_000 });
    await sampleSelect.click();
    const firstOption = page.getByRole("option").first();
    await expect(firstOption).toBeVisible();
    const picked = (await firstOption.innerText()).trim();
    await firstOption.click();
    await page.keyboard.press("Escape");

    // The persisted payload lands in sessionStorage keyed on the family.
    await expect
      .poll(async () =>
        page.evaluate(() => window.sessionStorage.getItem("depictio:cross-tab-filters")),
      )
      .toContain(picked);

    // Tab switch = full page navigation; the sibling tab must hydrate the
    // value back and render the fanned-out control and metadata section.
    await page.goto(`/dashboard/${family!.sibling.dashboard_id}`);
    await expect(page.getByText("Sample metadata", { exact: true })).toBeVisible({
      timeout: 30_000,
    });
    // Mantine MultiSelect renders the selected value as a pill inside the
    // fanned-out control.
    await expect(page.getByText(picked, { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    });
    const stored = await page.evaluate(() =>
      window.sessionStorage.getItem("depictio:cross-tab-filters"),
    );
    expect(stored).toContain(picked);
  });
});
