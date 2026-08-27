/**
 * Doc screenshots (not an assertion test) — drives the full flow and captures
 * PNGs into docs/screenshots/ for the README + PR. Run with:
 *   CAPTURE_SHOTS=1 pnpm exec playwright test screenshots.spec.ts
 *
 * The last shot (`07-pr-opened`) opens a REAL pull request against
 * depictio/depictio, so it is behind a second opt-in and needs a dev build
 * carrying a token:
 *   CAPTURE_SHOTS=1 LIVE_PR=1 PW_DEV_SERVER=1 VITE_GH_TOKEN=$(gh auth token) \
 *     pnpm exec playwright test screenshots.spec.ts -g "pull request"
 * Close the PR afterwards.
 */
import { test, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const goldenCsv = resolve(here, 'golden', 'golden.csv');
const shot = (name: string) => resolve(here, '..', 'docs', 'screenshots', `${name}.png`);

// A real tabular output with a header row, served with `Access-Control-Allow-Origin: *`
// — i.e. one of the corpora the Fixture step points at. Given as a github.com blob
// link on purpose, so the shot also exercises the rewrite to raw.githubusercontent.com.
const FIXTURE_URL =
  'https://github.com/MultiQC/test-data/blob/main/data/modules/kraken/bracken/v2.6.0/bracken_species_abundances.tsv';

/** Notifications stack in the corner and outlive the step that raised them, so
 *  a later shot inherits toasts about a file it is no longer showing. */
async function dismissToasts(page: Page) {
  const closes = page.locator('[class*="Notification-closeButton"]');
  for (let left = await closes.count(); left > 0; left -= 1) {
    await closes.first().click({ timeout: 2_000 }).catch(() => {});
  }
  await page.waitForTimeout(400);
}

// Opt-in only (run with CAPTURE_SHOTS=1) so CI's `pnpm e2e` doesn't re-capture.
test.skip(!process.env.CAPTURE_SHOTS, 'set CAPTURE_SHOTS=1 to regenerate doc screenshots');

test('capture documentation screenshots', async ({ page }) => {
  // Twelve steps, one cross-origin fetch and several settle waits: the 30 s
  // default is not enough for a full pass.
  test.setTimeout(120_000);
  // 0) Start screen — what a catalog entry is, the four steps, and what it does
  //    not cover. Taller viewport for this one shot, set before navigating: the
  //    cascade plus the scope pair overflows 900 px and the pinned footer then
  //    covers the Start button, and resizing after load re-renders the step
  //    tiles before their icons have resolved.
  await page.setViewportSize({ width: 1440, height: 1040 });
  await page.goto('./');
  await page.getByTestId('start').waitFor();
  await page.waitForTimeout(500);
  await page.screenshot({ path: shot('00-start'), fullPage: true });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByTestId('start').click();

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

  // 1c) MultiQC advisory — `fastqc` is a MultiQC module but not a catalog tool
  //     of its own, so only the yellow advisory fires, with no recognition
  //     panel competing for the same shot.
  await page.getByLabel('Tool id').fill('fastqc');
  await page.getByText('MultiQC already parses').waitFor();
  await page.screenshot({ path: shot('01c-multiqc'), fullPage: true });

  // Back to the new-tool flow for the remaining shots.
  await page.getByLabel('Tool id').fill('mytool');
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // 2b) Fixture from a URL — captured before the drop, since fetching replaces
  //     whatever is loaded and the rest of the flow binds the golden columns.
  await page.getByLabel('Output file URL').fill(FIXTURE_URL);
  await page.getByRole('button', { name: 'Fetch' }).click();
  await page.getByText('fraction_total_reads · Float64').first().waitFor({ timeout: 60_000 });
  await page.screenshot({ path: shot('02b-fetch-url'), fullPage: true });
  await dismissToasts(page);

  // 2) Fixture step — ag-grid preview of the dropped file.
  await page.locator('input[type="file"]').setInputFiles(goldenCsv);
  await page.getByText('coverage · Int64').waitFor();
  await page.screenshot({ path: shot('02-fixture'), fullPage: true });
  await dismissToasts(page);
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  // 3) Add-visualization modal — the component-type grid. Let the modal finish
  //    its fade, or the tiles are captured half-transparent.
  await page.getByRole('button', { name: 'Add visualization' }).click();
  await page.getByText('Choose a component type').waitFor();
  await page.waitForTimeout(500);
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

  // 6) Export step — generated files + submit. Park the cursor first: Next sits
  //     under the stepper, whose tooltip otherwise hangs over the shot.
  await page.getByText('# yaml-language-server:').first().waitFor();
  await page.mouse.move(720, 700);
  await page.waitForTimeout(400);
  await page.screenshot({ path: shot('06-export'), fullPage: true });
});

test('capture the opened pull request', async ({ page }) => {
  test.skip(
    !process.env.LIVE_PR,
    'set LIVE_PR=1 (with PW_DEV_SERVER=1 and VITE_GH_TOKEN) to open a real PR',
  );
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('./');
  await page.getByTestId('start').click();

  // An obviously throwaway identity: this really does land on depictio/depictio.
  await page.getByLabel('Tool id').fill('tool_studio_demo');
  await page.getByLabel('Tool name').fill('Tool Studio Demo');
  await page.getByLabel('Output slug').fill('results');
  await page.getByLabel('Path glob').fill('**/tool_studio_demo/*.csv');
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  await page.locator('input[type="file"]').setInputFiles(goldenCsv);
  await page.getByText('coverage · Int64').waitFor();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  await page.getByRole('button', { name: 'Add visualization' }).click();
  await page.locator('.cs-type-card', { hasText: 'Figure' }).click();
  await page.getByPlaceholder('Select x axis*...').click();
  await page.getByRole('option', { name: 'log2fc' }).first().click();
  await page.getByPlaceholder('Select y axis*...').click();
  await page.getByRole('option', { name: 'pvalue' }).first().click();
  await page.getByRole('button', { name: 'Add to output' }).click();
  await page.getByRole('button', { name: 'Next', exact: true }).click();

  await page.getByRole('button', { name: /Open pull request|Sign in with GitHub/ }).click();
  const link = page.getByRole('link', { name: 'View pull request' });
  await link.waitFor({ timeout: 150_000 });
  await page.screenshot({ path: shot('07-pr-opened'), fullPage: true });
  console.log(`LIVE_PR opened: ${await link.getAttribute('href')}`);
});

test('capture the pull request on GitHub', async ({ page }) => {
  // Separate from the run that opens it, and pointed at a URL, so re-taking this
  // shot does not mean opening a second pull request:
  //   CAPTURE_SHOTS=1 PR_URL=https://github.com/depictio/depictio/pull/1004 \
  //     pnpm exec playwright test screenshots.spec.ts -g "on GitHub"
  const prUrl = process.env.PR_URL;
  test.skip(!prUrl, 'set PR_URL to the pull request to photograph');
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(prUrl!, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: /Add catalog tool/ }).waitFor();
  await page.waitForTimeout(2_000);
  await page.screenshot({ path: shot('08-github-pr') });
});
