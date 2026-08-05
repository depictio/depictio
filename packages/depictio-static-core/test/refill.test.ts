/**
 * refillFigure unit tests (RFC §4 bind-and-refill, phase 5b).
 *
 * The main fixture is hand-written: 8 rows, two groups (A at rows 0,1,3,6 —
 * B at rows 2,4,5,7), bindings for x/y + a dotted marker.size path, and one
 * OLS trendline fit against group A. The OLS expectations are hand-computed:
 *   A points (x, y) = (1,2) (2,3) (4,7) (7,10)
 *   x̄ = 3.5, ȳ = 5.5, Sxy = 29, Sxx = 21
 *   slope = 29/21, intercept = 5.5 − 3.5·29/21 = 2/3
 *   line at [xmin, xmax] = [1, 7] → y = [43/21, 31/3]
 *
 * The last suite is contract-integration: it loads the demo penguins bundle
 * manifest and, IF the producer has landed a bindings entry, refills through
 * the real HyparquetEngine from the inline Parquet blob. It self-skips while
 * `bindings` is still empty (producer is a parallel work stream).
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import type { BindingTable, BundleManifest } from '../src/manifest';
import { refillFigure, type RefillInput } from '../src/refill';
import { HyparquetEngine } from '../src/engine/hyparquet/index';

// ---------------------------------------------------------------------------
// fixture
// ---------------------------------------------------------------------------

const GRP = ['A', 'A', 'B', 'A', 'B', 'B', 'A', 'B'];
const XCOL = new Float64Array([1, 2, 3, 4, 5, 6, 7, 8]);
const YCOL = new Float64Array([2, 3, 1, 7, 4, 9, 10, 16]);
const SZCOL = new BigInt64Array([10n, 20n, 30n, 40n, 50n, 60n, 70n, 80n]);

const FIXTURE_COLUMNS: Record<string, ArrayLike<unknown>> = {
  grp: GRP,
  xcol: XCOL,
  ycol: YCOL,
  szcol: SZCOL,
};

function fixtureColumns(names: string[]): Promise<Record<string, ArrayLike<unknown>>> {
  const out: Record<string, ArrayLike<unknown>> = {};
  for (const name of names) {
    const col = FIXTURE_COLUMNS[name];
    if (col === undefined) throw new Error(`fixture: unknown column "${name}"`);
    out[name] = col;
  }
  return Promise.resolve(out);
}

function fixtureBinding(): BindingTable {
  return {
    scaffold: {
      data: [
        { type: 'scattergl', mode: 'markers', name: 'A', marker: { color: 'red' } },
        { type: 'scattergl', mode: 'markers', name: 'B', marker: { color: 'blue' } },
        { type: 'scattergl', mode: 'lines', name: 'trend-A', showlegend: false },
      ],
      layout: { title: { text: 'fixture' }, xaxis: { title: { text: 'x' } } },
    },
    group_cols: ['grp'],
    traces: [
      {
        i: 0,
        group: { grp: 'A' },
        fields: { x: 'xcol', y: 'ycol', 'marker.size': 'szcol' },
        axes: {},
      },
      {
        i: 1,
        group: { grp: 'B' },
        fields: { x: 'xcol', y: 'ycol', 'marker.size': 'szcol' },
        axes: {},
      },
    ],
    trendlines: [{ i: 2, on: 0 }],
    sampled: false,
  };
}

function refill(binding: BindingTable, mask: Uint8Array | null): ReturnType<typeof refillFigure> {
  const input: RefillInput = { binding, columns: fixtureColumns, mask };
  return refillFigure(input);
}

type Trace = Record<string, unknown> & { marker?: Record<string, unknown> };

// ---------------------------------------------------------------------------

describe('refillFigure — no mask', () => {
  it('writes each group its own rows in row order (x, y, dotted marker.size)', async () => {
    const { figure, displayed, total } = await refill(fixtureBinding(), null);
    const [a, b] = figure.data as Trace[];

    expect(a.x).toEqual([1, 2, 4, 7]);
    expect(a.y).toEqual([2, 3, 7, 10]);
    expect(a.marker?.size).toEqual([10, 20, 40, 70]); // bigint → number

    expect(b.x).toEqual([3, 5, 6, 8]);
    expect(b.y).toEqual([1, 4, 9, 16]);
    expect(b.marker?.size).toEqual([30, 50, 60, 80]);

    expect(displayed).toBe(8); // sum of per-trace points, raw traces only
    expect(total).toBe(8);
  });

  it('preserves sibling keys when writing a dotted path', async () => {
    const { figure } = await refill(fixtureBinding(), null);
    const [a, b] = figure.data as Trace[];
    expect(a.marker?.color).toBe('red');
    expect(b.marker?.color).toBe('blue');
  });

  it('refits the trendline with hand-computed OLS over its source trace', async () => {
    const { figure } = await refill(fixtureBinding(), null);
    const trend = (figure.data as Trace[])[2];
    expect(trend.visible).not.toBe(false);
    expect(trend.x).toEqual([1, 7]);
    const [y0, y1] = trend.y as number[];
    expect(y0).toBeCloseTo(43 / 21, 12);
    expect(y1).toBeCloseTo(31 / 3, 12);
  });

  it('never touches the layout (verbatim scaffold clone)', async () => {
    const binding = fixtureBinding();
    const { figure } = await refill(binding, null);
    expect(figure.layout).toEqual(binding.scaffold.layout);
    expect(figure.layout).not.toBe(binding.scaffold.layout); // a clone, not a reference
  });

  it('does not mutate the scaffold (manifest object stays pristine)', async () => {
    const binding = fixtureBinding();
    const before = JSON.stringify(binding.scaffold);
    await refill(binding, null);
    expect(JSON.stringify(binding.scaffold)).toBe(before);
  });
});

describe('refillFigure — masked', () => {
  it('ANDs the mask with group predicates; counts reflect the selection', async () => {
    // Rows kept: 0,1,3,6 (all of A) and 7 (one B row).
    const mask = new Uint8Array([1, 1, 0, 1, 0, 0, 1, 1]);
    const { figure, displayed, total } = await refill(fixtureBinding(), mask);
    const [a, b] = figure.data as Trace[];

    expect(a.x).toEqual([1, 2, 4, 7]);
    expect(b.x).toEqual([8]);
    expect(b.y).toEqual([16]);
    expect(b.visible).not.toBe(false);

    expect(displayed).toBe(5);
    expect(total).toBe(5);
  });

  it('keeps groups isolated — no row of one group ever leaks into the other', async () => {
    const mask = new Uint8Array([1, 1, 1, 1, 1, 1, 1, 0]);
    const { figure } = await refill(fixtureBinding(), mask);
    const [a, b] = figure.data as Trace[];
    const aX = new Set(a.x as number[]);
    for (const x of b.x as number[]) expect(aX.has(x)).toBe(false);
    expect(a.x).toEqual([1, 2, 4, 7]); // A untouched by masking a B row
    expect(b.x).toEqual([3, 5, 6]);
  });

  it('hides an emptied group (visible:false) without dropping it — indices stable', async () => {
    // Keep only A rows → B is empty.
    const mask = new Uint8Array([1, 1, 0, 1, 0, 0, 1, 0]);
    const { figure, displayed, total } = await refill(fixtureBinding(), mask);
    expect(figure.data).toHaveLength(3);
    const [a, b, trend] = figure.data as Trace[];

    expect(b.visible).toBe(false);
    expect(b.x).toEqual([]);
    expect(b.name).toBe('B'); // still the same trace at the same index
    expect(a.visible).not.toBe(false);
    expect(trend.visible).not.toBe(false); // A still has ≥ 2 points

    expect(displayed).toBe(4);
    expect(total).toBe(4);
  });

  it('hides the trendline when its source trace has fewer than 2 usable points', async () => {
    // Keep a single A row (and all B rows).
    const mask = new Uint8Array([1, 0, 1, 0, 1, 1, 0, 1]);
    const { figure } = await refill(fixtureBinding(), mask);
    const [a, , trend] = figure.data as Trace[];
    expect(a.x).toEqual([1]); // raw trace still shows its lone point
    expect(a.visible).not.toBe(false);
    expect(trend.visible).toBe(false);
  });

  it('all-false mask empties every trace and reports zero counts', async () => {
    const mask = new Uint8Array(8); // all zeros
    const { figure, displayed, total } = await refill(fixtureBinding(), mask);
    for (const trace of figure.data as Trace[]) expect(trace.visible).toBe(false);
    expect(displayed).toBe(0);
    expect(total).toBe(0);
  });
});

describe('refillFigure — group value serialization', () => {
  it('matches a JSON-number group value against a bigint (Int64) column', async () => {
    const binding: BindingTable = {
      scaffold: { data: [{ name: '2007' }], layout: {} },
      group_cols: ['year'],
      traces: [{ i: 0, group: { year: 2007 }, fields: { y: 'val' }, axes: {} }],
      trendlines: [],
      sampled: false,
    };
    const columns = (names: string[]) => {
      const table: Record<string, ArrayLike<unknown>> = {
        year: new BigInt64Array([2007n, 2008n, 2007n]),
        val: new Float64Array([1.5, 99, 2.5]),
      };
      return Promise.resolve(Object.fromEntries(names.map((n) => [n, table[n]])));
    };
    const { figure, displayed } = await refillFigure({ binding, columns, mask: null });
    expect((figure.data[0] as Trace).y).toEqual([1.5, 2.5]);
    expect(displayed).toBe(2);
  });

  it('a null cell never matches any group predicate', async () => {
    const binding: BindingTable = {
      scaffold: { data: [{ name: 'A' }], layout: {} },
      group_cols: ['grp'],
      traces: [{ i: 0, group: { grp: 'A' }, fields: { y: 'val' }, axes: {} }],
      trendlines: [],
      sampled: false,
    };
    const columns = (names: string[]) => {
      const table: Record<string, ArrayLike<unknown>> = {
        grp: ['A', null, 'A'],
        val: [10, 20, 30],
      };
      return Promise.resolve(Object.fromEntries(names.map((n) => [n, table[n]])));
    };
    const { figure } = await refillFigure({ binding, columns, mask: null });
    expect((figure.data[0] as Trace).y).toEqual([10, 30]);
  });
});

// ---------------------------------------------------------------------------
// contract integration: the demo penguins bundle (self-skips until the
// producer lands its bindings entry — parallel work stream).
// ---------------------------------------------------------------------------

const PENGUINS_PATH = join(
  __dirname,
  '..',
  '..',
  '..',
  'depictio',
  'viewer',
  'demo',
  'manifests',
  'penguins.json',
);

function loadPenguins(): BundleManifest | null {
  try {
    return JSON.parse(readFileSync(PENGUINS_PATH, 'utf-8')) as BundleManifest;
  } catch {
    return null;
  }
}

const penguins = loadPenguins();
const penguinsBindings = Object.entries(penguins?.bindings ?? {});

describe.runIf(penguinsBindings.length > 0)('refillFigure — penguins demo manifest', () => {
  it('refills the species scatter from the inline Parquet blob', async () => {
    const manifest = penguins!;
    const [componentId, binding] = penguinsBindings[0];
    const meta = (
      manifest.dashboard.doc as {
        stored_metadata?: { index?: string; dc_id?: string | null }[];
      }
    ).stored_metadata?.find((c) => c.index === componentId);
    const dcId = String(meta?.dc_id ?? '');
    const ref = manifest.data_refs[dcId];
    expect(ref).toBeDefined();

    const blobKey = ref.uri.slice('inline:'.length);
    const bytes = new Uint8Array(Buffer.from(manifest.inline_blobs[blobKey], 'base64'));
    const engine = new HyparquetEngine();
    const handle = await engine.open(ref, bytes);

    const { figure, displayed, total } = await refillFigure({
      binding,
      columns: (names) => engine.columns(handle, names),
      mask: null,
    });

    // 3 species → 3 raw trace bindings, each with a plausible share of the
    // 342 penguins, lengths summing to the full table.
    expect(binding.traces).toHaveLength(3);
    let sum = 0;
    for (const t of binding.traces) {
      const x = (figure.data[t.i] as Trace).x as unknown[];
      expect(x.length).toBeGreaterThan(0);
      sum += x.length;
    }
    expect(ref.rows).toBe(342);
    expect(sum).toBe(342);
    expect(displayed).toBe(342);
    expect(total).toBe(342);
  });
});
