import { describe, expect, it } from 'vitest';

import {
  chi2InvCdf1df,
  classifyTiers,
  contrastLabel,
  contrastSides,
  genomicInflation,
  matchSearch,
  maTableOf,
  offeredDeViews,
  qqConfidenceBand,
  qqSeries,
  rankTopN,
  resolveDeView,
  resolveEffectLabel,
  significancePredicate,
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

  it('keeps the source row of each point, so a caller can look up its other columns', () => {
    const series = qqSeries([0.5, 0.01, 0.9, 7], [0, 1, 2, 3], null);
    expect(series.indices).toEqual([1, 0, 2]);
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

describe('maTableOf', () => {
  it('reads the MA table only when the test table has no abundance column', () => {
    expect(maTableOf({ ma_wf_id: 'wf', ma_dc_id: 'dc' })).toEqual({ wfId: 'wf', dcId: 'dc' });
    expect(maTableOf({ ma_wf_id: 'wf', ma_dc_id: 'dc', avg_log_intensity_col: 'base_mean' })).toBeNull();
    expect(maTableOf({ ma_dc_id: 'dc' })).toBeNull();
  });
});

describe('offeredDeViews', () => {
  it('offers the volcano alone when nothing else is bound', () => {
    expect(offeredDeViews({ significance_is_neg_log10: true })).toEqual(['volcano']);
  });

  it('adds the MA view for an MA table of its own', () => {
    expect(
      offeredDeViews({ ma_wf_id: 'wf', ma_dc_id: 'dc', significance_is_neg_log10: true }),
    ).toEqual(['volcano', 'ma']);
    // An unresolved tag leaves no id: no MA view rather than an empty one.
    expect(offeredDeViews({ ma_wf_id: 'wf', significance_is_neg_log10: true })).toEqual(['volcano']);
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

describe('significancePredicate', () => {
  it('counts an underflowed p of 0 as significant, the cutoff inclusive', () => {
    const pass = significancePredicate([0, 0.05, 0.051, null, NaN, -1], {
      isNegLog10: false,
      threshold: 0.05,
    });
    expect([0, 1, 2, 3, 4, 5].map(pass)).toEqual([true, true, false, false, false, false]);
  });

  it('reads a -log10 column against -log10 of the p cutoff', () => {
    const pass = significancePredicate([10, 9.9, Infinity, null], {
      isNegLog10: true,
      threshold: 1e-10,
    });
    expect([0, 1, 2, 3].map(pass)).toEqual([true, false, true, false]);
  });

  it('gives the volcano and MA tier counts the same answer on the same column', () => {
    const padj = [0, 0.01, 0.2, 0.04];
    const lfc = [2, -3, 4, 0.5];
    const pass = significancePredicate(padj, { isNegLog10: false, threshold: 0.05 });
    expect(tierCounts(classifyTiers(lfc, 1, pass))).toEqual({ UP: 1, DN: 1, NS: 2 });
  });

  it('lets every row through when there is no significance column', () => {
    expect(significancePredicate([], { isNegLog10: false, threshold: 0.05 })(3)).toBe(true);
  });
});

describe('contrast sides', () => {
  const groups = {
    reference: 'Athens',
    contrast_prefix: 'locality',
    contrast_separator: '_vs_',
    group_colors: { Athens: '#1a4f8f', Naples: '#00a550', Barcelona: '#f5a11b' },
  };
  const fallback = { positive: 'p', negative: 'n' };

  it('tests the group the value names against the shared reference', () => {
    const sides = contrastSides('localityBarcelona', groups, fallback);
    expect([sides.positiveName, sides.negativeName]).toEqual(['Barcelona', 'Athens']);
    expect(contrastLabel('localityBarcelona', groups)).toBe('Barcelona vs Athens');
  });

  it('lets a value that names both sides carry its own baseline and colours', () => {
    const sides = contrastSides('localityNaples_vs_Barcelona', groups, fallback);
    expect([sides.positiveName, sides.negativeName]).toEqual(['Naples', 'Barcelona']);
    expect([sides.positive, sides.negative]).toEqual(['#00a550', '#f5a11b']);
    expect(contrastLabel('localityNaples_vs_Barcelona', groups)).toBe('Naples vs Barcelona');
  });

  it('ignores the separator when none is configured', () => {
    const { contrast_separator: _unused, ...plain } = groups;
    expect(contrastSides('localityNaples_vs_Barcelona', plain, fallback).negativeName).toBe('Athens');
  });
});

describe('resolveEffectLabel', () => {
  const groups = { reference: 'Athens', contrast_prefix: 'locality', contrast_separator: '_vs_' };

  it('names the baseline of the one contrast on show', () => {
    const label = 'Log-fold change vs {reference}';
    expect(resolveEffectLabel(label, ['localityNaples_vs_Barcelona', 'localityNaples_vs_Barcelona'], groups))
      .toBe('Log-fold change vs Barcelona');
    expect(resolveEffectLabel(label, ['localityNaples'], groups)).toBe('Log-fold change vs Athens');
  });

  it('falls back on the configured reference when several contrasts are drawn', () => {
    expect(
      resolveEffectLabel('vs {reference}', ['localityNaples', 'localityNaples_vs_Barcelona'], groups),
    ).toBe('vs Athens');
  });

  it('leaves a label without the token, and an absent one, alone', () => {
    expect(resolveEffectLabel('Log fold change', ['x'], groups)).toBe('Log fold change');
    expect(resolveEffectLabel(null, ['x'], groups)).toBeUndefined();
  });
});
