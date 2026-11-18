/**
 * The agent surface: everything below goes through `window.toolStudio` and the
 * stable `data-testid`s, never through clicks on visible text. If this spec
 * passes, a script can author, check and export an entry without a person.
 */
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const goldenCsv = readFileSync(join(here, 'golden', 'golden.csv'), 'utf8');

const draft = {
  format: 'depictio-tool-studio/draft@1',
  tool: { id: 'agenttool', name: 'Agent Tool', description: 'Authored by a script.', homepage: 'https://example.org' },
  output: { slug: 'results', path_glob: '**/agent/*.csv' },
  fixture: { fileName: 'golden.csv', content: goldenCsv },
  renders: [
    { component: 'card', column: 'coverage', aggregation: 'average' },
    // effect_size bound to a String column: an error CI would reject.
    { component: 'advanced_viz', kind: 'volcano', roles: { feature_id: 'gene', effect_size: 'sample', significance: 'pvalue' } },
  ],
};

async function api<T>(page: Page, fn: string, ...args: unknown[]): Promise<T> {
  return page.evaluate(
    async ([name, a]) => {
      const ts = window.toolStudio!;
      await ts.ready;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return (ts as any)[name as string](...(a as unknown[]));
    },
    [fn, args] as const,
  );
}

test('an agent loads, validates, fixes and exports a draft without clicking', async ({ page }) => {
  await page.goto('./');
  await page.waitForFunction(() => Boolean(window.toolStudio));

  await api(page, 'load', draft);
  // The UI followed: we are on Export, and the diagnostics are on screen as data.
  await expect(page.getByTestId('diagnostics')).toBeVisible();
  // The Export step's list (the entry panel carries the same rows under entry-diagnostics).
  await expect(page.getByTestId('diagnostics').getByTestId('diagnostic')).toHaveAttribute('data-code', 'render.role_dtype');
  await expect(page.getByTestId('diagnostics').getByTestId('diagnostic')).toHaveAttribute('data-path', 'renders[1]');
  await expect(page.getByTestId('entry-diagnostics')).toHaveAttribute('data-errors', '1');
  await expect(page.getByTestId('download')).toBeDisabled();

  const diags = await api<Array<{ code: string; severity: string }>>(page, 'validateAsync');
  expect(diags.filter((d) => d.severity === 'error').map((d) => d.code)).toEqual(['render.role_dtype']);

  // Fix it through the API: replace the draft with the corrected binding.
  const fixed = structuredClone(draft);
  fixed.renders[1].roles!.effect_size = 'log2fc';
  await api(page, 'load', fixed);
  expect((await api<Array<{ severity: string }>>(page, 'validateAsync')).filter((d) => d.severity === 'error')).toEqual([]);
  await expect(page.getByTestId('checks-pass')).toBeVisible();
  await expect(page.getByTestId('download')).toBeEnabled();

  const files = await api<Record<string, string>>(page, 'exportFiles');
  expect(Object.keys(files).sort()).toEqual(['agenttool/golden.csv', 'agenttool/module.yaml', 'agenttool/results.yaml']);
  expect(files['agenttool/results.yaml']).toContain('effect_size: log2fc');

  // Round-trip the export back in, then share it as a link and open that.
  const res = await api<{ draft: { renders: unknown[] }; notes: string[] }>(page, 'loadFiles', files);
  expect(res.notes).toEqual([]);
  expect(res.draft.renders).toHaveLength(2);
  const link = await api<string>(page, 'link');
  expect(link).toContain('#draft=');

  const fresh = await page.context().newPage();
  await fresh.goto(link);
  await fresh.waitForFunction(() => window.toolStudio?.getDraft().tool.id === 'agenttool');
  await expect(fresh.getByTestId('checks-pass')).toBeVisible();
  expect(new URL(fresh.url()).hash).toBe(''); // consumed, so a reload keeps later edits
});

test('the Export button is blocked by errors until explicitly overridden', async ({ page }) => {
  await page.goto('./');
  await page.waitForFunction(() => Boolean(window.toolStudio));
  await api(page, 'load', draft);
  await expect(page.getByTestId('download')).toBeDisabled();
  await page.getByTestId('export-anyway').click();
  await expect(page.getByTestId('download')).toBeEnabled();
});
