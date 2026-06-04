import { Page, expect } from "@playwright/test";

/**
 * Toggle a Mantine Switch by its input's data-testid.
 *
 * Mantine renders the actual <input> visually hidden (no clickable box), so
 * clicking it directly fails with "element is outside of the viewport" — the
 * associated <label for=...> is the clickable surface (same trick the Cypress
 * suite used with `label[for="theme-switch"]`).
 */
export async function clickMantineSwitch(page: Page, testid: string): Promise<void> {
  const input = page.locator(`[data-testid='${testid}']`);
  await expect(input).toBeAttached();
  const id = await input.getAttribute("id");
  if (!id) throw new Error(`Switch input ${testid} has no id to target its label.`);
  await page.locator(`label[for="${id}"]`).first().click();
}
