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
  // Both module.yaml and <output>.yaml carry a (per-shape) schema header now,
  // and Mantine keeps both tab panels mounted — so match the first.
  await expect(page.getByText('# yaml-language-server:').first()).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download zip' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('mytool-catalog.zip');
});

test('recognition routes an existing tool to a new output', async ({ page }) => {
  await page.goto('/');

  // ── Step 0: identify a tool already in the catalog → recognized panel ───────
  await page.getByLabel('Tool id').fill('mosdepth');
  await expect(page.getByText('is already in the catalog')).toBeVisible();
  // Route: add a NEW output to the existing tool.
  await page.getByRole('button', { name: 'Add a new output to this tool' }).click();
  await expect(page.getByText('Adding a new output to mosdepth')).toBeVisible();
  // Author the new output (a slug that doesn't collide with mosdepth's existing ones).
  await page.getByLabel('Output slug').fill('custom_track');
  await page.getByLabel('Path glob').fill('**/mosdepth/*.custom.tsv');
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // ── Step 1: Fixture (a new output brings its own) ───────────────────────────
  await page.locator('input[type="file"]').setInputFiles(goldenCsv);
  await expect(page.getByText('coverage · Int64')).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // ── Step 2: add a Table render ──────────────────────────────────────────────
  await page.getByRole('button', { name: 'Add visualization' }).click();
  await page.locator('.cs-type-card', { hasText: 'Table' }).click();
  await page.getByRole('button', { name: 'Add to output' }).click();
  await expect(page.getByRole('tab', { name: 'For catalog developers' })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // ── Step 3: Export — only the new <slug>.yaml (module.yaml is untouched) ─────
  await expect(page.getByText('id: mosdepth_custom_track')).toBeVisible();
  await expect(page.getByRole('tab', { name: 'module.yaml' })).toHaveCount(0);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download zip' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('mosdepth-custom_track.zip');
});
