/**
 * Doc screenshots (not an assertion test): drives the Studio and captures PNGs
 * into test-results/screenshots/ (gitignored: the images live in depictio-docs,
 * not in this repo), once per colour scheme (`<name>_light.png`,
 * `<name>_dark.png`), for the depictio-docs Tool Studio page. Run with:
 *   CAPTURE_SHOTS=1 pnpm exec playwright test screenshots.spec.ts
 *
 * The data is real: the table route authors Bracken from its nf-core module and
 * a species-abundance file from MultiQC's test-data; the recipe and the several
 * outputs use the committed macs2 entry, its recipes and its fixtures. The
 * recipe test downloads Pyodide + polars on its first run.
 *
 * The last two tests are opt-in. `pull request` opens a REAL pull request
 * against depictio/depictio, and needs a dev build carrying a token:
 *   CAPTURE_SHOTS=1 LIVE_PR=1 PW_DEV_SERVER=1 VITE_GH_TOKEN=$(gh auth token) \
 *     pnpm exec playwright test screenshots.spec.ts -g "pull request"
 * Close the PR afterwards.
 */
import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const goldenCsv = resolve(here, 'golden', 'golden.csv');
const catalogDir = resolve(here, '..', '..', '..', 'depictio', 'catalog');
const png = (name: string) => resolve(here, '..', 'test-results', 'screenshots', `${name}.png`);

// A real tabular output, served with `Access-Control-Allow-Origin: *` (one of
// the corpora the Fixture step points at). Given as a github.com blob link on
// purpose, so the shot also exercises the rewrite to raw.githubusercontent.com.
const FIXTURE_URL =
  'https://github.com/MultiQC/test-data/blob/main/data/modules/kraken/bracken/v2.6.0/bracken_species_abundances.tsv';

// Neither tool is in the catalog nor a MultiQC module, so no recognition panel
// or advisory competes with the import. Bracken is the tool the table route
// authors, but its meta.yml types every output as `map`, which the picker
// (file channels only) skips; centrifuge, from the same metagenomics corner,
// declares its file channels properly and is what the picker shot shows.
const NF_CORE_MODULE_URL = 'https://github.com/nf-core/modules/tree/master/modules/nf-core/bracken/bracken';
const NF_CORE_PICKER_URL = 'https://github.com/nf-core/modules/tree/master/modules/nf-core/centrifuge/centrifuge';

/** The committed macs2 files a test loads, keyed the way `loadFiles` takes them. */
function macs2(...names: string[]): Record<string, string> {
  return Object.fromEntries(names.map((n) => [`macs2/${n}`, readFileSync(resolve(catalogDir, 'macs2', n), 'utf8')]));
}

/** Raw MACS2 narrowPeak files, one per sample, rebuilt from the committed
 *  fixture (the recipe's output): headerless BED6+4, as `macs2 callpeak` writes
 *  them, so the recipe returns those same peaks. */
function narrowPeaks(samples: string[]): Array<{ name: string; mimeType: string; buffer: Buffer }> {
  const [header, ...rows] = readFileSync(resolve(catalogDir, 'macs2', 'peaks.tsv'), 'utf8').trim().split('\n');
  const col = Object.fromEntries(header.split('\t').map((c, i) => [c, i]));
  return samples.map((sample) => {
    const lines = rows
      .map((r) => r.split('\t'))
      .filter((r) => r[col.sample] === sample)
      .map((r) =>
        [
          r[col.chr],
          r[col.start],
          r[col.end],
          r[col.peak_id],
          r[col.score],
          '.',
          r[col.fold_enrichment],
          r[col.neg_log10_pvalue],
          r[col.neg_log10_qvalue],
          String(Number(r[col.summit]) - Number(r[col.start]) - 1),
        ].join('\t'),
      );
    return { name: `${sample}_peaks.narrowPeak`, mimeType: 'text/plain', buffer: Buffer.from(lines.join('\n') + '\n') };
  });
}

/** Notifications stack in the corner and outlive the step that raised them, so
 *  a later shot inherits toasts about a file it is no longer showing. */
async function dismissToasts(page: Page) {
  const closes = page.locator('[class*="Notification-closeButton"]');
  for (let left = await closes.count(); left > 0; left -= 1) {
    await closes.first().click({ timeout: 2_000 }).catch(() => {});
  }
  await page.waitForTimeout(400);
}

/** The step canvas is its own scroll container (so `fullPage` cannot help):
 *  scroll it back to the top, where the stepper and the outputs bar are. */
async function toTop(page: Page) {
  await page.evaluate(() => document.querySelector('main')?.scrollTo(0, 0));
  await page.waitForTimeout(300);
}

/** Scroll the step canvas so `selector`'s top edge sits `offset` px from the top. */
async function scrollTo(page: Page, selector: string, offset = 90) {
  await page.evaluate(
    ([sel, off]) => {
      const main = document.querySelector('main');
      const el = document.querySelector(sel as string);
      if (!main || !el) return;
      main.scrollTop += el.getBoundingClientRect().top - (off as number);
    },
    [selector, offset] as const,
  );
  await page.waitForTimeout(400);
}

/** Call `window.toolStudio[fn](...args)` once the app is ready. */
async function api(page: Page, fn: string, ...args: unknown[]) {
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

/** Size the viewport before navigating: resizing after load re-renders the
 *  start screen's step tiles before their icons have resolved. */
async function open(page: Page, width = 1440, height = 1000) {
  await page.setViewportSize({ width, height });
  await page.goto('./');
  await page.waitForFunction(() => Boolean(window.toolStudio));
}

// Opt-in only (run with CAPTURE_SHOTS=1) so CI's `pnpm e2e` doesn't re-capture.
test.skip(!process.env.CAPTURE_SHOTS, 'set CAPTURE_SHOTS=1 to regenerate doc screenshots');

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`${scheme} scheme`, () => {
    // Mantine follows prefers-color-scheme (defaultColorScheme "auto").
    test.use({ colorScheme: scheme });
    const shot = (page: Page, name: string) => page.screenshot({ path: png(`${name}_${scheme}`) });

    test(`the table route, Bracken (${scheme})`, async ({ page }) => {
      test.setTimeout(180_000);
      // 0) Start screen.
      await open(page);
      await page.getByTestId('start').waitFor();
      await page.waitForTimeout(500);
      await shot(page, '00-start');
      await page.getByTestId('start').click();

      // 1b) Recognition: the id of a tool already in the catalog. `qiime2` is
      //     not a MultiQC module (no advisory over the shot) and its eight
      //     outputs carry real render badges.
      //     The banner's "Show the entry" scrolls to it, under the identity form.
      await page.getByLabel('Tool id').fill('qiime2');
      await page.getByText('is already in the catalog').waitFor();
      await page.setViewportSize({ width: 1440, height: 1180 });
      await scrollTo(page, '#recognized-tool', 100);
      await shot(page, '01b-recognized');
      await page.setViewportSize({ width: 1440, height: 1000 });

      // 1c) MultiQC advisory: `fastqc` is a MultiQC module, not a catalog tool.
      await page.getByLabel('Tool id').fill('fastqc');
      await page.getByText('MultiQC already parses').waitFor();
      await toTop(page);
      await shot(page, '01c-multiqc');
      await page.getByLabel('Tool id').fill('');

      // 1d) Import from nf-core: pull a meta.yml in the browser and open the
      //     output-channel picker it populates (portalled, so this is a
      //     viewport shot).
      await page.getByLabel('nf-core module URL').fill(NF_CORE_PICKER_URL);
      await page.getByRole('button', { name: 'Import' }).click();
      const channelPicker = page.getByRole('textbox', { name: 'Output channel' });
      await channelPicker.waitFor({ timeout: 60_000 });
      await dismissToasts(page);
      await toTop(page);
      await channelPicker.click();
      await page.getByRole('option').first().waitFor();
      await page.waitForTimeout(400);
      await shot(page, '01d-nfcore-import');
      await page.keyboard.press('Escape');

      // 1) Bracken's identity from its module (an Import overwrites the
      //    identity), the output named after the abundance file.
      await page.getByLabel('nf-core module URL').fill(NF_CORE_MODULE_URL);
      await page.getByRole('button', { name: 'Import' }).click();
      await expect(page.getByLabel('Tool name')).toHaveValue('bracken', { timeout: 60_000 });
      await page.getByLabel('Tool name').fill('Bracken');
      await page.getByLabel('Output slug').fill('species_abundance');
      await page.getByLabel('Path glob').fill('**/bracken/*.bracken.tsv');
      await dismissToasts(page);
      await toTop(page);
      await shot(page, '01-tool');
      await page.getByTestId('next').click();

      // 2) Fixture: fetch the real abundance table from a URL.
      await page.getByLabel('Output file URL').fill(FIXTURE_URL);
      await page.getByRole('button', { name: 'Fetch' }).click();
      await page.getByText('fraction_total_reads · Float64').first().waitFor({ timeout: 60_000 });
      await dismissToasts(page);
      await toTop(page);
      await shot(page, '02-fixture');
      await scrollTo(page, 'input[placeholder^="https://nf-core-awsmegatests"]', 160);
      await shot(page, '02b-fetch-url');
      await page.getByTestId('next').click();

      // 3) Add-visualization modal: the component-type grid. Let the modal
      //    finish its fade, or the tiles are captured half-transparent.
      await page.getByRole('button', { name: 'Add visualization' }).click();
      await page.getByText('Choose a component type').waitFor();
      await page.waitForTimeout(600);
      await shot(page, '03-component-types');

      // 4) Figure builder, seeded from the fixture.
      await page.locator('.cs-type-card', { hasText: 'Figure' }).click();
      //    Bracken's re-estimate against Kraken's own count, both on log axes:
      //    the 196 species span six orders of magnitude.
      await page.getByPlaceholder('Select x axis*...').click();
      await page.getByRole('option', { name: /^kraken_assigned_reads / }).first().click();
      await page.getByPlaceholder('Select y axis*...').click();
      await page.getByRole('option', { name: /^new_est_reads / }).first().click();
      await page.getByText('Advanced Options', { exact: true }).click();
      // The checkbox's own label is its description text.
      await page.getByText(/^Plot the X axis on a logarithmic/).click();
      await page.getByText(/^Plot the Y axis on a logarithmic/).click();
      await expect(page.getByRole('checkbox', { name: /^Plot the Y axis on a logarithmic/ })).toBeChecked();
      await page.getByText('Advanced Options', { exact: true }).click();
      await page.waitForTimeout(4_000);
      await shot(page, '04-figure-builder');
      await page.getByTestId('add-to-output').click();

      // 5) Render card, developer tab.
      await page.getByRole('tab', { name: 'For catalog developers' }).first().click();
      await dismissToasts(page);
      await toTop(page);
      await shot(page, '05-render-card');
      await page.getByTestId('next').click();

      // 6) Export, every check passing. Park the cursor off the stepper.
      await page.getByText('# yaml-language-server:').first().waitFor();
      await page.getByTestId('checks-pass').waitFor({ timeout: 30_000 });
      await dismissToasts(page);
      await page.mouse.move(720, 700);
      await toTop(page);
      await shot(page, '06-export');
    });

    test(`a recipe, macs2 narrowPeak (${scheme})`, async ({ page }) => {
      // The first run downloads Pyodide and polars.
      test.setTimeout(300_000);
      await open(page, 1440, 1200);
      // The committed macs2 peaks entry without its fixture: the recipe is
      // what produces it, from raw narrowPeak files.
      await api(page, 'loadFiles', macs2('module.yaml', 'peaks.yaml', 'peaks.py'));
      await api(page, 'goTo', 1);
      await page.getByTestId('recipe-panel').waitFor();

      // ① Raw samples: four libraries' narrowPeak files.
      // The drop zone is a button; its file input is the next sibling.
      await page
        .locator('[data-testid="recipe-add-input"] + input[type="file"]')
        .setInputFiles(narrowPeaks(['EZH2_IP_NTKO_R1', 'EZH2_IP_NTKO_R2', 'EZH2_IP_TKO_R1', 'EZH2_IP_TKO_R2']));
      await page.getByTestId('recipe-inputs').waitFor();

      // ② Run it. A recipe that came in with an imported entry asks for
      //    consent first ("Run this code"); after the run it is the author's.
      await page.getByTestId('recipe-run').click();
      await page.getByTestId('recipe-ok').waitFor({ timeout: 240_000 });
      await dismissToasts(page);
      await page.mouse.move(1300, 950);

      await toTop(page);
      await shot(page, '02c-recipe-raw');
      await scrollTo(page, '[data-testid="recipe-run"]', 120);
      await shot(page, '02d-recipe-run');

      // ③ The fixture is checked against OUTPUT_SCHEMA: declare a column the
      //    recipe does not return yet, and the stale fixture is flagged.
      const editor = page.getByTestId('stage-recipe').locator('.monaco-editor').first();
      await editor.click();
      const code = readFileSync(resolve(catalogDir, 'macs2', 'peaks.py'), 'utf8').split('\n');
      const line = code.findIndex((l) => l.includes('"neg_log10_qvalue": pl.Float64')) + 1;
      // To the top of the file (PageUp: Cmd/Ctrl+Home differ by platform), then
      // down: word wrap is off, so one press is one line.
      for (let i = 0; i < 20; i += 1) await page.keyboard.press('PageUp');
      await page.keyboard.press('Home');
      for (let i = 1; i < line; i += 1) await page.keyboard.press('ArrowDown');
      await page.keyboard.press('End');
      await page.keyboard.press('Enter');
      await page.keyboard.type('"peak_rank": pl.Int64,');
      await page.getByTestId('fixture-schema-mismatch').waitFor();
      await page.mouse.move(1300, 950);
      await scrollTo(page, '[data-testid="recipe-output-schema"]', 120);
      await shot(page, '02e-recipe-schema');
    });

    test(`several outputs and the checks, macs2 (${scheme})`, async ({ page }) => {
      test.setTimeout(120_000);
      await open(page);
      // The committed macs2 entry, two of its outputs: what Import an entry
      // does with a tool folder.
      await api(
        page,
        'loadFiles',
        macs2('module.yaml', 'peaks.yaml', 'peaks.py', 'peaks.tsv', 'broad_peaks.yaml', 'broad_peaks.py', 'broad_peaks.tsv'),
      );
      // On Visualizations: the highlighted output's renders, next to the
      // files the export will write for both.
      await api(page, 'goTo', 2);
      await page.getByTestId('outputs-bar').waitFor();
      await page.waitForTimeout(3_000);
      await page.getByTestId('entry-file').first().waitFor();
      await toTop(page);
      await shot(page, '07-outputs');

      // The checks at export: a render bound to a column the fixture lacks
      // (a typo).
      await api(page, 'addRender', {
        component: 'figure',
        visu_type: 'scatter',
        dict_kwargs: { x: 'fold_enrichment', y: 'neg_log10_qvalue', color: 'smaple' },
      });
      await api(page, 'goTo', 3);
      await page.getByTestId('diagnostics').waitFor();
      await dismissToasts(page);
      await page.mouse.move(720, 980);
      await toTop(page);
      await shot(page, '06b-export-checks');
    });
  });
}

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
  await page.getByLabel('Tool description').fill('A test tool.');
  await page.getByLabel('Homepage').fill('https://example.org');
  await page.getByLabel('Output slug').fill('results');
  await page.getByLabel('Path glob').fill('**/tool_studio_demo/*.csv');
  await page.getByTestId('next').click();

  await page.locator('input[type="file"]').setInputFiles(goldenCsv);
  await page.getByText('coverage · Int64').waitFor();
  await page.getByTestId('next').click();

  await page.getByRole('button', { name: 'Add visualization' }).click();
  await page.locator('.cs-type-card', { hasText: 'Figure' }).click();
  await page.getByPlaceholder('Select x axis*...').click();
  await page.getByRole('option', { name: 'log2fc' }).first().click();
  await page.getByPlaceholder('Select y axis*...').click();
  await page.getByRole('option', { name: 'pvalue' }).first().click();
  await page.getByTestId('add-to-output').click();
  await page.getByTestId('next').click();

  await page.getByRole('button', { name: /Open pull request|Sign in with GitHub/ }).click();
  const link = page.getByRole('link', { name: 'View pull request' });
  await link.waitFor({ timeout: 150_000 });
  await page.screenshot({ path: png('07-pr-opened') });
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
  await page.screenshot({ path: png('08-github-pr') });
});
