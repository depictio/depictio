import { describe, expect, it } from 'vitest';

import {
  chi2InvCdf1df,
  classifyTiers,
  genomicInflation,
  matchSearch,
  offeredDeViews,
  qqConfidenceBand,
  qqSeries,
  rankTopN,
  resolveDeView,
  tierCounts,
} from './deViews';

describe('classifyTiers', () => {
  it('splits by sign once both thresholds are passed', () => {
    const tiers = classifyTiers([2, -2, 0.5, 3], 1, (i) => i !== 3);
    expect(tiers).toEqual(['UP', 'DN', 'NS', 'NS']);
  });

  it('treats a missing effect as not significant', () => {
    expect(classifyTiers([null, undefined, NaN], 0, () => true)).toEqual(['NS', 'NS', 'NS']);
  });

  it('counts in UP / DN / NS order', () => {
    expect(Object.keys(tierCounts(['NS', 'UP']))).toEqual(['UP', 'DN', 'NS']);
    expect(tierCounts(['UP', 'UP', 'DN', 'NS'])).toEqual({ UP: 2, DN: 1, NS: 1 });
  });
});

describe('rankTopN', () => {
  it('keeps the highest scores and drops non-finite ones', () => {
    expect([...rankTopN([1, NaN, 5, 3], 2)].sort()).toEqual([2, 3]);
  });

  it('labels nothing when the budget is zero', () => {
    expect(rankTopN([1, 2, 3], 0).size).toBe(0);
  });
});

describe('matchSearch', () => {
  it('is null for an empty query so the caller falls back to top-N', () => {
    expect(matchSearch(['a'], ['b'], '   ')).toBeNull();
  });

  it('matches the id or the label, case-insensitively', () => {
    const hits = matchSearch(['GENE1', 'gene2'], ['alpha', 'BETA'], 'beta');
    expect([...(hits ?? [])]).toEqual([1]);
  });
});

describe('qqSeries', () => {
  it('sorts ascending and puts the largest expected value first', () => {
    const series = qqSeries([0.5, 0.01, 0.9], [0, 1, 2], ['a', 'b', 'c']);
    expect(series.n).toBe(3);
    expect(series.ps).toEqual([0.01, 0.5, 0.9]);
    expect(series.ids).toEqual(['b', 'a', 'c']);
    expect(series.expected[0]).toBeGreaterThan(series.expected[2]);
    expect(series.observed[0]).toBeCloseTo(2, 10);
  });

  it('drops values that are not p-values rather than plotting them at infinity', () => {
    expect(qqSeries([0, 1.5, null, 0.2], [0, 1, 2, 3], null).n).toBe(1);
  });
});

describe('genomic inflation', () => {
  it('reads about one for p-values drawn uniformly', () => {
    const ps = Array.from({ length: 999 }, (_, k) => (k + 1) / 1000);
    expect(genomicInflation(ps)).toBeCloseTo(1, 1);
  });

  it('grows when the whole distribution is shifted', () => {
    const ps = Array.from({ length: 999 }, (_, k) => ((k + 1) / 1000) ** 2);
    expect(genomicInflation(ps)).toBeGreaterThan(1.5);
  });

  it('is NaN with nothing to summarise', () => {
    expect(Number.isNaN(genomicInflation([]))).toBe(true);
  });

  it('sends a certain p-value to a zero chi-square', () => {
    expect(chi2InvCdf1df(1)).toBe(0);
    expect(chi2InvCdf1df(0)).toBe(Infinity);
  });
});

describe('qqConfidenceBand', () => {
  it('brackets the expected line and never dips below zero', () => {
    const band = qqConfidenceBand(50);
    expect(band.x).toHaveLength(50);
    for (let i = 0; i < band.x.length; i++) {
      expect(band.lower[i]).toBeLessThanOrEqual(band.upper[i]);
      expect(band.lower[i]).toBeGreaterThanOrEqual(0);
    }
  });
});

describe('offeredDeViews', () => {
  it('offers the volcano alone when nothing else is bound', () => {
    expect(offeredDeViews({ significance_is_neg_log10: true })).toEqual(['volcano']);
  });

  it('adds the MA view once abundance is bound', () => {
    expect(
      offeredDeViews({ avg_log_intensity_col: 'base_mean', significance_is_neg_log10: true }),
    ).toEqual(['volcano', 'ma']);
  });

  it('adds the QQ view when the significance column holds raw p-values', () => {
    expect(offeredDeViews({})).toEqual(['volcano', 'qq']);
  });

  it('honours an explicit list, intersected with what the bindings allow', () => {
    expect(offeredDeViews({ views: ['ma', 'qq'] })).toEqual(['qq']);
  });

  it('falls back to the first offered view when the stored one is gone', () => {
    expect(resolveDeView('ma', ['volcano', 'qq'])).toBe('volcano');
    expect(resolveDeView('qq', ['volcano', 'qq'])).toBe('qq');
  });
});
