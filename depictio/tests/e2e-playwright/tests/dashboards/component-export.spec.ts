/**
 * "Export / embed" on a tile: the per-component way into the export API.
 *
 * The API (`/export/dashboards/{id}/components[/{cid}]`) is off by default
 * (`DEPICTIO_FASTAPI_EMBED_ENABLED`), and CI does not turn it on, so the
 * server's two answers this UI depends on are stubbed: the feature flag on
 * `/auth/me/optional`, and the manifest saying what each component exports
 * as. What is under test is the viewer's half: the action appears only when
 * the flag is on, the dialog opens on the format the component has, offers
 * the other one only where the manifest does, and builds the URL for the mode
 * picked.
 *
 * Skips itself when no seeded dashboard carries both a figure and a text tile.
 */

import type { Page, Route } from "@playwright/test";

import { test, expect, apiLogin, API_URL, API_PREFIX } from "@fixtures/auth";
import { credentials } from "@fixtures/credentials";

const SCAN_LIMIT = 15;

interface StoredComponent {
  index: string;
  component_type?: string;
  title?: string;
}

interface DashboardEntry {
  dashboard_id: string;
}

type Request = Parameters<typeof apiLogin>[0];

/** A dashboard on the main grid with a figure and a text tile. */
async function findDashboard(
  request: Request,
): Promise<{ id: string; figure: string; text: string; components: StoredComponent[] } | null> {
  const admin = credentials.adminUser;
  let headers: Record<string, string>;
  try {
    const { access_token } = await apiLogin(request, admin.email, admin.password);
    headers = { Authorization: `Bearer ${access_token}` };
  } catch {
    return null;
  }
  const res = await request.get(`${API_URL}${API_PREFIX}/dashboards/list`, { headers });
  if (!res.ok()) return null;
  const body = (await res.json()) as { dashboards?: DashboardEntry[] } | DashboardEntry[];
  const entries = Array.isArray(body) ? body : (body.dashboards ?? []);
  for (const entry of entries.slice(0, SCAN_LIMIT)) {
    const doc = await request.get(`${API_URL}${API_PREFIX}/dashboards/get/${entry.dashboard_id}`, {
      headers,
    });
    if (!doc.ok()) continue;
    const components = ((await doc.json()) as { stored_metadata?: StoredComponent[] })
      .stored_metadata ?? [];
    const figure = components.find((c) => c.component_type === "figure");
    const text = components.find((c) => c.component_type === "text");
    if (figure && text) {
      return { id: entry.dashboard_id, figure: figure.index, text: text.index, components };
    }
  }
  return null;
}

/** `/auth/me/optional` as the server answers it, with the export flags forced. */
async function setEmbedFlags(page: Page, enabled: boolean): Promise<void> {
  await page.route("**/api/v1/auth/me/optional**", async (route: Route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown> | null;
    await route.fulfill({
      response,
      json: {
        ...(body ?? {}),
        embed_enabled: enabled,
        embed_framing_enabled: false,
        walkthrough_disabled: true,
      },
    });
  });
}

/** The manifest the API would serve: figures in both formats, text as a page. */
async function stubManifest(page: Page, components: StoredComponent[]): Promise<void> {
  await page.route("**/api/v1/export/dashboards/*/components", async (route: Route) => {
    await route.fulfill({
      json: components.map((c) => {
        const figure = c.component_type === "figure";
        return {
          component_id: c.index,
          component_type: c.component_type,
          viz_kind: null,
          title: c.title ?? "",
          formats: figure ? ["html", "json"] : ["html"],
          ...(figure
            ? {}
            : {
                json_unavailable_reason:
                  "'text' components are not Plotly figures. Use format=html to embed the rendered component.",
              }),
        };
      }),
    });
  });
}

async function openExport(page: Page, componentId: string) {
  const tile = page.locator(`[data-component-id='${componentId}']`).first();
  await expect(tile).toBeVisible({ timeout: 30_000 });
  await tile.scrollIntoViewIfNeeded();
  await tile.hover();
  await tile.getByTestId("tile-export").click();
  const dialog = page.getByTestId("component-export-modal");
  await expect(dialog).toBeVisible();
  return dialog;
}

test.describe("Component export", () => {
  test("a figure exports as a Plotly spec or a page, a text tile as a page only", async ({
    page,
    request,
    loginAsAdmin,
  }) => {
    test.setTimeout(120_000);
    await loginAsAdmin();
    const target = await findDashboard(request);
    test.skip(!target, "no seeded dashboard carries a figure and a text tile");
    const { id, figure, text, components } = target!;

    await setEmbedFlags(page, true);
    await stubManifest(page, components);
    await page.goto(`/dashboard/${id}`);

    // A figure opens on its richer format, the Plotly spec.
    const dialog = await openExport(page, figure);
    const snippet = dialog.getByTestId("export-snippet");
    await expect(snippet).toContainText(`/export/dashboards/${id}/components/${figure}`);
    await expect(snippet).toContainText("format=json");
    await expect(dialog.getByTestId("export-snippet-plotly")).toBeVisible();

    // Switching the mode rebuilds the URL, and swaps the plotly.js snippet for
    // an iframe, with the warning that no site may frame it yet.
    await dialog.getByTestId("export-mode-html").click();
    await expect(snippet).toContainText("format=html");
    await expect(dialog.getByTestId("export-snippet-iframe")).toBeVisible();
    await expect(dialog.getByText("No site may frame this page yet")).toBeVisible();
    await expect(dialog.getByTestId("export-open")).toHaveAttribute(
      "href",
      new RegExp(`format=html`),
    );
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    // A text tile has no Plotly spec: it opens on the page, and says why the
    // spec is not offered.
    const textDialog = await openExport(page, text);
    await expect(textDialog.getByTestId("export-snippet")).toContainText("format=html");
    await textDialog.getByTestId("export-mode-json").hover();
    await expect(page.getByText(/not Plotly figures/).first()).toBeVisible();
  });

  test("no tile offers export while the API is off", async ({ page, request, loginAsAdmin }) => {
    test.setTimeout(90_000);
    await loginAsAdmin();
    const target = await findDashboard(request);
    test.skip(!target, "no seeded dashboard carries a figure and a text tile");

    await setEmbedFlags(page, false);
    await page.goto(`/dashboard/${target!.id}`);
    const tile = page.locator(`[data-component-id='${target!.figure}']`).first();
    await expect(tile).toBeVisible({ timeout: 30_000 });
    await tile.hover();
    await expect(page.getByTestId("tile-export")).toHaveCount(0);
  });
});
