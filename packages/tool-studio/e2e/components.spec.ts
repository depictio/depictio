/**
 * Every component type authored through depictio's own builder, with a preview
 * that actually draws — and not one request to a backend that isn't there.
 *
 * This is the suite the previous one didn't have: `flow.spec.ts` only ever
 * opened the Table builder, which is the one type with nothing to configure and
 * nothing to fetch. Cards, interactive controls and advanced viz went to
 * production untested, and all three were broken — the card strip 404'd, the
 * slider was a lookalike, the advanced-viz picker was a different menu.
 */
import { test, expect, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const fixture = resolve(here, 'golden', 'card_metrics.csv');

/** Requests to depictio's API. There is no backend: any one of these is a
 *  preview reaching for a server, which is what "Preview unavailable: Failed to
 *  fetch card metric: 404" was. */
function trackApiCalls(page: Page): string[] {
  const calls: string[] = [];
  page.on('request', (req) => {
    if (req.url().includes('/depictio/api/')) calls.push(req.url());
  });
  return calls;
}

/** A Mantine `Select` input by its label.
 *
 *  `getByLabel` matches both the input and the listbox it labels, and after a
 *  few open/close cycles the portalled listbox can come first in DOM order — so
 *  `.first()` starts resolving to something unclickable. Filtering to the input
 *  itself is unambiguous whatever the portal does. */
function selectByLabel(page: Page, label: string) {
  return page.getByLabel(label).locator('xpath=self::input');
}

async function openBuilder(page: Page, type: string) {
  await page.getByRole('button', { name: 'Add visualization' }).click();
  // By the tile's own label, not its text: the Figure tile's description reads
  // "Interactive data visualizations", so `hasText` matches two tiles.
  await page.getByRole('button', { name: type, exact: true }).click();
}

/** Tool + fixture, up to the Visualizations step. */
async function reachVisualizations(page: Page) {
  await page.goto('/');
  // The app opens on the start screen (what a catalog entry is, and the four
  // steps); the wizard is behind it.
  await page.getByTestId('start').click();
  await page.getByLabel('Tool id').fill('demotool');
  await page.getByLabel('Tool name').fill('Demo Tool');
  await page.getByLabel('Output slug').fill('metrics');
  await page.getByLabel('Path glob').fill('**/demotool/*.csv');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles(fixture);
  await expect(page.getByText('coverage · Float64')).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
}

test('a multi-metric card previews its strip, with no backend call', async ({ page }) => {
  const apiCalls = trackApiCalls(page);
  await reachVisualizations(page);
  await openBuilder(page, 'Card');

  await selectByLabel(page, 'Select your column').click();
  await page.getByRole('option', { name: 'coverage (float64)' }).click();
  await selectByLabel(page, 'Select your aggregation method').click();
  await page.getByRole('option', { name: 'Average', exact: true }).click();

  // Each numeric layout is a `fetchCardMetric` call — the exact path that 404'd.
  for (const layout of [
    'Histogram sparkline',
    'Threshold',
    'Completeness',
    'Uniqueness',
  ]) {
    await selectByLabel(page, 'Multi-metric style').click();
    await page.getByRole('option', { name: new RegExp(`^${layout}`) }).click();
    await expect(page.getByText(/Preview unavailable/)).toHaveCount(0);
  }

  // A breakdown layout needs the categorical column picker, which was empty
  // while the fixture reported polars-cased dtypes ('String' vs 'object').
  await selectByLabel(page, 'Multi-metric style').click();
  await page.getByRole('option', { name: /^Top-N bars/ }).click();
  await expect(selectByLabel(page, 'Breakdown column')).toHaveValue(/lineage/);
  // The strip renders the real distribution, not a placeholder.
  await expect(page.getByText('B.1.1.7').first()).toBeVisible();

  await page.getByRole('button', { name: 'Add to output' }).click();
  await expect(page.getByRole('tab', { name: 'For catalog developers' })).toBeVisible();
  expect(apiCalls).toEqual([]);
});

test('an interactive control previews as depictio renders it', async ({ page }) => {
  const apiCalls = trackApiCalls(page);
  await reachVisualizations(page);
  await openBuilder(page, 'Interactive');

  await selectByLabel(page, 'Select your column').click();
  await page.getByRole('option', { name: 'coverage (float64)' }).click();
  await selectByLabel(page, 'Select your interactive component').click();
  await page.getByRole('option', { name: 'Range slider' }).click();

  // depictio's own RangeSliderRenderer: its default title, and marks built by
  // `buildNumericScale` off the column's real bounds.
  await expect(page.getByText('RangeSlider on coverage')).toBeVisible();
  await expect(page.getByText('12.5', { exact: true })).toBeVisible();
  await expect(page.getByText('250', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Add to output' }).click();
  // The render carries the widget + column now — it used to export `{component:
  // interactive}`, which depictio cannot instantiate.
  await page.getByRole('tab', { name: 'For catalog developers' }).click();
  await expect(page.getByText(/interactive_type: RangeSlider/)).toBeVisible();
  await expect(page.getByText(/column_name: coverage/)).toBeVisible();
  expect(apiCalls).toEqual([]);
});

test('advanced viz offers depictio\'s ranked kind picker and renders a bound kind', async ({
  page,
}) => {
  const apiCalls = trackApiCalls(page);
  await reachVisualizations(page);
  await openBuilder(page, 'Advanced viz');

  // depictio's picker: every kind, described, scored, split into recommended
  // and the rest. The Studio used to show a bare alphabetical Select.
  await expect(page.getByText('Volcano plot')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Effect size vs significance')).toBeVisible();
  // Ranked, not alphabetised: every kind carries a fit score.
  await expect(page.getByText(/%\s*fit/i).first()).toBeVisible();

  // The kind tiles are clickable Papers, not buttons.
  await page.getByText('Volcano plot', { exact: true }).click();
  await expect(page.getByText('Column bindings')).toBeVisible();

  // Every required role is pre-filled from the ranked candidates the
  // suggestion endpoint returns — the Studio computes that ranking itself, so
  // an empty schema or the wrong dtype vocabulary would leave these blank.
  const binding = (role: string) => page.getByLabel(role).locator('xpath=self::input');
  await expect(binding('effect_size')).toHaveValue(/Float64/);
  await expect(binding('significance')).toHaveValue(/Float64/);
  await expect(binding('feature_id')).toHaveValue(/String/);

  // Rebind one by hand: the dropdown offers the fixture's columns with their
  // polars dtypes, exact matches before castable ones.
  await binding('feature_id').click();
  await page.getByRole('option', { name: 'sample : String' }).click();
  await expect(binding('feature_id')).toHaveValue('sample : String');

  // Unlike the figure and interactive builders, the advanced-viz dialog has no
  // preview pane of its own: picker, bindings table, role selects, buttons. The
  // renderer only mounts in the render card, so the plot assertion belongs after
  // the render is added, not inside the dialog.
  await page.getByRole('button', { name: 'Add to output' }).click();

  // ComponentRenderer lazy-mounts advanced viz on view, so bring the card into
  // frame the way a user landing back on the list would.
  await page.getByText('How this renders on a dashboard.').first().scrollIntoViewIfNeeded();
  // The real VolcanoRenderer draws a plotly figure from the shim's rows.
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible({ timeout: 20_000 });
  expect(apiCalls).toEqual([]);
});

test('a table previews at the size it would have on a dashboard', async ({ page }) => {
  await reachVisualizations(page);
  await openBuilder(page, 'Table');
  await page.getByRole('button', { name: 'Add to output' }).click();

  // depictio gives a new table the full 8-column width and 5 rows of grid
  // height; the preview is that box, not an arbitrary rectangle.
  const preview = page.locator('[data-studio-preview]').first();
  await expect(preview).toBeVisible();
  const box = await preview.boundingBox();
  expect(box?.height).toBeCloseTo(5 * 100 + 4 * 4, 0);
});
