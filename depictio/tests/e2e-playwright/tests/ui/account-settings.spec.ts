/**
 * Account settings page (/profile) and the admin Settings tab.
 *
 * /profile is one page of collapsible sections, each reachable by URL hash
 * (src/profile/ProfileApp.tsx): account, password, cli-agents, preferences,
 * getting-started, server. The old /cli-agents page now redirects to /profile#cli-agents. The
 * admin Settings tab (/admin/settings) holds the "Version check" group.
 *
 * Nothing here depends on GitHub being reachable: the server section and the
 * version check are asserted only for their frame and controls, never for a
 * release number or a check result.
 */

import { test, expect, getAuthMode } from "@fixtures/auth";

const SECTION_IDS = [
  "account",
  "password",
  "cli-agents",
  "preferences",
  "getting-started",
  "server",
];

// The reader's avatar: Glass draws `profile-key` on the management pages,
// Classic draws `profile-badge` in the sidebar. Each is a plain link.
const AVATAR = "[data-testid='profile-key'], [data-testid='profile-badge']";

const section = (page: import("@playwright/test").Page, id: string) =>
  page.locator(`[data-testid='settings-section-${id}']`);

test.describe("Account settings", () => {
  test("shows the six sections, with Account open", async ({ loginAsUser, page }) => {
    await loginAsUser();
    await page.goto("/profile");

    for (const id of SECTION_IDS) {
      await expect(section(page, id)).toBeVisible({ timeout: 15_000 });
    }
    // Account is open on a first visit: its facts are on screen.
    await expect(page.locator("[data-testid='profile-info-email']")).toBeVisible();
    // The sign-out button sits at the foot of the page.
    await expect(page.locator("[data-testid='logout-button']")).toBeVisible();
  });

  test("a section hash opens that section", async ({ loginAsUser, page }) => {
    const { is_public_mode } = await getAuthMode();
    await loginAsUser();
    await page.goto("/profile#cli-agents");

    await expect(section(page, "cli-agents")).toBeVisible({ timeout: 15_000 });
    // The panel mounts only once its section is open, so seeing it proves the
    // hash opened the section. In public mode it is there but disabled.
    const add = page.locator("[data-testid='add-cli-config-btn']");
    await expect(add).toBeVisible({ timeout: 15_000 });
    if (is_public_mode) await expect(add).toBeDisabled();
    else await expect(add).toBeEnabled();
  });

  test("a hash change on the page opens the named section", async ({ loginAsUser, page }) => {
    await loginAsUser();
    await page.goto("/profile");
    await expect(section(page, "preferences")).toBeVisible({ timeout: 15_000 });

    await page.evaluate(() => {
      window.location.hash = "preferences";
    });
    await expect(page.locator("[data-testid='theme-control']")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("[data-testid='font-size-control']")).toBeVisible();
  });

  test("/cli-agents redirects to /profile#cli-agents", async ({ loginAsUser, page }) => {
    await loginAsUser();
    await page.goto("/cli-agents");

    await expect(page).toHaveURL(/\/profile#cli-agents$/, { timeout: 15_000 });
    await expect(section(page, "cli-agents")).toBeVisible();
    await expect(page.locator("[data-testid='add-cli-config-btn']")).toBeVisible({
      timeout: 15_000,
    });
  });
});

test.describe("Account entry points", () => {
  test("the avatar goes straight to Account settings", async ({ loginAsUser, page }) => {
    await loginAsUser();
    // No tour backdrop over the header, whatever DEPICTIO_DEV_MODE says.
    await page.goto("/dashboards?no-walkthrough=1");

    const avatar = page.locator(AVATAR).first();
    await expect(avatar).toBeVisible({ timeout: 15_000 });
    await expect(avatar).toHaveAttribute("href", "/profile");
    // No intermediate menu: one click lands on the page.
    await avatar.click();
    await expect(page).toHaveURL(/\/profile$/, { timeout: 15_000 });
    await expect(page.locator("[data-testid='account-menu']")).toHaveCount(0);
    await expect(page.locator("[data-testid='account-settings']")).toBeVisible({ timeout: 15_000 });
  });

  test("Getting started holds the tour button", async ({ loginAsUser, page }) => {
    await loginAsUser();
    await page.goto("/profile#getting-started");

    await expect(section(page, "getting-started")).toBeVisible({ timeout: 15_000 });
    await expect(section(page, "getting-started")).toContainText("Getting started");
    await expect(page.locator("[data-testid='getting-started-tour']")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("the tour is switched off by ?no-walkthrough=1: disabled header button and restart", async ({
    loginAsUser,
    page,
  }) => {
    await loginAsUser();
    // `?no-walkthrough=1` is one of the gates the walkthrough host honours, so
    // this holds on every deployment, whatever DEPICTIO_DEV_MODE says.
    await page.goto("/dashboards?no-walkthrough=1");
    await expect(page.locator("[data-testid='new-dashboard-btn']")).toBeVisible({
      timeout: 20_000,
    });
    // Disabled, not hidden: the gap would not say why.
    await expect(page.locator("[data-testid='tour-button']")).toBeDisabled({ timeout: 15_000 });

    await page.goto("/profile?no-walkthrough=1#getting-started");
    await expect(page.locator("[data-testid='getting-started-tour']")).toBeDisabled({
      timeout: 15_000,
    });
  });

  test("the header tour button follows the deployment's walkthrough switch", async ({
    loginAsUser,
    page,
  }) => {
    await loginAsUser();
    await page.goto("/profile#getting-started");
    const restart = page.locator("[data-testid='getting-started-tour']");
    await expect(restart).toBeVisible({ timeout: 15_000 });
    // The button starts disabled while the session loads, so give it a moment
    // to turn on before reading a disabled one as "tours are off".
    let tourOn = true;
    try {
      await expect(restart).toBeEnabled({ timeout: 5_000 });
    } catch {
      tourOn = false;
    }

    await page.goto("/dashboards");
    await expect(page.locator("[data-testid='new-dashboard-btn']")).toBeVisible({
      timeout: 20_000,
    });
    // CI runs with DEPICTIO_DEV_MODE=true, which suppresses the walkthrough
    // (see src/walkthrough/availability.ts): there the header button and the
    // restart are both disabled. On a deployment with tours on, both are
    // live. The two surfaces share one gate, so they must agree.
    const headerTour = page.locator("[data-testid='tour-button']");
    if (tourOn) {
      await expect(headerTour).toBeEnabled({ timeout: 15_000 });
      await expect(headerTour).toHaveAttribute("aria-label", /tour/i);
    } else {
      await expect(headerTour).toBeDisabled({ timeout: 15_000 });
    }
  });
});

test.describe("Admin settings", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "No administrator signs in on a public instance.");
  });

  test("the Settings tab shows the Version check group", async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    await page.goto("/admin/settings");

    await expect(page).toHaveURL(/\/admin\/settings/);
    const group = page.locator("[data-testid='admin-settings-version-check']");
    await expect(group).toBeVisible({ timeout: 20_000 });
    await expect(group).toContainText("Version check");
    // The setting and its actions are always present; whether they are
    // enabled depends on the deployment (env lock, demo mode), so only
    // presence is asserted.
    await expect(page.locator("[data-testid='version-check-switch']")).toBeAttached();
    await expect(page.locator("[data-testid='version-check-save']")).toBeVisible();
    await expect(page.locator("[data-testid='version-check-reset']")).toBeVisible();
    await expect(page.locator("[data-testid='version-check-run']")).toBeVisible();
  });

  test("the tab is reachable from the admin tab bar", async ({ loginAsAdmin, page }) => {
    await loginAsAdmin();
    await page.goto("/admin?no-walkthrough=1");

    await page.locator("[data-testid='admin-tab-settings']").click();
    await expect(page).toHaveURL(/\/admin\/settings/);
    await expect(page.locator("[data-testid='admin-settings-version-check']")).toBeVisible({
      timeout: 20_000,
    });
  });
});
