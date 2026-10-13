/**
 * Cross-tab persistent sections & global filters (issue #858).
 *
 * Against the seeded nf-core/ampliseq multi-tab dashboard:
 *   - the "Sample sheet" grid section (owned by the main tab, marked
 *     `persistent: true`, `exclude_tabs: [Overview]`) is present on the child
 *     tabs via the fan-out host, and absent from the Overview itself;
 *   - a value picked in the persistent "Sample filters" section on one child
 *     tab survives the full-page navigation of a tab switch (sessionStorage
 *     hydration) and the control itself is present on the sibling tab.
 *
 * Skips itself when the ampliseq reference project is not seeded in the
 * target stack (not every CI leg seeds the nf-core projects).
 */

import { test, expect, apiLogin, API_URL, API_PREFIX } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

interface DashboardEntry {
  dashboard_id: string;
}

// db_init_reference_datasets.STATIC_IDS["ampliseq"]["dashboards"]: the
// Overview main tab and two child tabs that both show the Sample sheet.
const AMPLISEQ_OVERVIEW = "646b0f3c1e4a2d7f8e5b8ca2";
const AMPLISEQ_ALPHA_DIVERSITY = "646b0f3c1e4a2d7f8e5b8cbe";
const AMPLISEQ_COMMUNITY = "646b0f3c1e4a2d7f8e5b8cb3";

async function ampliseqFamilySeeded(
  request: Parameters<typeof apiLogin>[0],
): Promise<boolean> {
  const admin = credentials.adminUser;
  let token: string;
  try {
    token = (await apiLogin(request, admin.email, admin.password)).access_token;
  } catch {
    return false;
  }
  const res = await request.get(
    `${API_URL}${API_PREFIX}/dashboards/list?include_child_tabs=true`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!res.ok()) return false;
  const body = (await res.json()) as { dashboards?: DashboardEntry[] } | DashboardEntry[];
  const entries = Array.isArray(body) ? body : (body.dashboards ?? []);
  const ids = new Set(entries.map((d) => d.dashboard_id));
  return [AMPLISEQ_OVERVIEW, AMPLISEQ_ALPHA_DIVERSITY, AMPLISEQ_COMMUNITY].every((id) =>
    ids.has(id),
  );
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

    const seeded = await ampliseqFamilySeeded(request);
    test.skip(!seeded, "nf-core/ampliseq multi-tab dashboard not seeded on this stack");

    await loginAsAdmin();

    // The Overview excludes the Sample sheet: the main tab owns the section but
    // does not render it.
    await page.goto(`/dashboard/${AMPLISEQ_OVERVIEW}`);
    await expect(page.getByText("Key figures", { exact: true })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("Sample sheet", { exact: true })).toHaveCount(0);

    // On a child tab the fan-out host renders it (collapsed, pinned bottom).
    await page.goto(`/dashboard/${AMPLISEQ_ALPHA_DIVERSITY}`);
    await expect(page.getByText("Sample sheet", { exact: true })).toBeVisible({
      timeout: 30_000,
    });

    // Pick a sample in the persistent filter section (fanned out from the main tab).
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
    await page.goto(`/dashboard/${AMPLISEQ_COMMUNITY}`);
    await expect(page.getByText("Sample sheet", { exact: true })).toBeVisible({
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
