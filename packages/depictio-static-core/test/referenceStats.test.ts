/**
 * The twin of reference_stats.py: the values below were computed by
 * `compute_stat` (polars) on the same input, and the tail test pins
 * routes.py `_tail_with_stat_threshold` — a cut given as a statistic is
 * settled on the unreduced rows, so every row past it survives the sample.
 */

import { describe, expect, it } from 'vitest';

import { reduceFrame } from '../src/advancedViz';
import { DEFAULT_LIMITS } from '../src/manifest';
import {
  computeReferenceRequests,
  computeStat,
  parseReferenceRequests,
  roundReference,
} from '../src/referenceStats';

// Nulls, NaN, an infinity and a non-numeric string are all left out; numeric
// strings are cast, as `cast(pl.Float64, strict=False)` does.
const MIXED = [3.5, null, '7', Number.NaN, 1, Number.POSITIVE_INFINITY, 10, -2.25, 'x', 4];

describe('computeStat', () => {
  it.each([
    ['median', 3.75],
    ['mean', 3.875],
    ['p75', 6.25],
    ['p90', 8.5],
    ['p95', 9.25],
    ['p99', 9.850000000000001],
  ])('%s matches polars', (stat, expected) => {
    expect(computeStat(MIXED, stat)).toBeCloseTo(expected, 12);
  });

  it('is null when no finite value is left', () => {
    expect(computeStat([null, 'x', Number.NaN], 'median')).toBeNull();
  });

  it('refuses an unknown statistic', () => {
    expect(() => computeStat([1], 'p50')).toThrow();
  });
});

describe('reference requests', () => {
  it('drops malformed entries and answers null for a missing column', () => {
    const requests = parseReferenceRequests({
      line: { column: 'score', stat: 'median' },
      gone: { column: 'absent', stat: 'mean' },
      bad: { column: 'score', stat: 'p50' },
      junk: 'median',
    });
    expect(Object.keys(requests)).toEqual(['line', 'gone']);
    expect(computeReferenceRequests({ score: [1, 2, 3, 10] }, requests)).toEqual({
      line: 2.5,
      gone: null,
    });
  });

  it('rounds like the response, to six significant digits', () => {
    expect(roundReference(9.850000000000001)).toBe(9.85);
    expect(roundReference(null)).toBeNull();
  });
});

describe('a tail cut given as a statistic', () => {
  const n = 10_000;
  const score = Array.from({ length: n }, (_, i) => i);

  it('keeps every row past the statistic of the unreduced column', () => {
    const out = reduceFrame({
      columns: ['score'],
      data: { score },
      vizKind: 'volcano',
      tail: { column: 'score', direction: 'high', threshold_stat: 'p99' },
      limits: { ...DEFAULT_LIMITS, figure_max_points: 1_000 },
    });
    expect(out.sampling.policy).toBe('tail');
    // p99 of 0..9999 is 9899.01: the 100 rows from 9900 up are the tail.
    const kept = (out.rows['score'] as number[]).filter((v) => v >= 9899.01);
    expect(kept).toHaveLength(100);
  });

  it('falls back to the role table when the statistic has nothing to read', () => {
    expect(() =>
      reduceFrame({
        columns: ['score', 'empty'],
        data: { score, empty: score.map(() => null) },
        vizKind: 'volcano',
        tail: { column: 'empty', direction: 'high', threshold_stat: 'p99' },
        limits: { ...DEFAULT_LIMITS, figure_max_points: 1_000 },
      }),
    ).not.toThrow();
  });
});
