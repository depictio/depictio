/**
 * Doc screenshots (not an assertion test) — drives the full flow and captures
 * PNGs into docs/screenshots/ for the README + PR. Run with:
 *   pnpm exec playwright test screenshots.spec.ts
 */
import { test } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const goldenCsv = resolve(here, 'golden', 'golden.csv');
const shot = (name: string) => resolve(here, '..', 'docs', 'screenshots', `${name}.png`);

// Opt-in only (run with CAPTURE_SHOTS=1) so CI's `pnpm e2e` doesn't re-capture.
test.skip(!process.env.CAPTURE_SHOTS, 'set CAPTURE_SHOTS=1 to regenerate doc screenshots');

test('capture documentation screenshots', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  // 1) Tool step — a brand-new tool: 2-panel identity/output + source picker.
  //    Use a name that isn't in the catalog so recognition doesn't take over.
  await page.getByLabel('Tool id').fill('mytool');
  await page.getByLabel('Tool name').fill('My Tool');
  await page.getByLabel('Output slug').fill('coverage');
  await page.getByLabel('Path glob').fill('**/mytool/*.tsv');
  await page.screenshot({ path: shot('01-tool'), fullPage: true });

  // 1b) Recognition — retype the id of a tool already in the catalog; the
  //     recognized entry (its outputs + renders) and the two actions appear.
  await page.getByLabel('Tool id').fill('mosdepth');
  await page.getByText('is already in the catalog').waitFor();
  await page.screenshot({ path: shot('01b-recognized'), fullPage: true });

  // Back to the new-tool flow for the remaining shots.
  await page.getByLabel('Tool id').fill('mytool');
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // 2) Fixture step — ag-grid preview of the dropped file.
  await page.locator('input[type="file"]').setInputFiles(goldenCsv);
  await page.getByText('coverage · Int64').waitFor();
  await page.screenshot({ path: shot('02-fixture'), fullPage: true });
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // 3) Add-visualization modal — the component-type grid.
  await page.getByRole('button', { name: 'Add visualization' }).click();
  await page.getByText('Choose a component type').waitFor();
  await page.screenshot({ path: shot('03-component-types') });

  // 4) Figure builder — preview-left / properties-right (set x/y for a plot).
  await page.locator('.cs-type-card', { hasText: 'Figure' }).click();
  await page.getByPlaceholder('Select x axis*...').click();
  await page.getByRole('option', { name: 'log2fc' }).first().click();
  await page.getByPlaceholder('Select y axis*...').click();
  await page.getByRole('option', { name: 'pvalue' }).first().click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: shot('04-figure-builder') });
  await page.getByRole('button', { name: 'Add to output' }).click();

  // 5) Render card — the "user vs developer" tabs.
  await page.getByRole('tab', { name: 'For catalog developers' }).click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: shot('05-render-card'), fullPage: true });
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // 6) Export step — generated files + submit.
  await page.getByText('# yaml-language-server:').waitFor();
  await page.screenshot({ path: shot('06-export'), fullPage: true });
});
