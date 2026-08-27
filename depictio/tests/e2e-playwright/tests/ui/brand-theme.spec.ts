/**
 * Instance brand theme (issue #397).
 *
 * /admin -> Branding writes a `BrandTheme` that `/utils/public-config` serves
 * to every visitor, already resolved: the derived Mantine shade tuples and the
 * figure colorway are computed server-side so the render path and the SPA
 * cannot drift.
 *
 * The two properties worth pinning here are the ones a refactor breaks
 * silently:
 *   - a hex brand color lands on the shade Mantine actually paints a filled
 *     control with (shade 6 in light mode), rather than near it;
 *   - the status colors survive the brand, because pass / warn / fail have to
 *     keep reading as meaning.
 */

import { API_PREFIX, API_URL, loginAsTestUser, test, expect } from "@fixtures/auth";

type Page = import("@playwright/test").Page;

/** TREC (Traversing European Coastlines), one of the shipped presets. */
const TREC_PRIMARY = "#00a550";

function cssVar(page: Page, name: string, selector = ":root"): Promise<string> {
  return page.evaluate(
    ([sel, prop]) =>
      getComputedStyle(document.querySelector(sel) ?? document.documentElement)
        .getPropertyValue(prop)
        .trim()
        .toLowerCase(),
    [selector, name] as const,
  );
}

test.describe("Instance brand theme", () => {
  test.skip(
    process.env.UNAUTHENTICATED_MODE === "true",
    "The Branding panel is admin-only.",
  );

  // This test has to start from the stock look to mean anything, so it resets
  // the deployment's branding. That is harmless on a fresh CI stack and
  // destructive anywhere else — running the suite against a configured
  // instance used to silently wipe its brand. Snapshot the overrides first and
  // put them back, whatever the test did in between.
  let savedOverrides: Record<string, unknown> | null = null;

  test.beforeEach(async ({ page, request }) => {
    const { access_token } = await loginAsTestUser(page, request, "adminUser");
    const response = await request.get(`${API_URL}${API_PREFIX}/utils/branding`, {
      headers: { Authorization: `Bearer ${access_token}` },
    });
    savedOverrides = response.ok() ? ((await response.json()).overrides ?? null) : null;
  });

  test.afterEach(async ({ page, request }) => {
    const { access_token } = await loginAsTestUser(page, request, "adminUser");
    const headers = { Authorization: `Bearer ${access_token}` };
    const url = `${API_URL}${API_PREFIX}/utils/branding`;
    if (savedOverrides && Object.keys(savedOverrides).length > 0) {
      await request.put(url, { headers, data: savedOverrides });
    } else {
      await request.delete(url, { headers });
    }
  });

  test("applying a preset re-tints the app and spares the status colors", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/admin");
    await page.getByRole("tab", { name: "Branding" }).click();
    await expect(page.locator("[data-testid='admin-branding-panel']")).toBeVisible({
      timeout: 15_000,
    });

    // Anything already configured on this deployment would make the
    // assertions below meaningless, so start from the stock look.
    const reset = page.locator("[data-testid='branding-reset']");
    if (await reset.isEnabled()) {
      await reset.click();
    }

    await page.locator("[data-testid='branding-preset-menu']").click();
    await page.locator("[data-testid='branding-preset-trec']").click();

    // The preview is a nested, scoped MantineProvider: it must re-tint on the
    // draft alone, without leaking into the page around it.
    const preview = page.locator("[data-testid='brand-theme-preview']");
    await expect(preview).toBeVisible();
    await expect
      .poll(() => cssVar(page, "--mantine-color-brandPrimary-6", ".depictio-brand-preview"))
      .toBe(TREC_PRIMARY);
    expect(await cssVar(page, "--mantine-color-brandPrimary-6")).not.toBe(TREC_PRIMARY);

    await page.locator("[data-testid='branding-save']").click();

    // Saved, the whole app follows: shade 6 IS the brand color, `blue` is
    // remapped onto it so the app's existing blue accents come along, and the
    // primary a filled button paints resolves to it.
    await expect.poll(() => cssVar(page, "--mantine-color-blue-6")).toBe(TREC_PRIMARY);
    expect(await cssVar(page, "--mantine-primary-color-filled")).toBe(TREC_PRIMARY);
    // TREC ships `tint_mode: full`, so teal/orange follow the secondary and
    // tertiary too.
    expect(await cssVar(page, "--mantine-color-teal-6")).toBe("#1a4f8f");
    expect(await cssVar(page, "--mantine-color-orange-6")).toBe("#f5a11b");
    // ...but red stays Mantine's red: the brand names no danger color.
    expect(await cssVar(page, "--mantine-color-red-6")).toBe("#fa5252");

    // The theme survives a reload (it is served by /utils/public-config, and
    // cached in localStorage for a flash-free first paint).
    await page.reload();
    await expect.poll(() => cssVar(page, "--mantine-color-blue-6")).toBe(TREC_PRIMARY);

    // Reset returns the deployment to its stock look.
    await page.getByRole("tab", { name: "Branding" }).click();
    await page.locator("[data-testid='branding-reset']").click();
    await expect.poll(() => cssVar(page, "--mantine-color-blue-6")).not.toBe(TREC_PRIMARY);
  });
});
