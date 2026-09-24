/**
 * Content-aware tile sizing: a height set by hand wins, and keeps winning.
 *
 * Autofit sizes text, cards, tables and advanced-viz tiles to what they hold,
 * in the editor as well as the viewer. That makes one guarantee worth guarding
 * end to end: the moment a user drags a tile's height, that tile leaves
 * autofit (`fit: fixed` on its stored_metadata) and nothing sizes it again  -
 * not the next save, not a reload, not the viewer. Before autofit ran in the
 * editor there was no way to lose a manual height; now there is, and it is the
 * regression a unit test on `fitLayoutHeights` cannot see, because it lives in
 * the round trip through react-grid-layout and the save.
 *
 * Skips itself when no seeded dashboard carries a text tile.
 */

import { test, expect, apiLogin, API_URL, API_PREFIX } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

/** How many dashboards to open before giving up on finding a text tile. */
const SCAN_LIMIT = 15;

interface StoredComponent {
  index: string;
  component_type?: string;
  fit?: string | null;
}

interface LayoutItem {
  i: string;
  h: number;
}

interface DashboardDoc {
  stored_metadata?: StoredComponent[];
  right_panel_layout_data?: LayoutItem[];
}

interface DashboardEntry {
  dashboard_id: string;
  title?: string;
}

type Request = Parameters<typeof apiLogin>[0];

async function adminHeaders(request: Request): Promise<Record<string, string> | null> {
  const admin = credentials.adminUser;
  try {
    const { access_token } = await apiLogin(request, admin.email, admin.password);
    return { Authorization: `Bearer ${access_token}` };
  } catch {
    return null;
  }
}

async function fetchDashboard(
  request: Request,
  headers: Record<string, string>,
  id: string,
): Promise<DashboardDoc | null> {
  const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/get/${id}`, { headers });
  return res.ok() ? ((await res.json()) as DashboardDoc) : null;
}

/** A dashboard with a text tile on the main grid, plus that tile's id. */
async function findTextTile(
  request: Request,
  headers: Record<string, string>,
): Promise<{ id: string; componentId: string } | null> {
  const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/list`, { headers });
  if (!res.ok()) return null;
  const body = (await res.json()) as { dashboards?: DashboardEntry[] } | DashboardEntry[];
  const entries = Array.isArray(body) ? body : (body.dashboards ?? []);

  for (const entry of entries.slice(0, SCAN_LIMIT)) {
    const doc = await fetchDashboard(request, headers, entry.dashboard_id);
    if (!doc) continue;
    const laidOut = new Set(
      (doc.right_panel_layout_data ?? []).map((item) => String(item.i).replace(/^box-/, "")),
    );
    const text = (doc.stored_metadata ?? []).find(
      (m) => m.component_type === "text" && m.fit !== "fixed" && laidOut.has(m.index),
    );
    if (text) return { id: entry.dashboard_id, componentId: text.index };
  }
  return null;
}

/** The `.react-grid-item` box a component renders in, in CSS pixels. */
async function tileHeight(
  page: import("@playwright/test").Page,
  componentId: string,
): Promise<number> {
  const cell = page.locator(`[data-component-id='${componentId}']`).first();
  await expect(cell).toBeVisible({ timeout: 30_000 });
  return cell.evaluate((node) => {
    const tile = (node as HTMLElement).closest(".react-grid-item") ?? (node as HTMLElement);
    return Math.round(tile.getBoundingClientRect().height);
  });
}

test.describe("Tile sizing", () => {
  test("a height set by hand survives the reload", async ({ page, request, loginAsAdmin }) => {
    // An editor load, a resize, a save and two viewer loads.
    test.setTimeout(180_000);
    void loginAsAdmin;

    const headers = await adminHeaders(request);
    test.skip(!headers, "no admin credentials on this stack");
    const target = await findTextTile(request, headers!);
    test.skip(!target, "no seeded dashboard carries a text tile");
    const { id, componentId } = target!;

    await page.goto(`/dashboard-edit/${id}`);
    const before = await tileHeight(page, componentId);

    // Drag the south handle down by two grid rows. `.react-resizable-handle-s`
    // is react-resizable's own class, injected into the cell by the grid.
    const cell = page.locator(`[data-component-id='${componentId}']`).first();
    const tile = cell.locator("xpath=ancestor::div[contains(@class,'react-grid-item')][1]");
    const handle = tile.locator(".react-resizable-handle-s");
    const box = await handle.boundingBox();
    expect(box, "the resize handle should be reachable in edit mode").not.toBeNull();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.down();
    // In steps: react-grid-layout tracks the drag through mousemove, and a
    // single jump can be swallowed as a click.
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2 + 208, { steps: 12 });
    await page.mouse.up();

    const resized = await tileHeight(page, componentId);
    expect(resized).toBeGreaterThan(before);

    // The editor saves on a 500 ms debounce; poll the document rather than
    // sleeping for it.
    await expect
      .poll(
        async () => {
          const doc = await fetchDashboard(request, headers!, id);
          return (doc?.stored_metadata ?? []).find((m) => m.index === componentId)?.fit ?? null;
        },
        { timeout: 20_000, message: "the resized tile should be marked fit: fixed" },
      )
      .toBe("fixed");

    const saved = await fetchDashboard(request, headers!, id);
    const storedHeight = (saved?.right_panel_layout_data ?? []).find(
      (item) => String(item.i).replace(/^box-/, "") === componentId,
    )?.h;
    expect(storedHeight, "the height the user dragged to is the one persisted").toBeGreaterThan(0);

    // The viewer honours it: autofit may not size a tile whose height someone
    // chose, however little prose it holds.
    await page.goto(`/dashboard/${id}`);
    const inViewer = await tileHeight(page, componentId);
    expect(inViewer).toBe(storedHeight! * 104 - 4);

    // And the editor still agrees with itself after a reload.
    await page.goto(`/dashboard-edit/${id}`);
    expect(await tileHeight(page, componentId)).toBe(resized);
  });
});
