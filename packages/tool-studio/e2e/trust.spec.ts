/**
 * Code from a `#draft=` link is shown, not run. Python runs under Pyodide in
 * the page itself, so a link carrying a code-mode figure used to execute
 * whoever's code it was the moment the Visualizations step drew it. The
 * snippet below sets `window.__ran` (a harmless side effect any real payload
 * could swap for reading storage); it must stay unset until the person clicks
 * "Run this code".
 *
 * The Pyodide CDN and PyPI are served from node_modules/pyodide when a file is
 * there (the npm package ships the core; wheels are only there once cached by a
 * local run), and fetched from the network otherwise. After the click the test
 * asserts the engine starts loading, which the core alone proves; it does not
 * wait for pandas + plotly, which a fresh CI checkout does not have locally.
 */
import { test, expect, type Page } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const here = dirname(fileURLToPath(import.meta.url));
const PYODIDE_DIR = join(here, '..', 'node_modules', 'pyodide');
const goldenCsv = readFileSync(join(here, 'golden', 'golden.csv'), 'utf8');

const CODE = ['import js', 'js.window.__ran = True', 'fig = px.bar(df, x="gene", y="coverage")'].join('\n');

const linkDraft = {
  format: 'depictio-tool-studio/draft@1',
  tool: { id: 'linktool', name: 'Link Tool', description: 'From a link.', homepage: 'https://example.org' },
  output: { slug: 'results', path_glob: '**/link/*.csv' },
  fixture: { fileName: 'golden.csv', content: goldenCsv },
  renders: [{ component: 'figure', code: CODE }],
};

/** What toolStudio.link() produces: gzip + base64url of the draft JSON. */
const token = (draft: unknown) => gzipSync(Buffer.from(JSON.stringify(draft))).toString('base64url');

const TYPES: Record<string, string> = {
  '.wasm': 'application/wasm',
  '.mjs': 'text/javascript',
  '.js': 'text/javascript',
  '.json': 'application/json',
};

/** Serve the Pyodide CDN + PyPI from the local package; count what is asked. */
async function routePyodide(page: Page): Promise<string[]> {
  const asked: string[] = [];
  await page.route(/^https:\/\/(cdn\.jsdelivr\.net|files\.pythonhosted\.org)\//, async (route) => {
    const name = route.request().url().split('?')[0].split('/').pop()!;
    asked.push(name);
    const file = join(PYODIDE_DIR, name);
    if (!existsSync(file)) return route.continue();
    await route.fulfill({
      status: 200,
      body: readFileSync(file),
      headers: {
        'content-type': TYPES[name.slice(name.lastIndexOf('.'))] ?? 'application/octet-stream',
        'access-control-allow-origin': '*',
      },
    });
  });
  return asked;
}

test('a #draft= link with a code figure runs nothing until "Run this code"', async ({ page }) => {
  test.setTimeout(90_000);
  const asked = await routePyodide(page);
  await page.goto(`./#draft=${token(linkDraft)}`);
  await page.waitForFunction(() => window.toolStudio?.getDraft().tool.id === 'linktool');
  await page.evaluate(() => window.toolStudio!.goTo(2));

  const card = page.getByTestId('untrusted-code');
  await expect(card).toBeVisible();
  await expect(card).toContainText('js.window.__ran = True');
  // Give a would-be auto-run every chance to start.
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => (window as unknown as { __ran?: boolean }).__ran)).toBeUndefined();
  expect(asked.filter((n) => /pyodide/.test(n))).toEqual([]);
  // Nothing the link carried is trusted on the way back out either.
  expect(JSON.stringify(await page.evaluate(() => window.toolStudio!.getDraft()))).not.toContain('_untrusted');

  await page.getByTestId('run-untrusted').click();
  await expect(card).toHaveCount(0);
  // The click, and only the click, starts the Python engine for this code.
  await expect.poll(() => asked.some((n) => /^pyodide\.(mjs|asm\.wasm)$/.test(n)), { timeout: 60_000 }).toBe(true);
});

test('a #draft= link keeps the draft it replaced, and restores it', async ({ page }) => {
  await page.goto('./');
  await page.waitForFunction(() => Boolean(window.toolStudio));
  await page.evaluate(async () => {
    const ts = window.toolStudio!;
    await ts.ready;
    ts.load({
      format: 'depictio-tool-studio/draft@1',
      tool: { id: 'mine', name: 'Mine', source: 'nf-core' },
      output: { slug: 'o', path_glob: '*.csv' },
      renders: [{ component: 'table' }],
    });
  });

  // A query change makes this a real navigation, so main.tsx reads the hash.
  await page.goto(`./?from=link#draft=${token({ ...linkDraft, renders: [{ component: 'table' }] })}`);
  await expect(page.getByTestId('draft-backup')).toBeVisible();
  expect(await page.evaluate(() => window.toolStudio!.getDraft().tool.id)).toBe('linktool');

  await page.getByTestId('restore-backup').click();
  await expect(page.getByTestId('draft-backup')).toHaveCount(0);
  expect(await page.evaluate(() => window.toolStudio!.getDraft().tool.id)).toBe('mine');
});
