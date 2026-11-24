// @vitest-environment node
/**
 * Exact figure previews against a real Pyodide (same gating as
 * pyodideEngine.node.test.ts): depictio's create_figure_from_data and the path
 * around it, shipped by src/pyodide/figureModules.ts, built straight from the
 * repo. Needs plotly 6.9.0 and, for the trendline, statsmodels + scipy + patsy
 * cached next to the pyodide package (TOOL_STUDIO_PYODIDE_TESTS=1 allows the
 * download). Compares against depictio's own mantine templates, read out of
 * depictio/cli/cli/utils/mantine_templates.py in the same interpreter.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  __setEngineHostForTests,
  ensureFigureEngine,
  loadPython,
  renderFigure,
  type PyodideApi,
} from '../pyodide/engine';
import { collectDepictioModules } from '../pyodide/depictioModules';
import { collectFigureModules } from '../pyodide/figureModules';
import pin from '../pyodide/generated/pin.json';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, '..', '..');
const repoRoot = resolve(pkgRoot, '..', '..');
const pyodideDir = resolve(pkgRoot, 'node_modules', 'pyodide');

const cached = (prefix: string) => existsSync(pyodideDir) && readdirSync(pyodideDir).some((f) => f.startsWith(prefix));
const wheelsCached = ['polars-', 'plotly-', 'statsmodels-', 'scipy-', 'patsy-'].every(cached);
const enabled = process.env.TOOL_STUDIO_PYODIDE_TESTS === '1' || wheelsCached;
const modules = collectDepictioModules(repoRoot);
const figureModules = collectFigureModules(repoRoot);

const IRIS = [
  'sepal_length,sepal_width,species,site',
  '5.1,3.5,setosa,A',
  '4.9,3.0,setosa,B',
  '4.7,3.2,setosa,A',
  '7.0,3.2,versicolor,B',
  '6.4,3.2,versicolor,A',
  '6.9,3.1,versicolor,B',
  '6.3,3.3,virginica,A',
  '5.8,2.7,virginica,B',
  '7.1,3.0,virginica,A',
  '6.5,3.0,virginica,B',
].join('\n');

describe.skipIf(!enabled || !modules || !figureModules)('exact figures (real runtime, node)', () => {
  let loadMs = 0;

  beforeAll(async () => {
    __setEngineHostForTests({
      async loadPyodide() {
        const mod = await import('pyodide');
        return (await mod.loadPyodide({
          indexURL: `${pyodideDir}/`,
          stdout: () => undefined,
          stderr: () => undefined,
        })) as unknown as PyodideApi;
      },
      loadModules: async () => modules!,
      loadFigureModules: async () => figureModules!,
      async fetchBytes(url) {
        const local = resolve(pyodideDir, url.split('/').pop()!);
        if (existsSync(local)) return new Uint8Array(readFileSync(local));
        const res = await fetch(url);
        return new Uint8Array(await res.arrayBuffer());
      },
    });
    const t0 = Date.now();
    await ensureFigureEngine();
    loadMs = Date.now() - t0;
  }, 180_000);

  afterAll(() => __setEngineHostForTests(null));

  it('loads the figure engine on the serverless pin', () => {
    expect(pin.extras.plotly.version).toBe('6.9.0');
    expect(loadMs).toBeGreaterThan(0);
  });

  it('draws a faceted scatter with its trendline, as px does on the server', async () => {
    const res = await renderFigure(
      {
        visu_type: 'scatter',
        dict_kwargs: { x: 'sepal_length', y: 'sepal_width', facet_col: 'site', trendline: 'ols' },
      },
      { fileName: 'iris.csv', text: IRIS },
      'light',
    );
    expect(res.errors).toEqual([]);
    const layout = res.figure.layout as Record<string, Record<string, unknown>>;
    // One panel per site: px's facet axes, x2 anchored on y2.
    expect(layout.xaxis2).toBeDefined();
    expect(layout.xaxis2.anchor).toBe('y2');
    const traces = res.figure.data as Array<Record<string, unknown>>;
    // A trendline trace per facet panel: mode "lines", hovertemplate naming OLS.
    const trend = traces.filter((t) => t.mode === 'lines');
    expect(trend).toHaveLength(2);
    expect(String(trend[0].hovertemplate)).toContain('OLS trendline');
    // tidy_facet_layout ran: "site=A" is just "A".
    const ann = (layout.annotations as unknown as Array<{ text: string }>).map((a) => a.text);
    expect(ann).toEqual(expect.arrayContaining(['A', 'B']));
    // create_figure_from_data's own layout touches.
    expect(layout.paper_bgcolor).toBe('rgba(0,0,0,0)');
    expect(layout.uirevision).toBe('persistent');
  }, 120_000);

  it("themes a histogram with depictio's mantine_light / mantine_dark template", async () => {
    const py = await loadPython([]);
    const expected = (name: string) =>
      JSON.parse(
        String(
          py.runPython(
            [
              'import json',
              'import plotly.io as pio',
              'from depictio.cli.cli.utils.mantine_templates import ensure_mantine_templates',
              'ensure_mantine_templates()',
              `json.dumps(pio.templates["${name}"].to_plotly_json()["layout"])`,
            ].join('\n'),
          ),
        ),
      );
    for (const theme of ['light', 'dark'] as const) {
      const res = await renderFigure(
        { visu_type: 'histogram', dict_kwargs: { x: 'sepal_length', color: 'species' } },
        { fileName: 'iris.csv', text: IRIS },
        theme,
      );
      expect(res.errors).toEqual([]);
      // The aggregation fast path drew it (as the server does for a histogram).
      expect(res.metadata.aggregated).toBe(true);
      const template = (res.figure.layout as { template: { layout: Record<string, unknown> } }).template;
      const want = expected(`mantine_${theme}`);
      expect(JSON.parse(JSON.stringify(template.layout))).toEqual(want);
      // The shared plot chrome's text (depictio_palettes.json writes hex in upper case).
      expect((template.layout.font as { color: string }).color.toLowerCase()).toBe(theme === 'dark' ? '#e9ecef' : '#343a40');
    }
  }, 120_000);

  it('applies the preview filters as a row mask, and refuses one over another row count', async () => {
    const res = await renderFigure(
      { visu_type: 'scatter', dict_kwargs: { x: 'sepal_length', y: 'sepal_width' } },
      { fileName: 'iris.csv', text: IRIS, keep: [0, 1, 2], rows: 10 },
      'light',
    );
    // plotly 6 serialises arrays as base64 typed arrays, which plotly.js reads.
    const x = (res.figure.data as Array<{ x: { dtype: string; bdata: string } }>)[0].x;
    expect(x.dtype).toBe('f8');
    const buf = Buffer.from(x.bdata, 'base64');
    expect(Array.from(new Float64Array(buf.buffer, buf.byteOffset, buf.length / 8))).toEqual([5.1, 4.9, 4.7]);
    expect(res.metadata.displayed_data_count).toBe(3);
    await expect(
      renderFigure(
        { visu_type: 'scatter', dict_kwargs: { x: 'sepal_length', y: 'sepal_width' } },
        { fileName: 'iris.csv', text: IRIS, keep: [0], rows: 11 },
        'light',
      ),
    ).rejects.toThrow(/computed over 11 rows/);
  }, 60_000);

  it("returns depictio's error figure for a binding px rejects", async () => {
    const res = await renderFigure(
      { visu_type: 'scatter', dict_kwargs: { x: 'nope', y: 'sepal_width' } },
      { fileName: 'iris.csv', text: IRIS },
      'light',
    );
    expect(res.errors.join(' ')).toContain('Figure creation failed');
  }, 60_000);
});
