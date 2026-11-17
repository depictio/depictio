import { describe, expect, it } from 'vitest';

import {
  boxStats,
  buildRankedFigure,
  clampTopN,
  columnsToFetch,
  featureIdFromPoint,
  formatNumber,
  groupsOf,
  log1p10,
  parseRankedRows,
  quantile,
  rankFeatures,
  rankingEcho,
  selectedFeatureIds,
  selectionValueOf,
  shapeOf,
  topFeatures,
  withAlpha,
  type RankedColumns,
  type RankedFeature,
} from './rankedLayout';

const STATS_COLS: RankedColumns = {
  featureId: 'gene_id',
  score: 'stability_score',
  label: 'gene_name',
  group: 'section',
  q1: 'q1',
  median: 'median',
  q3: 'q3',
  lower: 'lower',
  upper: 'upper',
};

const LONG_COLS: RankedColumns = {
  featureId: 'gene_id',
  score: 'stability_score',
  value: 'value',
};

const statsRows = () => ({
  gene_id: ['G3', 'G1', 'G2', 'G4'],
  gene_name: ['ACTB', 'GAPDH', 'RPL13A', null],
  section: ['high', 'high', 'mid', null],
  stability_score: [0.3, 0.1, 0.2, null],
  q1: [1, 2, 3, 4],
  median: [2, 3, 4, 5],
  q3: [3, 4, 5, 6],
  lower: [0.5, null, 2.5, 3],
  upper: [4, null, 6, 7],
});

const colours = { high: 'rgb(1, 2, 3)', mid: '#336699' } as Record<string, string>;
const figureOpts = {
  orientation: 'horizontal' as const,
  mark: 'box' as const,
  shape: 'stats' as const,
  colourOf: (g: string | null) => (g ? colours[g] : '#888888'),
  stemColour: '#999999',
  selectedOutline: '#000000',
  scoreTitle: 'Stability score',
  valueTitle: 'Normalised count',
  groupTitle: 'section',
};

describe('shape and columns', () => {
  it('tells the two shapes apart, and an incomplete binding from both', () => {
    expect(shapeOf(LONG_COLS)).toBe('long');
    expect(shapeOf(STATS_COLS)).toBe('stats');
    expect(shapeOf({ featureId: 'a', score: 'b', q1: 'q1', median: 'm' })).toBeNull();
    expect(shapeOf({ featureId: 'a', score: 'b' })).toBeNull();
  });

  it('fetches only the columns of the bound shape, each once', () => {
    expect(columnsToFetch({ ...LONG_COLS, label: 'gene_id', selection: 'gene_id' })).toEqual([
      'gene_id',
      'stability_score',
      'value',
    ]);
    expect(columnsToFetch(STATS_COLS)).toEqual([
      'gene_id',
      'stability_score',
      'gene_name',
      'section',
      'q1',
      'median',
      'q3',
      'lower',
      'upper',
    ]);
  });
});

describe('statistics', () => {
  it('interpolates quantiles the numpy way', () => {
    expect(quantile([1, 2, 3, 4], 0.25)).toBeCloseTo(1.75);
    expect(quantile([1, 2, 3, 4], 0.5)).toBeCloseTo(2.5);
    expect(quantile([5], 0.9)).toBe(5);
    expect(Number.isNaN(quantile([], 0.5))).toBe(true);
  });

  it('draws Tukey whiskers to the last value inside the fences', () => {
    const s = boxStats([1, 2, 3, 4, 5, 6, 7, 8, 100])!;
    expect(s.median).toBe(5);
    expect(s.q1).toBe(3);
    expect(s.q3).toBe(7);
    expect(s.lower).toBe(1);
    // 100 is beyond q3 + 1.5 IQR = 13: the whisker stops at 8.
    expect(s.upper).toBe(8);
    expect(s.n).toBe(9);
    expect(s.mean).toBeCloseTo(136 / 9);
    expect(boxStats([])).toBeNull();
    expect(boxStats([Number.NaN])).toBeNull();
  });

  it('takes log10(x + 1), and refuses what has no log', () => {
    expect(log1p10(9)).toBeCloseTo(1);
    expect(log1p10(0)).toBe(0);
    expect(log1p10(-1)).toBeNull();
  });
});

describe('parseRankedRows', () => {
  it('reads one feature per pre-aggregated row and fills missing fences', () => {
    const parsed = parseRankedRows(statsRows(), STATS_COLS);
    expect(parsed.shape).toBe('stats');
    // G4 has no score: it cannot be ranked, so it is dropped and counted.
    expect(parsed.features.map((f) => f.id)).toEqual(['G3', 'G1', 'G2']);
    expect(parsed.dropped).toBe(1);
    const g1 = parsed.features.find((f) => f.id === 'G1')!;
    expect(g1.label).toBe('GAPDH');
    expect(g1.group).toBe('high');
    // No published whiskers: Tukey's fences around the box.
    expect(g1.stats).toMatchObject({ q1: 2, median: 3, q3: 4, lower: -1, upper: 7, mean: null });
  });

  it('folds long-form rows into each feature and computes its box', () => {
    const parsed = parseRankedRows(
      {
        gene_id: ['A', 'A', 'A', 'B', 'B', 'A', 'C'],
        stability_score: [0.5, 0.5, 0.5, 0.2, 0.2, 0.5, 0.9],
        value: [1, 2, 3, 10, 20, 4, null],
      },
      LONG_COLS,
    );
    expect(parsed.shape).toBe('long');
    expect(parsed.features.map((f) => [f.id, f.values.length])).toEqual([
      ['A', 4],
      ['B', 2],
    ]);
    // C has a score but not one value: nothing to draw.
    expect(parsed.dropped).toBe(1);
    expect(parsed.features[0].stats!.median).toBe(2.5);
    expect(parsed.features[0].label).toBe('A');
  });

  it('logs the values before the box, and drops a pre-aggregated mean on the log axis', () => {
    const long = parseRankedRows(
      { gene_id: ['A', 'A'], stability_score: [1, 1], value: [9, 99] },
      LONG_COLS,
      { logValue: true },
    );
    expect(long.features[0].values.map((v) => Number(v.toFixed(6)))).toEqual([1, 2]);
    const stats = parseRankedRows(
      {
        gene_id: ['A'],
        stability_score: [1],
        q1: [9],
        median: [99],
        q3: [999],
        mean: [500],
      },
      { featureId: 'gene_id', score: 'stability_score', q1: 'q1', median: 'median', q3: 'q3', mean: 'mean' },
      { logValue: true },
    );
    expect(stats.features[0].stats!.median).toBeCloseTo(2);
    expect(stats.features[0].stats!.mean).toBeNull();
    // The unpublished fences are Tukey's on the log axis (1 - 1.5 * 2 = -2),
    // where a linear fence (9 - 1.5 * 990) would have no log at all.
    expect(stats.features[0].stats!.lower).toBeCloseTo(-2);
    expect(stats.features[0].stats!.upper).toBeCloseTo(6);
  });

  it('keeps the selection value of each feature', () => {
    const parsed = parseRankedRows(
      { gene_id: ['A', 'B'], stability_score: [1, 2], q1: [1, 1], median: [2, 2], q3: [3, 3], ens: ['E1', 'E2'] },
      { featureId: 'gene_id', score: 'stability_score', q1: 'q1', median: 'median', q3: 'q3', selection: 'ens' },
    );
    expect(parsed.features.map((f) => f.selectionValue)).toEqual(['E1', 'E2']);
    expect(selectionValueOf(parsed.features, 'B')).toBe('E2');
    expect(selectionValueOf(parsed.features, 'Z')).toBeNull();
    expect([...selectedFeatureIds(parsed.features, new Set(['E2']))]).toEqual(['B']);
  });
});

describe('ranking', () => {
  const features = (): RankedFeature[] => parseRankedRows(statsRows(), STATS_COLS).features;

  it('ranks by score, lowest first by default direction, ties by id', () => {
    expect(rankFeatures(features(), { ascending: true }).map((f) => [f.id, f.rank])).toEqual([
      ['G1', 1],
      ['G2', 2],
      ['G3', 3],
    ]);
    expect(rankFeatures(features(), { ascending: false }).map((f) => f.id)).toEqual([
      'G3',
      'G2',
      'G1',
    ]);
    const tied = features().map((f) => ({ ...f, score: 1 }));
    expect(rankFeatures(tied, { ascending: true }).map((f) => f.id)).toEqual(['G1', 'G2', 'G3']);
  });

  it('keeps a bound rank column when every feature has one', () => {
    const ranked = parseRankedRows(
      { ...statsRows(), rank: [1, 3, 2, 4] },
      { ...STATS_COLS, rank: 'rank' },
    ).features;
    expect(rankFeatures(ranked, { ascending: true, useRankColumn: true }).map((f) => [f.id, f.rank])).toEqual([
      ['G3', 1],
      ['G2', 2],
      ['G1', 3],
    ]);
    // A hole in the rank column: the score decides instead.
    ranked[0].rank = Number.NaN;
    expect(rankFeatures(ranked, { ascending: true, useRankColumn: true })[0].id).toBe('G1');
  });

  it('does not mutate what it ranks', () => {
    const input = features();
    rankFeatures(input, { ascending: true });
    expect(input.map((f) => f.id)).toEqual(['G3', 'G1', 'G2']);
    expect(input.every((f) => Number.isNaN(f.rank))).toBe(true);
  });

  it('cuts the top N, capped by the guard', () => {
    const ranked = rankFeatures(features(), { ascending: true });
    expect(topFeatures(ranked, 2, 200).map((f) => f.id)).toEqual(['G1', 'G2']);
    expect(topFeatures(ranked, 50, 200)).toHaveLength(3);
    expect(clampTopN(500, 200)).toBe(200);
    expect(clampTopN(0, 200)).toBe(1);
    expect(clampTopN(Number.NaN, 200)).toBe(25);
    expect(clampTopN(7.9, 200)).toBe(7);
  });

  it('lists groups sorted with the ungrouped last', () => {
    expect(groupsOf(parseRankedRows(statsRows(), STATS_COLS).features)).toEqual(['high', 'mid']);
    const withNull = parseRankedRows(
      { gene_id: ['A', 'B'], stability_score: [1, 2], q1: [1, 1], median: [2, 2], q3: [3, 3], section: ['b', null] },
      { ...STATS_COLS, lower: null, upper: null, label: null },
    ).features;
    expect(groupsOf(withNull)).toEqual(['b', null]);
  });
});

describe('buildRankedFigure', () => {
  const top = () =>
    rankFeatures(parseRankedRows(statsRows(), STATS_COLS).features, { ascending: true });

  it('puts both panels on one category axis in rank order', () => {
    const fig = buildRankedFigure(top(), figureOpts);
    const yaxis = fig.layout.yaxis as Record<string, unknown>;
    expect(yaxis.categoryarray).toEqual(['G1', 'G2', 'G3']);
    expect(yaxis.ticktext).toEqual(['GAPDH', 'RPL13A', 'ACTB']);
    expect(yaxis.autorange).toBe('reversed');
    // Every trace reads the same y (the category axis); the boxes and the
    // lollipop differ only by their value axis.
    expect(new Set(fig.data.map((t) => t.yaxis))).toEqual(new Set(['y']));
    expect(new Set(fig.data.map((t) => t.xaxis))).toEqual(new Set(['x', 'x2']));
    const boxes = fig.data.filter((t) => t.type === 'box');
    expect(boxes.map((b) => b.name)).toEqual(['high', 'mid']);
    expect(boxes[0].y).toEqual(['G1', 'G3']);
    expect(boxes[0].q1).toEqual([2, 1]);
    expect(boxes[0].lowerfence).toEqual([-1, 0.5]);
    expect(boxes[0].fillcolor).toBe('rgba(1,2,3,0.45)');
    expect(boxes.every((b) => b.orientation === 'h')).toBe(true);
    // One legend entry per group, on the distribution trace.
    expect(fig.data.filter((t) => t.showlegend).map((t) => t.name)).toEqual(['high', 'mid']);
    expect(fig.layout.showlegend).toBe(true);
  });

  it('draws a stem from zero to each score, and heads that carry the feature id', () => {
    const fig = buildRankedFigure(top(), figureOpts);
    const stems = fig.data.find((t) => t.mode === 'lines')!;
    expect(stems.y).toEqual(['G1', 'G1', null, 'G2', 'G2', null, 'G3', 'G3', null]);
    expect(stems.x).toEqual([0, 0.1, null, 0, 0.2, null, 0, 0.3, null]);
    const heads = fig.data.filter((t) => t.mode === 'markers');
    expect(heads.flatMap((h) => (h.customdata as unknown[][]).map((c) => c[0]))).toEqual([
      'G1',
      'G3',
      'G2',
    ]);
    expect((fig.layout.xaxis2 as Record<string, unknown>).rangemode).toBe('tozero');
  });

  it('stacks the panels vertically on a shared x axis under the score', () => {
    const fig = buildRankedFigure(top(), { ...figureOpts, orientation: 'vertical' });
    const xaxis = fig.layout.xaxis as Record<string, unknown>;
    expect(xaxis.categoryarray).toEqual(['G1', 'G2', 'G3']);
    expect(xaxis.anchor).toBe('y2');
    expect(new Set(fig.data.map((t) => t.xaxis))).toEqual(new Set(['x']));
    expect(fig.data.find((t) => t.mode === 'lines')!.yaxis).toBe('y2');
    expect(fig.data.filter((t) => t.type === 'box').every((b) => b.orientation === 'v')).toBe(true);
  });

  it('dims what a selection leaves out and outlines what it holds', () => {
    const fig = buildRankedFigure(top(), { ...figureOpts, selected: new Set(['G3']) });
    const boxes = fig.data.filter((t) => t.type === 'box');
    expect(boxes.map((b) => [b.name, b.y, b.opacity])).toEqual([
      ['high', ['G3'], 1],
      ['high', ['G1'], 0.3],
      ['mid', ['G2'], 0.3],
    ]);
    expect((boxes[0].line as Record<string, unknown>).color).toBe('#000000');
    // The legend still lists each group once.
    expect(fig.data.filter((t) => t.showlegend).map((t) => t.name)).toEqual(['high', 'mid']);
    const high = fig.data.find((t) => t.mode === 'markers' && t.name === 'high')!;
    expect((high.marker as Record<string, unknown>).opacity).toEqual([0.3, 1]);
  });

  it('draws violins from the raw values in long form only', () => {
    const long = rankFeatures(
      parseRankedRows(
        { gene_id: ['A', 'A', 'B', 'B'], stability_score: [1, 1, 2, 2], value: [1, 2, 3, 4] },
        LONG_COLS,
      ).features,
      { ascending: true },
    );
    const fig = buildRankedFigure(long, { ...figureOpts, shape: 'long', mark: 'violin', groupTitle: null });
    const violin = fig.data.find((t) => t.type === 'violin')!;
    expect(violin.y).toEqual(['A', 'A', 'B', 'B']);
    expect(violin.x).toEqual([1, 2, 3, 4]);
    expect(fig.layout.showlegend).toBe(false);
    // A violin cannot be drawn from statistics: the box is the fallback.
    const stats = buildRankedFigure(top(), { ...figureOpts, mark: 'violin' });
    expect(stats.data.some((t) => t.type === 'violin')).toBe(false);
    expect(stats.data.some((t) => t.type === 'box')).toBe(true);
  });

  it('adds the mean line only when every box has one', () => {
    const fig = buildRankedFigure(top(), figureOpts);
    expect(fig.data.some((t) => t.type === 'box' && 'mean' in t)).toBe(false);
    const long = rankFeatures(
      parseRankedRows({ gene_id: ['A', 'A'], stability_score: [1, 1], value: [1, 3] }, LONG_COLS).features,
      { ascending: true },
    );
    const box = buildRankedFigure(long, { ...figureOpts, shape: 'long' }).data.find((t) => t.type === 'box')!;
    expect(box.mean).toEqual([2]);
    expect(box.boxmean).toBe(true);
  });
});

describe('helpers', () => {
  it('reads the clicked feature off a head or off a box', () => {
    expect(featureIdFromPoint({ customdata: ['G1', 1], y: 'G9' }, 'horizontal')).toBe('G1');
    expect(featureIdFromPoint({ y: 'G2' }, 'horizontal')).toBe('G2');
    expect(featureIdFromPoint({ x: 'G3' }, 'vertical')).toBe('G3');
    expect(featureIdFromPoint({ x: 0.4 }, 'horizontal')).toBeNull();
    expect(featureIdFromPoint(null, 'horizontal')).toBeNull();
  });

  it('turns a theme colour into a fill', () => {
    expect(withAlpha('#abc', 0.5)).toBe('rgba(170,187,204,0.5)');
    expect(withAlpha('rgba(1, 2, 3, 1)', 0.2)).toBe('rgba(1,2,3,0.2)');
    expect(withAlpha('var(--x)', 0.2)).toBe('var(--x)');
  });

  it('formats numbers for the hover', () => {
    expect(formatNumber(0.123456)).toBe('0.123');
    expect(formatNumber(1234.5)).toBe('1230');
    expect(formatNumber(0.00001234)).toBe('1.23e-5');
  });

  it('says what the tile shows', () => {
    expect(rankingEcho({ shown: 25, total: 200, ascending: true, byRankColumn: false, noun: 'genes' })).toBe(
      'Top 25 of 200 genes, lowest score first',
    );
    expect(rankingEcho({ shown: 3, total: 3, ascending: false, byRankColumn: false })).toBe(
      'All 3 features, highest score first',
    );
    expect(rankingEcho({ shown: 2, total: 9, ascending: true, byRankColumn: true })).toContain('rank order');
  });
});
