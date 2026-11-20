// @vitest-environment node
/**
 * The engine against a real Pyodide (the npm package in node_modules, same
 * version as the serverless pin) with the depictio modules built straight from
 * the repo. Pyodide's Node loader fetches wheels from the jsDelivr CDN once and
 * caches them next to the package, so this runs offline once the wheels are
 * cached (numpy + polars + pydantic, ~30 MB) and is skipped otherwise, unless
 * TOOL_STUDIO_PYODIDE_TESTS=1 allows the download. About 10 s warm.
 */
import { existsSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  __setEngineHostForTests,
  ensureEngine,
  polarsSchema,
  runRecipe,
  type EngineProgress,
  type PyodideApi,
} from '../pyodide/engine';
import { collectDepictioModules } from '../pyodide/depictioModules';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, '..', '..');
const repoRoot = resolve(pkgRoot, '..', '..');
const pyodideDir = resolve(pkgRoot, 'node_modules', 'pyodide');

const wheelsCached =
  existsSync(pyodideDir) && readdirSync(pyodideDir).some((f) => f.startsWith('polars-') && f.endsWith('.whl'));
const enabled = process.env.TOOL_STUDIO_PYODIDE_TESTS === '1' || wheelsCached;
const modules = collectDepictioModules(repoRoot);

describe.skipIf(!enabled || !modules)('pyodide engine (real runtime, node)', () => {
  const phases: string[] = [];

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
      async fetchBytes(url) {
        const res = await fetch(url);
        return new Uint8Array(await res.arrayBuffer());
      },
    });
    await ensureEngine((p: EngineProgress) => phases.push(p.phase));
  }, 120_000);

  afterAll(() => __setEngineHostForTests(null));

  it('reported its load phases', () => {
    expect(phases).toEqual(expect.arrayContaining(['runtime', 'packages', 'modules', 'ready']));
  });

  it('infers the schema catalog validate infers (ISO dates stay String)', async () => {
    const csv = 'date,sample,reads,ratio\n2024-01-02,a,10,0.5\n2024-02-03,b,20,1.5\n';
    expect(await polarsSchema('fixture.csv', csv)).toEqual({
      date: 'String',
      sample: 'String',
      reads: 'Int64',
      ratio: 'Float64',
    });
    // The separator follows the suffix: a .tsv is tab-separated, anything else comma.
    expect(await polarsSchema('fixture.tsv', 'a\tb\n1\tx\n')).toEqual({ a: 'Int64', b: 'String' });
  });

  it('runs a recipe with a lib helper, read_kwargs and source_path', async () => {
    const code = `
import polars as pl
from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.contigs import sort_contigs

SOURCES = [
    RecipeSource(
        ref="cov",
        path="results/*.cov.tsv",
        format="TSV",
        read_kwargs={"comment_prefix": "#"},
        source_path="source_path",
        input_schema={"chrom": pl.Utf8, "depth": pl.Float64},
    )
]
OUTPUT_SCHEMA = {"chrom": pl.Utf8, "depth": pl.Float64, "file": pl.Utf8}

def transform(sources):
    print("rows in:", sources["cov"].height)
    df = sources["cov"].with_columns(pl.col("source_path").alias("file")).select("chrom", "depth", "file")
    return sort_contigs(df, "chrom")
`;
    const res = await runRecipe(code, [
      { fileName: 's1.cov.tsv', sourcePath: 'results/s1.cov.tsv', text: '# mosdepth-ish\nchrom\tdepth\nchr10\t3\nchr2\t4.5\n' },
    ]);
    expect(res.error).toBeUndefined();
    expect(res.ok).toBe(true);
    expect(res.columns).toEqual([
      { name: 'chrom', dtype: 'String' },
      { name: 'depth', dtype: 'Float64' },
      { name: 'file', dtype: 'String' },
    ]);
    expect(res.rowCount).toBe(2);
    expect(res.tsv).toBe('chrom\tdepth\tfile\nchr2\t4.5\tresults/s1.cov.tsv\nchr10\t3.0\tresults/s1.cov.tsv\n');
    expect(res.outputSchema).toEqual({ chrom: 'String', depth: 'Float64', file: 'String' });
    expect(res.stdout).toContain('rows in: 2');
  }, 60_000);

  it('runs a real catalog recipe (mosdepth/summary.py, a dc_ref source)', async () => {
    const { readFileSync } = await import('node:fs');
    const code = readFileSync(resolve(repoRoot, 'depictio', 'catalog', 'mosdepth', 'summary.py'), 'utf8');
    const raw = [
      'chrom\tlength\tbases\tmean\tmin\tmax\tsource_path',
      'chr2\t100\t500\t5.0\t0\t9\tmosdepth/S1.md.mosdepth.summary.txt',
      'chr1\t100\t300\t3.0\t0\t7\tmosdepth/S1.md.mosdepth.summary.txt',
      'chrUn_x\t10\t1\t0.1\t0\t1\tmosdepth/S1.md.mosdepth.summary.txt',
      'total\t200\t800\t4.0\t0\t9\tmosdepth/S1.md.mosdepth.summary.txt',
    ].join('\n');
    const res = await runRecipe(code, [{ ref: 'summary', fileName: 'summary_raw.tsv', text: raw + '\n' }]);
    expect(res.error).toBeUndefined();
    expect(res.rowCount).toBe(3);
    expect(res.tsv.split('\n')[1]).toBe('S1\tmd\tgenome\tchr1\t100\t300\t3.0\t0\t7');
    expect(res.columns.find((c) => c.name === 'mean_depth')?.dtype).toBe('Float64');
  }, 60_000);

  it('reports a failed OUTPUT_SCHEMA check with the declared schema', async () => {
    const code = `
import polars as pl
from depictio.models.models.transforms import RecipeSource
SOURCES = [RecipeSource(ref="t", path="t.csv", format="csv")]
OUTPUT_SCHEMA = {"x": pl.Float64}
def transform(sources):
    return sources["t"]
`;
    const res = await runRecipe(code, [{ fileName: 't.csv', text: 'x\n1\n2\n' }]);
    expect(res.ok).toBe(false);
    expect(res.error).toContain("column 'x' expected Float64, got Int64");
    expect(res.outputSchema).toEqual({ x: 'Float64' });
  }, 60_000);

  it('fails a source with no format exactly as depictio does', async () => {
    // RecipeSource's default format ("CSV") is not normalised by its validator,
    // so depictio's _format_readers rejects it; the engine runs the same code.
    const res = await runRecipe(
      'import polars as pl\nfrom depictio.models.models.transforms import RecipeSource\nSOURCES=[RecipeSource(ref="a", path="a.csv")]\nOUTPUT_SCHEMA={"x": pl.Int64}\ndef transform(s): return s["a"]',
      [{ fileName: 'a.csv', text: 'x\n1\n' }],
    );
    expect(res.ok).toBe(false);
    expect(res.error).toContain('Unsupported format: CSV');
  }, 60_000);

  it('reports RecipeSource validation and a missing source', async () => {
    const bad = await runRecipe(
      'from depictio.models.models.transforms import RecipeSource\nSOURCES=[RecipeSource(ref="a", format="xlsx")]\nOUTPUT_SCHEMA={}\ndef transform(s): return s',
      [{ fileName: 'a.csv', text: 'x\n1\n' }],
    );
    expect(bad.ok).toBe(false);
    expect(bad.error).toContain('format must be one of');
    const missing = await runRecipe(
      `import polars as pl
from depictio.models.models.transforms import RecipeSource
SOURCES=[RecipeSource(ref="a", path="a.csv", format="csv"), RecipeSource(ref="b", path="b.csv", format="csv")]
OUTPUT_SCHEMA={"x": pl.Int64}
def transform(s): return s["a"]`,
      [{ fileName: 'a.csv', text: 'x\n1\n' }],
    );
    expect(missing.ok).toBe(false);
    expect(missing.error).toContain("Source 'b': no file was given for it");
  }, 60_000);
});

// Code Mode on the shared interpreter: pandas + plotly 6.9.0 (the pinned PyPI
// wheel, downloaded on every run, so only with TOOL_STUDIO_PYODIDE_TESTS=1).
describe.skipIf(process.env.TOOL_STUDIO_PYODIDE_TESTS !== '1')('code mode on the shared engine (node)', () => {
  beforeAll(() => {
    __setEngineHostForTests({
      async loadPyodide() {
        const mod = await import('pyodide');
        return (await mod.loadPyodide({
          indexURL: `${pyodideDir}/`,
          stdout: () => undefined,
          stderr: () => undefined,
        })) as unknown as PyodideApi;
      },
      loadModules: async () => modules ?? {},
      async fetchBytes(url) {
        const res = await fetch(url);
        return new Uint8Array(await res.arrayBuffer());
      },
    });
  });
  afterAll(() => __setEngineHostForTests(null));

  it('runs a plotly-express snippet against a pandas df', async () => {
    const { runCodeToFigure } = await import('../builder/pyodideRunner');
    const fixture = {
      fileName: 'f.csv',
      delimiter: ',',
      columns: [
        { name: 'sample', dtype: 'String' },
        { name: 'reads', dtype: 'Int64' },
      ],
      rows: [
        { sample: 'a', reads: '10' },
        { sample: 'b', reads: '20' },
      ],
      raw: 'sample,reads\na,10\nb,20\n',
    } as unknown as import('../types').ParsedFixture;
    const res = await runCodeToFigure(
      "import plotly\nassert plotly.__version__ == '6.9.0'\nfig = px.bar(df.to_pandas(), x='sample', y='reads')",
      fixture,
    );
    expect(res.error).toBeUndefined();
    expect(res.figure?.data[0]).toMatchObject({ type: 'bar' });
    const pl = await runCodeToFigure('fig = pl.col("x")', fixture);
    expect(pl.error).toContain('polars is not available');
  }, 120_000);
});
