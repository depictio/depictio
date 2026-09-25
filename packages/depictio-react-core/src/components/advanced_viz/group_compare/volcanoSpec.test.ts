import { describe, expect, it } from 'vitest';

import type { GroupCompareRow } from '../../../api';
import {
  MIN_PLOTTED_P,
  negLog10,
  tierCounts,
  tierFor,
  topLabelIndices,
  volcanoPoints,
} from './volcanoSpec';

function row(over: Partial<GroupCompareRow>): GroupCompareRow {
  return {
    feature: 'gene_01',
    mean_a: 10,
    mean_b: 1,
    log2fc: 3,
    p_value: 1e-8,
    fdr: 1e-6,
    significant: true,
    direction: 'up',
    ...over,
  };
}

describe('negLog10', () => {
  it('maps a plain p-value onto its decade', () => {
    expect(negLog10(0.01)).toBeCloseTo(2);
    expect(negLog10(1)).toBeCloseTo(0);
  });

  it('floors an underflowed p instead of returning Infinity', () => {
    expect(negLog10(0)).toBeCloseTo(-Math.log10(MIN_PLOTTED_P));
    expect(Number.isFinite(negLog10(0))).toBe(true);
  });

  it('reads a missing statistic as the axis origin', () => {
    expect(negLog10(null)).toBe(0);
    expect(negLog10(undefined)).toBe(0);
    expect(negLog10(Number.NaN)).toBe(0);
  });
});

describe('tierFor', () => {
  it('needs both thresholds, not either', () => {
    expect(tierFor(row({ fdr: 1e-6, log2fc: 3 }), 0.05, 1)).toBe('UP');
    // Significant but barely moved.
    expect(tierFor(row({ fdr: 1e-6, log2fc: 0.2 }), 0.05, 1)).toBe('NS');
    // Moved a lot but not supported.
    expect(tierFor(row({ fdr: 0.4, log2fc: 3 }), 0.05, 1)).toBe('NS');
  });

  it('reads the sign of the fold change as the direction', () => {
    expect(tierFor(row({ log2fc: -3 }), 0.05, 1)).toBe('DN');
  });

  it('treats a missing statistic as not significant', () => {
    expect(tierFor(row({ fdr: null }), 0.05, 1)).toBe('NS');
    expect(tierFor(row({ log2fc: null }), 0.05, 1)).toBe('NS');
  });

  it('is recomputed from the thresholds, not read off the server flag', () => {
    // The server called it significant at its own thresholds; a reader who
    // tightened the effect-size line must see it fall out.
    expect(tierFor(row({ significant: true, log2fc: 1.2 }), 0.05, 4)).toBe('NS');
  });
});

describe('volcanoPoints', () => {
  const rows = [
    row({ feature: 'a', log2fc: 3, fdr: 1e-6 }),
    row({ feature: 'b', log2fc: -2, fdr: 1e-3 }),
    row({ feature: 'c', log2fc: 0.1, fdr: 0.9, significant: false, direction: 'ns' }),
    row({ feature: 'd', log2fc: null }),
  ];

  it('drops features with no fold change and keeps the input order', () => {
    const points = volcanoPoints(rows, 0.05, 1);
    expect(points.map((p) => p.feature)).toEqual(['a', 'b', 'c']);
  });

  it('places each point at its effect size and adjusted significance', () => {
    const [a] = volcanoPoints(rows, 0.05, 1);
    expect(a.x).toBe(3);
    expect(a.y).toBeCloseTo(6);
    expect(a.tier).toBe('UP');
  });

  it('counts the tiers the frame badges', () => {
    expect(tierCounts(volcanoPoints(rows, 0.05, 1))).toEqual({ UP: 1, DN: 1, NS: 1 });
  });
});

describe('topLabelIndices', () => {
  const rows = [
    row({ feature: 'big', log2fc: 5, fdr: 1e-10 }),
    row({ feature: 'mid', log2fc: 2, fdr: 1e-4 }),
    row({ feature: 'small', log2fc: 1.1, fdr: 0.02 }),
    row({ feature: 'noise', log2fc: 0.1, fdr: 0.9, significant: false, direction: 'ns' }),
  ];

  it('labels the strongest features on both axes first', () => {
    const points = volcanoPoints(rows, 0.05, 1);
    expect(Array.from(topLabelIndices(points, 2)).sort()).toEqual([0, 1]);
  });

  it('never labels a feature that failed the thresholds', () => {
    const points = volcanoPoints(rows, 0.05, 1);
    expect(topLabelIndices(points, 10).has(3)).toBe(false);
  });

  it('labels nothing when the budget is zero', () => {
    expect(topLabelIndices(volcanoPoints(rows, 0.05, 1), 0).size).toBe(0);
  });
});
