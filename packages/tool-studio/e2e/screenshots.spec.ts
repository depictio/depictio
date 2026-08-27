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

// An nf-core module that is neither in the catalog nor parsed by MultiQC, so the
// import shot shows the importer alone. `kraken2/kraken2` was the obvious pick
// and is the wrong one: `multiqcModuleFor` strips the trailing digit and lands
// on MultiQC's `kraken`, so the yellow advisory covers half the shot. cnvkit
// matches nothing, and its meta.yml declares twelve output channels, which is
// what makes the picker worth photographing.
const NF_CORE_MODULE_URL =
  'https://github.com/nf-core/modules/tree/master/modules/nf-core/cnvkit/batch';

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
  //     recognized entry (its outputs, each with the renders already committed
  //     for it) and the two actions appear. `qiime2` on purpose: it is not a
  //     MultiQC module, so the yellow advisory does not fire over this shot the
  //     way it does for mosdepth, and its eight outputs carry real render
  //     badges rather than "no renders yet".
  await page.getByLabel('Tool id').fill('qiime2');
  const recognized = page.getByText('is already in the catalog');
  await recognized.waitFor();
  // `fullPage` is useless in this app: the AppShell body is its own scroll
  // container, so Playwright's page-height capture still crops at the viewport.
  // Grow the viewport instead, and scroll the panel to the top so the eight
  // outputs and their render badges are all in frame.
  await page.setViewportSize({ width: 1440, height: 1220 });
  // scrollIntoViewIfNeeded only nudges the panel just inside the fold, which
  // leaves the Identity form eating half the frame. Pin the panel's top edge to
  // the top of the viewport instead: this shot is about the recognized entry.
  await recognized.evaluate((el) =>
    el.closest('.mantine-Paper-root')?.scrollIntoView({ block: 'start' }),
  );
  await page.waitForTimeout(700);
  await page.screenshot({ path: shot('01b-recognized') });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(300);

  // 1c) MultiQC advisory — `fastqc` is a MultiQC module but not a catalog tool
  //     of its own, so only the yellow advisory fires, with no recognition
  //     panel competing for the same shot.
  await page.getByLabel('Tool id').fill('fastqc');
  await page.getByText('MultiQC already parses').waitFor();
  await page.screenshot({ path: shot('01c-multiqc'), fullPage: true });

  // 1d) Import from nf-core — paste a module URL, pull its meta.yml in the
  //     browser, and open the output-channel picker the import populates. Kept
  //     last of the Tool-step shots because Import overwrites the whole identity
  //     half of the form, which would otherwise leak a foreign tool name into
  //     `01b` and `01c`. The dropdown is portalled, so this is a viewport shot.
  await page.getByLabel('nf-core module URL').fill(NF_CORE_MODULE_URL);
  await page.getByRole('button', { name: 'Import' }).click();
  // Mantine points the label at both the input and its listbox, so getByLabel is
  // ambiguous here; target the textbox itself.
  const channelPicker = page.getByRole('textbox', { name: 'Output channel' });
  await channelPicker.waitFor({ timeout: 60_000 });
  await channelPicker.click();
  await page.getByRole('option').first().waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({ path: shot('01d-nfcore-import') });
  await page.keyboard.press('Escape');
  await dismissToasts(page);

  // Back to the new-tool flow for the remaining shots. Clearing the visible
  // fields is not enough: Import also sets `homepage` and `biotools_url`, which
  // have no input on this step and would surface in the generated module.yaml in
  // `06-export`. Switching source and back runs the store's full identity reset,
  // which is the only thing that drops them.
  await page.getByLabel('Snakemake wrapper').click();
  await page.getByLabel('nf-core module').click();
  await page.getByLabel('Tool id').fill('mytool');
  await page.getByLabel('Tool name').fill('My Tool');
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
  await dismissToasts(page);
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
