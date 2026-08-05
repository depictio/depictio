/**
 * Aggregate kernel vs. Polars ground truth in the server's _agg_value forms
 * (dashboards routes.py:1290). Exact for ints, 1e-9 relative for floats —
 * the spike showed bit-identical is achievable.
 */

import { describe, expect, it } from 'vitest';

import type { AggFn } from '../../src/engine/QueryEngine';
import { expectClose, expected, openFixture } from './helpers';

const NUM_AGGS: AggFn[] = [
  'sum',
  'mean',
  'median',
  'min',
  'max',
  'count',
  'nunique',
  'std',
  'var',
  'first',
  'last',
];

const STR_AGGS: AggFn[] = ['count', 'nunique', 'mode', 'min', 'max', 'first', 'last'];

async function maskInStr() {
  const { engine, handle } = await openFixture();
  const { mask } = await engine.mask(handle, [
    { kind: 'in', column: 'category_str', values: ['alpha', 'beta'] },
  ]);
  return { engine, handle, mask };
}

describe('aggregate: full table (mask = null)', () => {
  for (const col of ['value_f64', 'value_i64'] as const) {
    it(`matches Polars on ${col} for every numeric agg`, async () => {
      const { engine, handle } = await openFixture();
      const results = await engine.aggregate(
        handle,
        null,
        NUM_AGGS.map((fn) => ({ col, fn })),
      );
      NUM_AGGS.forEach((fn, i) => {
        const exp = expected.aggregates['full'][col][fn] as number | string | null;
        try {
          expectClose(results[i], exp);
        } catch (e) {
          throw new Error(`${col}.${fn}: ${(e as Error).message}`);
        }
      });
    });
  }

  it('matches Polars on category_str (count/nunique/mode/min/max/first/last)', async () => {
    const { engine, handle } = await openFixture();
    const results = await engine.aggregate(
      handle,
      null,
      STR_AGGS.map((fn) => ({ col: 'category_str', fn })),
    );
    STR_AGGS.forEach((fn, i) => {
      expect(results[i], `category_str.${fn}`).toBe(
        expected.aggregates['full']['category_str'][fn],
      );
    });
  });

  it('mode counts null as a value like polars — null-heavy Int64 column yields the server\'s str(None) artifact', async () => {
    const { engine, handle } = await openFixture();
    const [mode] = await engine.aggregate(handle, null, [{ col: 'value_i64', fn: 'mode' }]);
    // value_i64 has more nulls (128) than any single value's count, polars
    // mode() counts null, and _agg_value str()'s the None winner -> "None".
    expect(expected.aggregates['full']['value_i64']['mode']).toBe('None');
    expect(mode).toBe('None');
  });

  it('count is the NON-null count, nunique counts null as distinct', async () => {
    const { engine, handle } = await openFixture();
    const [count] = await engine.aggregate(handle, null, [{ col: 'category_str', fn: 'count' }]);
    expect(count).toBe(expected.rows - expected.null_counts['category_str']);
    const [nunique] = await engine.aggregate(handle, null, [
      { col: 'category_str', fn: 'nunique' },
    ]);
    // 5 categories + 1 for null (polars n_unique counts null as a value)
    expect(nunique).toBe(6);
  });
});

describe('aggregate: under a mask', () => {
  it('matches Polars on the in_str-filtered subset', async () => {
    const { engine, handle, mask } = await maskInStr();
    for (const col of ['value_f64', 'value_i64'] as const) {
      const results = await engine.aggregate(
        handle,
        mask,
        NUM_AGGS.map((fn) => ({ col, fn })),
      );
      NUM_AGGS.forEach((fn, i) => {
        const exp = expected.aggregates['masked_in_str'][col][fn] as number | string | null;
        try {
          expectClose(results[i], exp);
        } catch (e) {
          throw new Error(`${col}.${fn}: ${(e as Error).message}`);
        }
      });
    }
    const strResults = await engine.aggregate(
      handle,
      mask,
      STR_AGGS.map((fn) => ({ col: 'category_str', fn })),
    );
    STR_AGGS.forEach((fn, i) => {
      expect(strResults[i], `category_str.${fn}`).toBe(
        expected.aggregates['masked_in_str']['category_str'][fn],
      );
    });
  });
});

describe('aggregate: empty mask (server empty-selection returns)', () => {
  it('sum -> 0 on numeric, count/nunique -> 0, everything else -> null', async () => {
    const { engine, handle } = await openFixture();
    const empty = new Uint8Array(expected.rows); // all zeros
    for (const col of ['value_f64', 'value_i64'] as const) {
      const results = await engine.aggregate(
        handle,
        empty,
        NUM_AGGS.map((fn) => ({ col, fn })),
      );
      NUM_AGGS.forEach((fn, i) => {
        const exp = expected.aggregates['empty'][col][fn] as number | string | null;
        expect(results[i], `${col}.${fn} on empty mask`).toBe(exp);
      });
    }
    const strResults = await engine.aggregate(
      handle,
      empty,
      STR_AGGS.map((fn) => ({ col: 'category_str', fn })),
    );
    STR_AGGS.forEach((fn, i) => {
      expect(strResults[i], `category_str.${fn} on empty mask`).toBe(
        expected.aggregates['empty']['category_str'][fn],
      );
    });
  });

  it('pins the exact empty-selection contract from Polars', () => {
    // Guard against fixture drift: the generated JSON must itself encode
    // sum=0.0 / count=0 / nunique=0 / null-for-the-rest (verified live on
    // the server's Polars version by generate_fixture.py).
    const e = expected.aggregates['empty']['value_f64'];
    expect(e['sum']).toBe(0.0);
    expect(e['count']).toBe(0);
    expect(e['nunique']).toBe(0);
    for (const fn of ['mean', 'median', 'min', 'max', 'std', 'var', 'first', 'last']) {
      expect(e[fn], `empty ${fn}`).toBeNull();
    }
  });

  it('sum on a String column is null (server catch path), even when empty', async () => {
    const { engine, handle } = await openFixture();
    const empty = new Uint8Array(expected.rows);
    const [full] = await engine.aggregate(handle, null, [{ col: 'category_str', fn: 'sum' }]);
    const [masked] = await engine.aggregate(handle, empty, [{ col: 'category_str', fn: 'sum' }]);
    expect(full).toBeNull();
    expect(masked).toBeNull();
  });

  it('std/var need at least two values (ddof=1)', async () => {
    const { engine, handle } = await openFixture();
    // Mask exactly one non-null value_f64 row.
    const batch = await engine.columns(handle, ['value_f64']);
    const col = batch['value_f64'];
    const one = new Uint8Array(expected.rows);
    for (let i = 0; i < col.length; i++) {
      if (col[i] != null) {
        one[i] = 1;
        break;
      }
    }
    const [std, variance] = await engine.aggregate(handle, one, [
      { col: 'value_f64', fn: 'std' },
      { col: 'value_f64', fn: 'var' },
    ]);
    expect(std).toBeNull();
    expect(variance).toBeNull();
  });
});
