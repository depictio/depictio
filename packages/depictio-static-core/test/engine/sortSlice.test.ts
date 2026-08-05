/**
 * sortSlice vs. the server's render_table contract:
 * - endpoint: dashboards routes.py:2429-2687 (single sort_by/sort_dir,
 *   filters before sort, total = filtered count, unknown sort col dropped
 *   at :2552-2555, natural-order slice branch at :2622-2633);
 * - sort call: deltatables_utils.py:1591-1592 (and lazy path :1568-1577) —
 *   df.sort(sort_by, descending=..., nulls_last=True, maintain_order=True);
 * - multi-key list form: routes.py:2838-2847.
 *
 * Every `expected.sort_slice` entry is Polars-computed ground truth written by
 * scripts/generate_fixture.py with exactly those arguments. Synthetic cases at
 * the bottom pin behaviors the fixture data cannot exercise (NaN, ±inf,
 * supplementary-plane strings), each verified empirically on Polars 1.42.1.
 */

import { describe, expect, it } from 'vitest';

import type { BoundFilter } from '../../src/engine/filters';
import type { ColumnBatch } from '../../src/engine/QueryEngine';
import { sortSlice } from '../../src/engine/sortSlice';
import { expected, openFixture } from './helpers';

interface SortSliceCase {
  total: number;
  idx: number[];
  values?: unknown[];
}

const SS = (expected as unknown as { sort_slice: Record<string, SortSliceCase> }).sort_slice;

const ALL_COLS = [
  'idx_i32',
  'value_f64',
  'value_i64',
  'category_str',
  'batch',
  'flag_bool',
  'event_date',
];

async function fixtureColumns(): Promise<{
  cols: ColumnBatch;
  mask: (filters: BoundFilter[]) => Promise<Uint8Array>;
}> {
  const { engine, handle } = await openFixture();
  const cols = await engine.columns(handle, ALL_COLS);
  return {
    cols,
    mask: async (filters) => (await engine.mask(handle, filters)).mask,
  };
}

function idxOf(rows: Record<string, unknown>[]): number[] {
  return rows.map((r) => r['idx_i32'] as number);
}

function checkCase(
  rows: Record<string, unknown>[],
  total: number,
  exp: SortSliceCase,
  valueCol?: string,
): void {
  expect(total).toBe(exp.total);
  expect(idxOf(rows)).toEqual(exp.idx);
  if (valueCol !== undefined && exp.values !== undefined) {
    expect(rows.map((r) => r[valueCol])).toEqual(exp.values);
  }
}

describe('sortSlice — Polars ground truth (fixture)', () => {
  it('Float64 asc: first page', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'value_f64', desc: false }], 0, 10);
    checkCase(rows, total, SS['f64_asc_head'], 'value_f64');
  });

  it('Float64 asc: nulls land LAST (tail page, in input order)', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(
      cols,
      null,
      [{ column: 'value_f64', desc: false }],
      expected.rows - 10,
      10,
    );
    checkCase(rows, total, SS['f64_asc_tail'], 'value_f64');
  });

  it('Float64 desc: first page', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'value_f64', desc: true }], 0, 10);
    checkCase(rows, total, SS['f64_desc_head'], 'value_f64');
  });

  it('Float64 desc: nulls STILL last (nulls_last=True is not direction-reversed)', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(
      cols,
      null,
      [{ column: 'value_f64', desc: true }],
      expected.rows - 10,
      10,
    );
    checkCase(rows, total, SS['f64_desc_tail'], 'value_f64');
  });

  it('Int64 asc: BigInt comparison, rows carry JSON-observable numbers', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'value_i64', desc: false }], 0, 10);
    checkCase(rows, total, SS['i64_asc_head'], 'value_i64');
    for (const r of rows) expect(typeof r['value_i64']).toBe('number');
  });

  it('Int64 desc: large values (BigInt64Array path) order exactly', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'value_i64', desc: true }], 0, 10);
    checkCase(rows, total, SS['i64_desc_head'], 'value_i64');
  });

  it('String asc: first page', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'category_str', desc: false }], 0, 10);
    checkCase(rows, total, SS['str_asc_head'], 'category_str');
  });

  it('String asc: nulls last (tail page)', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(
      cols,
      null,
      [{ column: 'category_str', desc: false }],
      expected.rows - 10,
      10,
    );
    checkCase(rows, total, SS['str_asc_tail'], 'category_str');
  });

  it('String desc: first page', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'category_str', desc: true }], 0, 10);
    checkCase(rows, total, SS['str_desc_head'], 'category_str');
  });

  it('Boolean asc: false < true', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'flag_bool', desc: false }], 0, 10);
    checkCase(rows, total, SS['bool_asc_head'], 'flag_bool');
  });

  it('Datetime asc (Date objects, epoch order)', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'event_date', desc: false }], 0, 10);
    checkCase(rows, total, SS['date_asc_head']);
  });

  it('Datetime desc', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'event_date', desc: true }], 0, 10);
    checkCase(rows, total, SS['date_desc_head']);
  });

  it('stability: ties keep input order (maintain_order=True)', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [{ column: 'batch', desc: false }], 0, 25);
    checkCase(rows, total, SS['batch_asc_stability']);
  });

  it('multi-key: per-key direction, key-1 ties broken by key 2', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(
      cols,
      null,
      [
        { column: 'category_str', desc: false },
        { column: 'value_f64', desc: true },
      ],
      0,
      15,
    );
    checkCase(rows, total, SS['multi_str_asc_f64_desc']);
  });

  it('mask narrows BEFORE sorting; total is the filtered count', async () => {
    const { cols, mask } = await fixtureColumns();
    const m = await mask([{ kind: 'in', column: 'category_str', values: ['alpha', 'beta'] }]);
    const { rows, total } = sortSlice(cols, m, [{ column: 'value_i64', desc: false }], 0, 10);
    checkCase(rows, total, SS['masked_in_str_i64_asc'], 'value_i64');
    expect(total).toBe(expected.filters['in_str'].matched);
  });

  it('sort: [] = natural order under a mask (slice-pushdown branch)', async () => {
    const { cols, mask } = await fixtureColumns();
    const m = await mask([{ kind: 'in', column: 'category_str', values: ['alpha', 'beta'] }]);
    const { rows, total } = sortSlice(cols, m, [], 5, 10);
    checkCase(rows, total, SS['masked_in_str_natural']);
  });

  it('empty mask -> total 0, no rows', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(
      cols,
      new Uint8Array(expected.rows),
      [{ column: 'value_f64', desc: false }],
      0,
      10,
    );
    expect(total).toBe(0);
    expect(rows).toEqual([]);
  });
});

describe('sortSlice — pagination edges', () => {
  it('start beyond total -> empty page, total unchanged', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [], expected.rows + 100, 10);
    expect(total).toBe(expected.rows);
    expect(rows).toEqual([]);
  });

  it('limit 0 -> empty page (kernel is a pure slice; the endpoint clamps limit to >=1 upstream, routes.py:2469)', async () => {
    const { cols } = await fixtureColumns();
    const { rows, total } = sortSlice(cols, null, [], 0, 0);
    expect(total).toBe(expected.rows);
    expect(rows).toEqual([]);
  });

  it('window overrunning the end returns the short remainder', async () => {
    const { cols } = await fixtureColumns();
    const { rows } = sortSlice(cols, null, [], expected.rows - 5, 10);
    expect(idxOf(rows)).toEqual([1995, 1996, 1997, 1998, 1999]);
  });

  it('exact boundary: start + limit === total returns the full last page', async () => {
    const { cols } = await fixtureColumns();
    const { rows } = sortSlice(cols, null, [], expected.rows - 10, 10);
    expect(rows).toHaveLength(10);
    expect(idxOf(rows)[9]).toBe(1999);
  });

  it('negative start/limit floor to 0', async () => {
    const { cols } = await fixtureColumns();
    expect(sortSlice(cols, null, [], -5, 3).rows).toHaveLength(3);
    expect(sortSlice(cols, null, [], 0, -1).rows).toEqual([]);
  });
});

describe('sortSlice — pinned Polars semantics (synthetic)', () => {
  it('NaN sorts above +inf; nulls after NaN, in both directions (verified Polars 1.42.1)', () => {
    // Polars 1.42.1: sort([1.0, inf, nan, -inf, None], nulls_last=True)
    //   asc  -> [-inf, 1.0, inf, nan, None]
    //   desc -> [nan, inf, 1.0, -inf, None]
    const cols = { v: [1.0, Infinity, NaN, -Infinity, null] };
    const asc = sortSlice(cols, null, [{ column: 'v', desc: false }], 0, 5);
    expect(asc.rows.map((r) => r['v'])).toEqual([-Infinity, 1.0, Infinity, NaN, null]);
    const desc = sortSlice(cols, null, [{ column: 'v', desc: true }], 0, 5);
    expect(desc.rows.map((r) => r['v'])).toEqual([NaN, Infinity, 1.0, -Infinity, null]);
  });

  it('strings compare by CODE POINT, not UTF-16 code units (verified Polars 1.42.1)', () => {
    // Polars (UTF-8 byte order == code-point order) sorts
    // ['�', '\u{1F600}', 'a', ''] -> ['', 'a', '�', '\u{1F600}'];
    // naive UTF-16 `<` would put '\u{1F600}' (0xD83D...) before '�'.
    const cols = { v: ['�', '\u{1F600}', 'a', ''] };
    const { rows } = sortSlice(cols, null, [{ column: 'v', desc: false }], 0, 4);
    expect(rows.map((r) => r['v'])).toEqual(['', 'a', '�', '\u{1F600}']);
  });

  it('unknown sort column is silently dropped (routes.py:2552-2555)', () => {
    const cols = { v: [3, 1, 2] };
    const { rows, total } = sortSlice(cols, null, [{ column: 'missing', desc: false }], 0, 3);
    expect(total).toBe(3);
    expect(rows.map((r) => r['v'])).toEqual([3, 1, 2]); // natural order
  });

  it('full multi-key tie preserves input order', () => {
    const cols = { k: ['x', 'x', 'x'], j: [1, 1, 1], tag: ['a', 'b', 'c'] };
    const { rows } = sortSlice(
      cols,
      null,
      [
        { column: 'k', desc: true },
        { column: 'j', desc: false },
      ],
      0,
      3,
    );
    expect(rows.map((r) => r['tag'])).toEqual(['a', 'b', 'c']);
  });

  it('multi-key: null tie on key 1 falls through to key 2, nulls last per key', () => {
    // Mirrors the verified Polars run: sort(['a','b'], descending=[False,True],
    // nulls_last=True, maintain_order=True) over a=[x,x,y,None,x], b=[1,2,None,5,2]
    // -> i order [1, 4, 0, 2, 3].
    const cols = { a: ['x', 'x', 'y', null, 'x'], b: [1, 2, null, 5, 2], i: [0, 1, 2, 3, 4] };
    const { rows } = sortSlice(
      cols,
      null,
      [
        { column: 'a', desc: false },
        { column: 'b', desc: true },
      ],
      0,
      5,
    );
    expect(rows.map((r) => r['i'])).toEqual([1, 4, 0, 2, 3]);
  });

  it('BigInt cells normalize to numbers in rows; undefined normalizes to null', () => {
    const cols = { v: [2n, 1n, undefined] };
    const { rows } = sortSlice(cols, null, [{ column: 'v', desc: false }], 0, 3);
    expect(rows).toEqual([{ v: 1 }, { v: 2 }, { v: null }]);
  });

  it('boolean desc: true first, nulls still last', () => {
    const cols = { v: [false, true, null, true] };
    const { rows } = sortSlice(cols, null, [{ column: 'v', desc: true }], 0, 4);
    expect(rows.map((r) => r['v'])).toEqual([true, true, false, null]);
  });
});
