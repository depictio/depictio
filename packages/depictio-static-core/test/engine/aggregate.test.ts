/**
 * Aggregate kernel vs. Polars ground truth in the server's _agg_value forms
 * (dashboards routes.py:1290). Exact for ints, 1e-9 relative for floats —
 * the spike showed bit-identical is achievable.
 */

import { describe, expect, it } from 'vitest';

import { aggregateValues, type BoxPlotStats } from '../../src/engine/aggregate';
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

// ---------------------------------------------------------------------------
// box_plot_stats — the one COMPOUND aggregation
// ---------------------------------------------------------------------------

/** Every expectation below is the literal dict `_agg_value(pl.Series(...),
 *  "box_plot_stats")` returned on the repo's Polars pin (1.42.1), captured by
 *  feeding these exact inputs to the server function. */
function box(values: unknown[]): BoxPlotStats | null {
  return aggregateValues(values, null, 'box_plot_stats', true) as BoxPlotStats | null;
}

function expectStats(actual: BoxPlotStats | null, exp: BoxPlotStats): void {
  expect(actual).not.toBeNull();
  const a = actual as BoxPlotStats;
  for (const k of [
    'min',
    'max',
    'q1',
    'q3',
    'median',
    'mean',
    'lower_whisker',
    'upper_whisker',
  ] as const) {
    try {
      expectClose(a[k], exp[k]);
    } catch (e) {
      throw new Error(`${k}: ${(e as Error).message}`);
    }
  }
  expect(a.outlier_count, 'outlier_count').toBe(exp.outlier_count);
  expect(a.outliers.length, 'outliers.length').toBe(exp.outliers.length);
  exp.outliers.forEach((v, i) => expectClose(a.outliers[i], v));
}

describe('aggregate: box_plot_stats vs the server dict', () => {
  it('normal spread — Tukey fence pushes the far value out to an outlier', () => {
    // Deliberately UNSORTED so the outlier list order is meaningful.
    expectStats(box([7, 2, 100, 4, 5, 1, 9, 3, 8, 6]), {
      min: 1.0,
      max: 100.0,
      q1: 3.25,
      q3: 7.75,
      median: 5.5,
      mean: 14.5,
      // Whiskers stop at the most extreme datum still inside the fence, NOT at
      // the fence itself (which is q3 + 1.5*4.5 = 14.5 here).
      lower_whisker: 1.0,
      upper_whisker: 9.0,
      outliers: [100.0],
      outlier_count: 1,
    });
  });

  it('IQR=0 on a constant column — fences collapse onto q1=q3, no outliers', () => {
    expectStats(box([5, 5, 5, 5]), {
      min: 5.0,
      max: 5.0,
      q1: 5.0,
      q3: 5.0,
      median: 5.0,
      mean: 5.0,
      // Not the min/max FALLBACK: every value compares equal to both fences,
      // so `within` is non-empty and the whiskers land on the constant.
      lower_whisker: 5.0,
      upper_whisker: 5.0,
      outliers: [],
      outlier_count: 0,
    });
  });

  it('IQR=0 with spread — a zero-width fence makes every off-constant value an outlier, in ROW order', () => {
    expectStats(box([5, 100, 5, 5, 5, -40]), {
      min: -40.0,
      max: 100.0,
      q1: 5.0,
      q3: 5.0,
      median: 5.0,
      mean: 13.333333333333334,
      lower_whisker: 5.0,
      upper_whisker: 5.0,
      // 100 before -40: the server filters the UNSORTED series, so the dot
      // list is in row order, not ascending order.
      outliers: [100.0, -40.0],
      outlier_count: 2,
    });
  });

  it('all-null column is null, not a zeroed payload', () => {
    expect(box([null, null, null])).toBeNull();
    // Same for a column with no numeric values at all.
    expect(box(['a', 'b'])).toBeNull();
  });

  it('single row — every marker collapses onto the one value', () => {
    expectStats(box([42]), {
      min: 42.0,
      max: 42.0,
      q1: 42.0,
      q3: 42.0,
      median: 42.0,
      mean: 42.0,
      lower_whisker: 42.0,
      upper_whisker: 42.0,
      outliers: [],
      outlier_count: 0,
    });
  });

  it('median is linear-interpolated on an EVEN count and exact on an ODD one', () => {
    // Even: q*(n-1) = 1.5 -> 2 + 0.5*(3-2) = 2.5, not the 2 or 3 a
    // nearest-rank quantile would give.
    const even = box([1, 2, 3, 10]) as BoxPlotStats;
    expect(even.median).toBeCloseTo(2.5, 12);
    expect(even.q1).toBeCloseTo(1.75, 12);
    expect(even.q3).toBeCloseTo(4.75, 12);
    const odd = box([1, 2, 3]) as BoxPlotStats;
    expect(odd.median).toBe(2);
    expect(odd.q1).toBeCloseTo(1.5, 12);
    expect(odd.q3).toBeCloseTo(2.5, 12);
    // The scalar `median` agg must agree with the compound payload's field —
    // both are quantile(0.5, linear).
    expect(aggregateValues([1, 2, 3, 10], null, 'median', true)).toBe(even.median);
  });

  it('nulls are dropped before the reduction, like the server cast+drop_nulls', () => {
    expectStats(box([3, null, 1, null, 2, 50]), {
      min: 1.0,
      max: 50.0,
      q1: 1.75,
      q3: 14.75,
      median: 2.5,
      mean: 14.0,
      lower_whisker: 1.0,
      upper_whisker: 3.0,
      outliers: [50.0],
      outlier_count: 1,
    });
  });

  it('matches Polars through the real Parquet path (fixture value_f64, 126 nulls)', async () => {
    const { engine, handle } = await openFixture();
    const [stats] = await engine.aggregate(handle, null, [
      { col: 'value_f64', fn: 'box_plot_stats' },
    ]);
    expectStats(stats as BoxPlotStats, {
      min: -6.583291,
      max: 6.793622,
      q1: -1.36753925,
      q3: 1.34355925,
      median: 0.033745,
      mean: 0.01019037993596586,
      lower_whisker: -5.374904,
      upper_whisker: 5.3731,
      outliers: [
        6.026977, -5.584713, -6.583291, -6.342375, -6.151694, 6.793622, 6.508922, 5.764453,
        -5.675585,
      ],
      outlier_count: 9,
    });
  });

  it('reduces the masked subset, not the whole column', async () => {
    const { engine, handle, mask } = await maskInStr();
    const [full] = await engine.aggregate(handle, null, [
      { col: 'value_f64', fn: 'box_plot_stats' },
    ]);
    const [masked] = await engine.aggregate(handle, mask, [
      { col: 'value_f64', fn: 'box_plot_stats' },
    ]);
    const f = full as BoxPlotStats;
    const m = masked as BoxPlotStats;
    expect(m.outlier_count).toBeLessThan(f.outlier_count);
    // The masked median must be the masked `median` agg — one kernel, and the
    // card's primary value and its box plot must never disagree.
    const [medianAgg] = await engine.aggregate(handle, mask, [{ col: 'value_f64', fn: 'median' }]);
    expect(m.median).toBe(medianAgg);
  });

  it('caps the outlier list at 100 while outlier_count stays exact', () => {
    // 150 far-out values against a core large enough to keep BOTH quartiles
    // inside it (q3 sits at 0.75*(n-1), so the tail must stay under a quarter
    // of the rows or it drags the fence out past itself).
    const core = Array.from({ length: 2000 }, (_, i) => (i % 5) - 2);
    const far = Array.from({ length: 150 }, (_, i) => 1000 + i);
    const s = box([...core, ...far]) as BoxPlotStats;
    expect(s.outlier_count).toBe(150);
    expect(s.outliers.length).toBe(100);
    // head(100) of the row-ordered outliers, so the first one wins.
    expect(s.outliers[0]).toBe(1000);
    expect(s.outliers[99]).toBe(1099);
  });
});
