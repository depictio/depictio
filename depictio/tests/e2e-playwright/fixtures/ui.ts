import { Page, expect } from "@playwright/test";

/**
 * Toggle a control by its data-testid: a Mantine Switch, or a plain button
 * standing in for one.
 *
 * Mantine renders a Switch's actual <input> visually hidden (no clickable
 * box), so clicking it directly fails with "element is outside of the
 * viewport" — the associated <label for=...> is the clickable surface (same
 * trick the Cypress suite used with `label[for="theme-switch"]`).
 *
 * Some toggles are a Switch in one chrome style and a button in another: the
 * theme toggle is a Switch in the Classic sidebar and an icon button in the
 * Glass top bar, both under `data-testid="theme-toggle"`. Anything that is not
 * a checkbox input is clicked as it is.
 */
export async function clickMantineSwitch(page: Page, testid: string): Promise<void> {
  const control = page.locator(`[data-testid='${testid}']`);
  await expect(control).toBeAttached();
  const isSwitchInput = await control.evaluate(
    (el) => el instanceof HTMLInputElement && el.type === "checkbox",
  );
  if (!isSwitchInput) {
    await control.click();
    return;
  }
  const id = await control.getAttribute("id");
  if (!id) throw new Error(`Switch input ${testid} has no id to target its label.`);
  await page.locator(`label[for="${id}"]`).first().click();
}
