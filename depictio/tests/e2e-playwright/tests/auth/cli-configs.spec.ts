/**
 * Port of:
 *   cypress/e2e/auth/standard/create-cli-config.cy.js
 *   cypress/e2e/auth/standard/auth-account-management.cy.js (token part)
 *
 * React-stack route is /cli-agents (was /cli_configs in Dash). Full
 * lifecycle: create → YAML shown once → listed → delete (type-"delete"
 * confirmation gate).
 *
 * Skipped only in public mode, where the add button is disabled
 * (CliAgentsApp.isAddDisabled). In single-user mode the auto-provisioned
 * admin can manage CLI configs.
 */

import { test, expect, getAuthMode } from "@fixtures/auth";

test.describe("CLI Configurations", () => {
  test.beforeEach(async () => {
    const { is_public_mode } = await getAuthMode();
    test.skip(is_public_mode, "CLI config creation is disabled in public mode.");
  });

  test("creates, displays and deletes a CLI configuration", async ({
    loginAsUser,
    page,
  }) => {
    await loginAsUser();
    await page.goto("/cli-agents");

    const addBtn = page.locator("[data-testid='add-cli-config-btn']");
    await expect(addBtn).toBeVisible({ timeout: 15_000 });
    await expect(addBtn).toBeEnabled();
    await addBtn.click();

    // Create modal: name the config and save.
    const createModal = page.locator("[data-testid='create-cli-token-modal']");
    await expect(createModal).toBeVisible();
    const configName = `e2e-cli-config-${Date.now()}`;
    await createModal.locator("[data-testid='cli-config-name-input']").fill(configName);
    await createModal.locator("[data-testid='save-cli-config-btn']").click();

    // Display modal: the generated YAML config is shown exactly once.
    const yaml = page.locator("[data-testid='agent-config-yaml']");
    await expect(yaml).toBeVisible({ timeout: 15_000 });
    await expect(yaml).toContainText("base_url");

    // Close the display modal (Mantine default close button).
    await page.locator(".mantine-Modal-close").click();

    // The new configuration appears in the list.
    await expect(page.locator("body")).toContainText(configName, {
      timeout: 10_000,
    });

    // Delete it: confirm-by-typing-"delete" gate.
    await page
      .locator(".mantine-Paper-root", { hasText: configName })
      .getByRole("button", { name: /delete/i })
      .click();

    const confirmBtn = page.locator("[data-testid='confirm-delete-token-btn']");
    await expect(confirmBtn).toBeVisible();
    await expect(confirmBtn).toBeDisabled(); // gate: disabled until typed
    await page.locator("[data-testid='delete-confirm-input']").fill("delete");
    await expect(confirmBtn).toBeEnabled();
    await confirmBtn.click();

    // The confirm modal closes on success…
    await expect(confirmBtn).toBeHidden({ timeout: 10_000 });
    // …and the configuration is gone from the list (scoped to the token
    // papers — notifications also mention the name and would race a
    // whole-body assertion).
    await expect(
      page.locator(".mantine-Paper-root", { hasText: configName }),
    ).toHaveCount(0, { timeout: 10_000 });
  });
});
