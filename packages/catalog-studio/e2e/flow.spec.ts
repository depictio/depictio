import { test, expect } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const goldenCsv = resolve(here, 'golden', 'golden.csv');

test('author a tool end-to-end and export a zip', async ({ page }) => {
  await page.goto('/');

  // ── Step 0: Tool ──────────────────────────────────────────────────────────
  await page.getByLabel('Tool id').fill('mytool');
  await page.getByLabel('Tool name').fill('My Tool');
  await page.getByLabel('Output slug').fill('results');
  await page.getByLabel('Path glob').fill('**/mytool/*.csv');
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // ── Step 1: Fixture ───────────────────────────────────────────────────────
  await page.locator('input[type="file"]').setInputFiles(goldenCsv);
  // dtype badges prove parsing worked.
  await expect(page.getByText('gene · String')).toBeVisible();
  await expect(page.getByText('coverage · Int64')).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // ── Step 2: Visualizations (depictio component builder in a modal) ──────────
  await page.getByRole('button', { name: 'Add visualization' }).click();
  // The depictio component-type grid renders inside the modal.
  await expect(page.getByText('Add a visualization')).toBeVisible();
  // Pick "Table" (zero-binding) — exercises seed → DesignArea → confirm.
  await page.locator('.cs-type-card', { hasText: 'Table' }).click();
  await page.getByRole('button', { name: 'Add to output' }).click();
  // A Table render card is now listed (catalog-style, with user / developer tabs).
  await expect(page.getByRole('tab', { name: 'For catalog developers' })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // ── Step 3: Export ────────────────────────────────────────────────────────
  await expect(page.getByText('# yaml-language-server:')).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download zip' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('mytool-catalog.zip');
});
