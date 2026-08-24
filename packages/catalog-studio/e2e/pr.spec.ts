import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const GOLDEN = join(here, 'golden', 'golden.csv');

/**
 * The one-click PR path — fork, branch, blobs, tree, commit, PR — had no
 * coverage at any level, and the OAuth popup made it look untestable. It isn't:
 * the authorize URL can be redirected straight at the app's own callback page,
 * which then postMessages the code back exactly as GitHub's would.
 */
async function routeGitHub(page: Page, baseURL: string) {
  // Routes must live on the CONTEXT, not the page: the OAuth popup is a separate
  // page, and page-level routes would not apply to it.
  const context = page.context();
  const committed: Array<{ path: string; content: string }> = [];
  let prBody = '';

  // GitHub's authorize endpoint → redirect to our real callback page with the
  // state the app generated, so the app's own state check runs for real.
  await context.route('https://github.com/login/oauth/authorize**', async (route) => {
    const state = new URL(route.request().url()).searchParams.get('state') ?? '';
    await route.fulfill({
      status: 302,
      headers: {
        // Absolute: a relative Location on a github.com response would resolve
        // against github.com, not the app.
        location: `${baseURL}oauth-callback.html?code=e2e-code&state=${encodeURIComponent(state)}`,
      },
      body: '',
    });
  });

  await context.route('https://oauth-worker.test/exchange', (route) =>
    route.fulfill({ json: { access_token: 'e2e-token' } }),
  );

  await context.route('https://api.github.com/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    const json = (body: unknown) => route.fulfill({ json: body });

    if (path === '/user') return json({ login: 'e2e-user' });
    if (method === 'POST' && path.endsWith('/forks')) return json({});
    if (path.includes('/git/ref/heads/')) return json({ object: { sha: 'basesha' } });
    if (path.includes('/git/commits/basesha')) return json({ tree: { sha: 'basetree' } });
    if (method === 'POST' && path.endsWith('/git/blobs')) {
      committed.push({ path: '', content: route.request().postDataJSON().content });
      return json({ sha: `blob${committed.length}` });
    }
    if (method === 'POST' && path.endsWith('/git/trees')) {
      const tree = route.request().postDataJSON().tree as Array<{ path: string }>;
      tree.forEach((t, i) => (committed[i].path = t.path));
      return json({ sha: 'newtree' });
    }
    if (method === 'POST' && path.endsWith('/git/commits')) return json({ sha: 'newcommit' });
    if (method === 'POST' && path.endsWith('/git/refs')) return json({});
    if (method === 'PATCH' && path.includes('/git/refs/heads/')) return json({});
    if (method === 'POST' && path.endsWith('/pulls')) {
      prBody = route.request().postDataJSON().body;
      return json({ html_url: 'https://github.com/depictio/depictio/pull/999' });
    }
    return route.fulfill({ status: 500, json: { message: `unhandled ${method} ${path}` } });
  });

  return { committed, prBody: () => prBody };
}

test('signs in and opens a pull request for a new tool', async ({ page, baseURL }) => {
  test.setTimeout(90_000); // OAuth popup + fork poll + six API round-trips
  const gh = await routeGitHub(page, baseURL!);
  await page.goto('/');

  await page.getByLabel('Tool id').fill('e2etool');
  await page.getByLabel('Tool name').fill('E2E Tool');
  await page.getByLabel('Output slug').fill('results');
  await page.getByLabel('Path glob').fill('**/e2etool/*.csv');
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  await page.locator('input[type="file"]').setInputFiles(GOLDEN);
  await expect(page.getByText('gene · String')).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  await page.getByRole('button', { name: 'Add visualization' }).click();
  await page.locator('.cs-type-card', { hasText: 'Table' }).click();
  await page.getByRole('button', { name: 'Add to output' }).click();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  await page.getByRole('button', { name: /Sign in with GitHub|Open pull request/ }).click();
  await expect(page.getByRole('link', { name: /pull\/999/ })).toBeVisible({ timeout: 30_000 });

  // The three files land under the tool folder, with the content the preview showed.
  expect(gh.committed.map((c) => c.path)).toEqual([
    'depictio/catalog/e2etool/module.yaml',
    'depictio/catalog/e2etool/results.yaml',
    'depictio/catalog/e2etool/golden.csv',
  ]);
  expect(gh.committed[1].content).toContain('component: table');
  expect(gh.committed[2].content).toBe(readFileSync(GOLDEN, 'utf8'));
  expect(gh.prBody()).toContain('dev catalog validate');
});


test('appends a visualization to an existing output, rebased on the live file', async ({
  page,
  baseURL,
}) => {
  test.setTimeout(90_000);
  const gh = await routeGitHub(page, baseURL!);

  // The catalog snapshot the app was built with is, by construction, older than
  // the repo. Serve a "live" file carrying a render the snapshot does not have:
  // if the append is rebased on the snapshot, that render disappears.
  const LIVE = `id: mosdepth_genome_coverage
find: {path_glob: "**/mosdepth/*.mosdepth.global.dist.txt"}
fixture: genome_coverage.tsv
renders_as:
  - { id: merged_after_the_snapshot, component: table }
`;
  const YAML_PATH = 'depictio/catalog/mosdepth/genome_coverage.yaml';
  await page
    .context()
    .route(`https://raw.githubusercontent.com/depictio/depictio/main/${YAML_PATH}`, (route) =>
      route.fulfill({ body: LIVE, contentType: 'text/plain' }),
    );
  await page
    .context()
    .route(`https://api.github.com/repos/depictio/depictio/contents/${YAML_PATH}**`, (route) =>
      route.fulfill({ json: { encoding: 'base64', content: Buffer.from(LIVE).toString('base64') } }),
    );

  await page.goto('/');
  await page.getByLabel('Tool id').fill('mosdepth');
  await expect(page.getByText('is already in the catalog')).toBeVisible();
  await page
    .locator('[data-output="genome_coverage"]')
    .getByRole('button', { name: 'Add a visualization here' })
    .click();

  // Append mode jumps straight to Visualizations with the catalog's fixture.
  await page.getByRole('button', { name: 'Add visualization' }).click();
  await page.locator('.cs-type-card', { hasText: 'Table' }).click();
  await page.getByRole('button', { name: 'Add to output' }).click();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // The preview is built on the live file, and says so.
  await expect(page.getByText('Rebased on the current file')).toBeVisible();
  await expect(page.getByText('merged_after_the_snapshot')).toBeVisible();

  await page.getByRole('button', { name: /Sign in with GitHub|Open pull request/ }).click();
  await expect(page.getByRole('link', { name: /pull\/999/ })).toBeVisible({ timeout: 30_000 });

  // Exactly one file, and the render only the live copy had is still in it.
  expect(gh.committed).toHaveLength(1);
  expect(gh.committed[0].path).toBe(YAML_PATH);
  expect(gh.committed[0].content).toContain('merged_after_the_snapshot');
  expect(gh.committed[0].content).toContain('component: table');
  expect(gh.prBody()).toContain('had changed upstream');
});
