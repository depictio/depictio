import { describe, expect, it } from 'vitest';

import { NEUTRAL_CATEGORY_COLOR } from '../../../categoryColors';
import {
  badgeColourOf,
  barFraction,
  barLabel,
  barRange,
  boundFromColumn,
  categoricalColumns,
  clampTopN,
  columnLabel,
  columnsToFetch,
  denseRanks,
  distinctValues,
  formatCell,
  isFiltering,
  isNumericColumn,
  missingColumns,
  pickDefaultRow,
  placePopover,
  rankRows,
  rankTier,
  rankedEcho,
  rowsKept,
  sortableColumns,
  toNumber,
  type RankedRow,
} from './rankedTable';

describe('toNumber', () => {
  it('reads numbers and numeric strings, nothing else', () => {
    expect(toNumber(3)).toBe(3);
    expect(toNumber('4.5')).toBe(4.5);
    expect(toNumber(' 7 ')).toBe(7);
    expect(toNumber('')).toBeNull();
    expect(toNumber('absent')).toBeNull();
    expect(toNumber(null)).toBeNull();
    expect(toNumber(Number.NaN)).toBeNull();
    expect(toNumber(Infinity)).toBeNull();
  });
});

describe('denseRanks', () => {
  it('shares a rank between ties and leaves no gap after them', () => {
    expect(denseRanks([9, 9, 7, 5, 5, 5, 1])).toEqual([1, 1, 2, 3, 3, 3, 4]);
  });
  it('is empty for no rows', () => {
    expect(denseRanks([])).toEqual([]);
  });
});

describe('rankTier', () => {
  it('gives a medal to ranks 1 to 3 only', () => {
    expect([1, 2, 3].map(rankTier)).toEqual([1, 2, 3]);
    expect(rankTier(4)).toBeNull();
    expect(rankTier(0)).toBeNull();
    expect(rankTier('2')).toBe(2);
    expect(rankTier('B')).toBeNull();
    expect(rankTier(null)).toBeNull();
  });
});

const cols = (o: Record<string, unknown[]>) => o;

describe('rankRows', () => {
  const rows = cols({ gene: ['A', 'B', 'C', 'D', 'E'], s: [3, 9, 9, 1, 5] });

  it('orders by score, best first, ties in source order', () => {
    const list = rankRows(rows, { score: 's' }, { descending: true, topN: 10 });
    expect(list.rows.map((r) => r.source)).toEqual([1, 2, 4, 0, 3]);
    expect(list.rows.map((r) => r.rank)).toEqual([1, 1, 2, 3, 4]);
    expect(list.rows.map((r) => r.tier)).toEqual([1, 1, 2, 3, null]);
  });

  it('puts the smallest first when not descending (a p-value)', () => {
    const list = rankRows(rows, { score: 's' }, { descending: false, topN: 10 });
    expect(list.rows.map((r) => r.source)).toEqual([3, 0, 4, 1, 2]);
    expect(list.rows[0].rank).toBe(1);
  });

  it('keeps the top N and still counts everything ranked', () => {
    const list = rankRows(rows, { score: 's' }, { descending: true, topN: 2 });
    expect(list.rows).toHaveLength(2);
    expect(list.ranked).toBe(5);
    expect(list.unscored).toBe(0);
  });

  it('does not rank a row without a score, and says so', () => {
    const list = rankRows(
      cols({ s: [2, null, 'n/a', '', 8] }),
      { score: 's' },
      { descending: true, topN: 10 },
    );
    expect(list.rows.map((r) => r.source)).toEqual([4, 0]);
    expect(list.unscored).toBe(3);
    expect(list.ranked).toBe(2);
  });

  it('shows a precomputed rank as stored, falling back to the dense rank', () => {
    const list = rankRows(
      cols({ s: [10, 20, 30], r: [3, null, '1'] }),
      { score: 's', rank: 'r' },
      { descending: true, topN: 10 },
    );
    // order by score: source 2, 1, 0 -> stored ranks 1, (missing -> dense 2), 3
    expect(list.rows.map((r) => r.rank)).toEqual([1, 2, 3]);
    expect(list.rows.map((r) => r.tier)).toEqual([1, 2, 3]);
  });

  it('takes the medal from the precomputed rank, not from the position', () => {
    const list = rankRows(
      cols({ s: [10, 20], r: [7, 8] }),
      { score: 's', rank: 'r' },
      { descending: true, topN: 10 },
    );
    expect(list.rows.map((r) => r.tier)).toEqual([null, null]);
  });

  it('handles an empty frame and a missing score column', () => {
    expect(rankRows({}, { score: 's' }, { descending: true, topN: 5 })).toEqual({
      rows: [],
      ranked: 0,
      unscored: 0,
    });
    const noScore = rankRows(cols({ gene: ['A', 'B'] }), { score: 's' }, { descending: true, topN: 5 });
    expect(noScore.rows).toEqual([]);
    expect(noScore.unscored).toBe(2);
  });
});

describe('clampTopN', () => {
  it('keeps the count in range and falls back on nonsense', () => {
    expect(clampTopN(25, 50)).toBe(25);
    expect(clampTopN(0, 50)).toBe(1);
    expect(clampTopN(5000, 50)).toBe(1000);
    expect(clampTopN('x', 50)).toBe(50);
    expect(clampTopN(undefined, 50)).toBe(50);
  });
});

describe('bars', () => {
  it('starts at zero and is full at the largest value shown', () => {
    const range = barRange([5, 10, 20, null]);
    expect(range).toEqual({ lo: 0, hi: 20 });
    expect(barFraction(10, range)).toBe(0.5);
    expect(barFraction(20, range)).toBe(1);
    expect(barFraction(null, range)).toBe(0);
  });

  it('is full at the stated max and clamps what lies past it', () => {
    const range = barRange([5, 30], { max: 25 });
    expect(range.hi).toBe(25);
    expect(barFraction(30, range)).toBe(1);
    expect(barFraction(12.5, range)).toBe(0.5);
  });

  it('starts at the smallest value when some are negative, or at the stated min', () => {
    expect(barRange([-4, 0, 6])).toEqual({ lo: -4, hi: 6 });
    expect(barRange([2, 6], { min: 1 })).toEqual({ lo: 1, hi: 6 });
    expect(barFraction(-9, barRange([-4, 6]))).toBe(0);
  });

  it('never divides by nothing', () => {
    const one = barRange([7]);
    expect(one.hi).toBeGreaterThan(one.lo);
    expect(barFraction(7, one)).toBe(1);
    const none = barRange([]);
    expect(Number.isFinite(barFraction(0, none))).toBe(true);
    const flat = barRange([0, 0]);
    expect(barFraction(0, flat)).toBe(0);
  });
});

describe('bars scaled to a column', () => {
  it('is full at the column bound, so the best row shown is not a full bar', () => {
    // 14 of a possible 18: the default would draw 14 as full.
    expect(barRange([14, 9], {}, { hi: boundFromColumn([18, 18, 17], 'max') })).toEqual({ lo: 0, hi: 18 });
    expect(barFraction(14, barRange([14, 9], {}, { hi: 18 }))).toBeCloseTo(14 / 18);
  });

  it('reads the largest and smallest of the whole frame, skipping blanks', () => {
    expect(boundFromColumn(['3', null, 9, 'x', 4], 'max')).toBe(9);
    expect(boundFromColumn(['3', null, 9, 'x', 4], 'min')).toBe(3);
    expect(boundFromColumn([], 'max')).toBeNull();
    expect(boundFromColumn(undefined, 'min')).toBeNull();
  });

  it('lets a literal min / max win and falls back on the data without a bound', () => {
    expect(barRange([5, 10], { max: 25 }, { hi: 18 }).hi).toBe(25);
    expect(barRange([5, 10], {}, { hi: null })).toEqual({ lo: 0, hi: 10 });
    expect(barRange([5, 10], {}, { lo: 2, hi: 12 })).toEqual({ lo: 2, hi: 12 });
  });

  it('writes the bound beside the value unless told not to', () => {
    expect(barLabel('14', { max_from: 'm' }, 18)).toBe('14 / 18');
    expect(barLabel('0.5', { max_from: 'm', decimals: 2 }, 1)).toBe('0.5 / 1.00');
    expect(barLabel('14', { max_from: 'm', show_bound: false }, 18)).toBe('14');
    expect(barLabel('14', {}, 18)).toBe('14');
    expect(barLabel('14', { max_from: 'm' }, null)).toBe('14');
    expect(barLabel('–', { max_from: 'm' }, 18)).toBe('–');
  });
});

describe('pickDefaultRow', () => {
  const row = (source: number): RankedRow => ({ source, score: 0, rank: source + 1, tier: null });
  const rows = [row(0), row(1), row(2), row(3)];
  const key = (r: RankedRow) => (r.source === 3 ? null : `v${r.source}`);

  it('takes the highest, or the lowest on request', () => {
    expect(pickDefaultRow(rows, [4, 9, 2, 1], 'desc', key)?.source).toBe(1);
    expect(pickDefaultRow(rows, [4, 9, 2, 1], 'asc', key)?.source).toBe(2);
  });

  it('gives a tie to the row ranked higher', () => {
    expect(pickDefaultRow(rows, [7, 7, 7, 7], 'desc', key)?.source).toBe(0);
  });

  it('skips rows without a number or without a key, and says null for none', () => {
    expect(pickDefaultRow(rows, [null, 'x', 3, 100], 'desc', key)?.source).toBe(2);
    expect(pickDefaultRow(rows, [null, 'x', null, 100], 'desc', key)).toBeNull();
    expect(pickDefaultRow(rows, undefined, 'desc', key)).toBeNull();
    expect(pickDefaultRow([], [1], 'desc', key)).toBeNull();
  });
});

describe('formatCell', () => {
  it('writes blanks as a dash', () => {
    for (const v of [null, undefined, '', Number.NaN, Infinity]) expect(formatCell(v)).toBe('–');
  });
  it('fixes decimals when asked and shortens a long float otherwise', () => {
    expect(formatCell(23, 1)).toBe('23.0');
    expect(formatCell(23.456, 1)).toBe('23.5');
    expect(formatCell(23.000001)).toBe('23');
    expect(formatCell(0.000123456)).toBe('0.0001235');
    expect(formatCell(12)).toBe('12');
  });
  it('leaves text, even numeric-looking text, as written', () => {
    expect(formatCell('absent')).toBe('absent');
    expect(formatCell('0.0004')).toBe('0.0004');
    expect(formatCell(true)).toBe('true');
  });
});

describe('labels and columns', () => {
  it('prefers the column label, then the config map, then the name', () => {
    expect(columnLabel('gt', 'Genotype', { gt: 'GT' })).toBe('Genotype');
    expect(columnLabel('gt', null, { gt: 'GT' })).toBe('GT');
    expect(columnLabel('gt', undefined, null)).toBe('gt');
  });

  it('lists the columns a spec names that the frame lacks, once each', () => {
    expect(missingColumns({ a: [], b: [] }, ['a', 'x', null, 'x', 'y', undefined])).toEqual(['x', 'y']);
  });

  it('fetches each column once, the bound ones first', () => {
    expect(
      columnsToFetch(
        { title: 'gene', score: 's', subtitle: 'hgvs', rank: null },
        [{ column: 's' }, { column: 'impact' }],
        ['cadd', 'impact'],
        ['gt1'],
        'gene',
      ),
    ).toEqual(['gene', 's', 'hgvs', 'impact', 'cadd', 'gt1']);
  });
});

describe('badgeColourOf', () => {
  const palette = ['#111111', '#222222', '#333333'];

  it('wears the dashboard colour pinned for the value', () => {
    const source = { category_colors: { impact: { HIGH: '#e03131' } } };
    const colour = badgeColourOf(source, 'impact', ['HIGH', 'LOW', 'MODERATE'], palette);
    expect(colour('HIGH')).toBe('#e03131');
  });

  it('falls back on the palette by place in the sorted universe, whatever order values arrive in', () => {
    const a = badgeColourOf(null, 'impact', ['MODERATE', 'HIGH', 'LOW'], palette);
    const b = badgeColourOf(null, 'impact', ['LOW', 'HIGH', 'MODERATE'], palette);
    for (const v of ['HIGH', 'LOW', 'MODERATE']) expect(a(v)).toBe(b(v));
    expect(a('HIGH')).toBe('#111111');
    expect(a('LOW')).toBe('#222222');
    expect(a('MODERATE')).toBe('#333333');
  });

  it('keeps a pinned value pinned and the others on the palette', () => {
    const source = { category_colors: { impact: { LOW: '#2f9e44' } } };
    const colour = badgeColourOf(source, 'impact', ['HIGH', 'LOW', 'MODERATE'], palette);
    expect(colour('LOW')).toBe('#2f9e44');
    expect(colour('HIGH')).toBe('#111111');
  });

  it('is grey for a value outside the universe and for a blank', () => {
    const colour = badgeColourOf(null, 'impact', ['HIGH'], palette);
    expect(colour('UNSEEN')).toBe(NEUTRAL_CATEGORY_COLOR);
    expect(colour(null)).toBe(NEUTRAL_CATEGORY_COLOR);
    expect(colour('')).toBe(NEUTRAL_CATEGORY_COLOR);
  });
});

describe('placePopover', () => {
  const viewport = { width: 1000, height: 800 };
  const size = { width: 320, height: 200 };

  it('sits right of and below the pointer when there is room', () => {
    expect(placePopover({ x: 100, y: 100 }, size, viewport)).toEqual({ left: 114, top: 114 });
  });

  it('flips to the left and above at the viewport edge', () => {
    const p = placePopover({ x: 900, y: 700 }, size, viewport);
    expect(p.left).toBe(900 - 14 - 320);
    expect(p.top).toBe(700 - 14 - 200);
  });

  it('stays inside a viewport smaller than the popover', () => {
    const p = placePopover({ x: 10, y: 10 }, size, { width: 200, height: 100 });
    expect(p.left).toBe(8);
    expect(p.top).toBe(8);
  });
});

describe('rankedEcho', () => {
  it('says how much of the ranking is drawn, and which end comes first', () => {
    expect(rankedEcho({ shown: 50, ranked: 3412, scoreLabel: 'rank score', descending: true })).toBe(
      'top 50 of 3,412 by rank score (highest first)',
    );
    expect(rankedEcho({ shown: 6, ranked: 6, scoreLabel: 'p', descending: false })).toBe(
      'top 6 by p (lowest first)',
    );
  });
});

describe('rowsKept', () => {
  const rows = {
    gene: ['A', 'B', 'C', 'D'],
    score: [10, 7, null, 3],
    impact: ['HIGH', 'LOW', 'HIGH', ''],
  };
  it('keeps every row (null) while no control narrows', () => {
    expect(rowsKept(rows, { scoreColumn: 'score' })).toBeNull();
    expect(rowsKept(rows, { scoreColumn: 'score', filterColumn: 'impact', filterValues: [] })).toBeNull();
    expect(isFiltering({ scoreColumn: 'score', minScore: null })).toBe(false);
  });
  it('drops rows under a floor, and rows with no score', () => {
    expect(rowsKept(rows, { scoreColumn: 'score', minScore: 5 })).toEqual(new Set([0, 1]));
  });
  it('keeps only the chosen category values, never a blank one', () => {
    expect(
      rowsKept(rows, { scoreColumn: 'score', filterColumn: 'impact', filterValues: ['HIGH'] }),
    ).toEqual(new Set([0, 2]));
  });
  it('combines a floor and a category', () => {
    expect(
      rowsKept(rows, { scoreColumn: 'score', minScore: 5, filterColumn: 'impact', filterValues: ['HIGH'] }),
    ).toEqual(new Set([0]));
  });
});

describe('rankRows with include', () => {
  const rows = { score: [10, 7, 7, 3], other: [1, 4, 2, 9] };
  it('ranks only the rows kept and counts the rest out', () => {
    const list = rankRows(rows, { score: 'score' }, { descending: true, topN: 10, include: new Set([1, 2, 3]) });
    expect(list.rows.map((r) => [r.source, r.rank])).toEqual([
      [1, 1],
      [2, 1],
      [3, 2],
    ]);
    expect(list.ranked).toBe(3);
    expect(list.unscored).toBe(0);
  });
  it('counts a kept row with no score as unscored', () => {
    const list = rankRows(
      { score: [10, null, 3] },
      { score: 'score' },
      { descending: true, topN: 10, include: new Set([0, 1]) },
    );
    expect(list.ranked).toBe(1);
    expect(list.unscored).toBe(1);
  });
  it('orders by another column when asked', () => {
    const list = rankRows(rows, { score: 'other' }, { descending: false, topN: 2 });
    expect(list.rows.map((r) => r.source)).toEqual([0, 2]);
  });
});

describe('column pickers', () => {
  const specs = [
    { column: 'model', display: 'badge' as const },
    { column: 'score', display: 'bar' as const },
    { column: 'af', display: 'number' as const },
    { column: 'hgvs', display: 'mono' as const },
    { column: 'note' },
  ];
  it('sorts by the score first, then bar and number columns once', () => {
    expect(sortableColumns('score', specs)).toEqual(['score', 'af']);
    expect(sortableColumns('rank', specs)).toEqual(['rank', 'score', 'af']);
    expect(sortableColumns('score', specs, ['cadd', 'af'])).toEqual(['score', 'af', 'cadd']);
  });
  it('reads a column as numeric only when every filled cell is a number', () => {
    expect(isNumericColumn([1, '2.5', null, ''])).toBe(true);
    expect(isNumericColumn([1, 'absent'])).toBe(false);
    expect(isNumericColumn([null, ''])).toBe(false);
    expect(isNumericColumn(undefined)).toBe(false);
  });
  it('filters on text, monospace and badge columns', () => {
    expect(categoricalColumns(specs)).toEqual(['model', 'hgvs', 'note']);
  });
  it('lists distinct values, sorted naturally, skipping blanks', () => {
    expect(distinctValues(['b', 'a', '', null, 'a', 10, 9])).toEqual(['9', '10', 'a', 'b']);
    expect(distinctValues(undefined)).toEqual([]);
  });
});

describe('rankedEcho filtered', () => {
  it('says so when the Data controls took rows out', () => {
    expect(rankedEcho({ shown: 3, ranked: 3, scoreLabel: 's', descending: true, filtered: true })).toBe(
      'top 3 by s (highest first, filtered)',
    );
  });
});
