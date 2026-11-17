import { describe, expect, it } from 'vitest';

import { binEdges, densityColours, densityGrid, densityHeatmap, sparseSources } from './densityBins';

describe('binEdges', () => {
  it('covers the range in exactly the requested number of bins', () => {
    const edges = binEdges([0, 10], 10);
    expect(edges).not.toBeNull();
    const { start, end, size } = edges as { start: number; end: number; size: number };
    expect(start).toBe(0);
    expect(size).toBeCloseTo(1);
    // One bin width past the maximum, so the largest value lands inside the
    // grid rather than on its half-open upper edge.
    expect(end).toBeCloseTo(11);
  });

  it('gives a constant column a bin with a width', () => {
    const edges = binEdges([3, 3, 3], 20);
    expect(edges).not.toBeNull();
    const { start, end, size } = edges as { start: number; end: number; size: number };
    expect(size).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
  });

  it('ignores non-finite values and returns null when nothing is left', () => {
    expect(binEdges([Number.NaN, Number.POSITIVE_INFINITY], 10)).toBeNull();
    expect(binEdges([], 10)).toBeNull();
    expect(binEdges([Number.NaN, 5, 15], 5)?.start).toBe(5);
  });

  it('never divides by a zero bin count', () => {
    expect(binEdges([0, 4], 0)?.size).toBeCloseTo(4);
  });
});

describe('densityGrid', () => {
  it('keeps pairs together and bins in data units on a linear axis', () => {
    const grid = densityGrid([1, 2, 3], [10, 20, 30], { logX: false, logY: false, bins: 2 });
    expect(grid.x).toEqual([1, 2, 3]);
    expect(grid.y).toEqual([10, 20, 30]);
    expect(grid.xbins?.start).toBe(1);
    expect(grid.xbins?.size).toBeCloseTo(1);
  });

  it('bins in log10 units on a log axis while the trace keeps data units', () => {
    const grid = densityGrid([1, 100], [1, 1], { logX: true, logY: false, bins: 2 });
    // The trace still carries 1 and 100; only the bin block is in log space.
    expect(grid.x).toEqual([1, 100]);
    expect(grid.xbins?.start).toBeCloseTo(0);
    expect(grid.xbins?.size).toBeCloseTo(1);
  });

  it('drops a pair either axis cannot draw', () => {
    const grid = densityGrid([1, 0, 4], [1, 2, Number.NaN], { logX: true, logY: false, bins: 4 });
    expect(grid.x).toEqual([1]);
    expect(grid.y).toEqual([1]);
  });

  it('returns no bin block when every pair is undrawable', () => {
    const grid = densityGrid([-1, 0], [1, 2], { logX: true, logY: false, bins: 4 });
    expect(grid.x).toEqual([]);
    expect(grid.xbins).toBeNull();
    expect(grid.ybins).toBeNull();
  });
});

describe('densityHeatmap', () => {
  it('counts every drawable pair into a bins x bins grid with data-unit edges', () => {
    const grid = densityHeatmap([1, 2, 3, 3], [10, 20, 30, 30], { logX: false, logY: false, bins: 2 });
    expect(grid).not.toBeNull();
    const { xEdges, yEdges, z, count } = grid as NonNullable<typeof grid>;
    expect(count).toBe(4);
    expect(z.length).toBe(2);
    expect(z[0].length).toBe(2);
    expect(xEdges.length).toBe(3);
    expect(yEdges.length).toBe(3);
    expect(z.flat().reduce((a, b) => a + b, 0)).toBe(4);
    // (2, 20) and the doubled (3, 30) all land in the top-right cell: the
    // maximum is clamped into the last cell rather than given a spare bin.
    expect(z[1][1]).toBe(3);
    expect(z[0][0]).toBe(1);
  });

  it('spaces the edges evenly in log10 on a log axis and reports them in data units', () => {
    const grid = densityHeatmap([1, 10, 100, 1000], [1, 1, 1, 1], { logX: true, logY: false, bins: 3 });
    expect(grid).not.toBeNull();
    const { xEdges, z } = grid as NonNullable<typeof grid>;
    expect(xEdges[0]).toBeCloseTo(1);
    expect(xEdges[1]).toBeCloseTo(10);
    expect(xEdges[2]).toBeCloseTo(100);
    expect(xEdges[3]).toBeCloseTo(1000);
    // A constant y spreads its half-unit span over the rows; the middle row holds every pair.
    expect(z[1]).toEqual([1, 1, 2]);
  });

  it('is null when no pair is drawable', () => {
    expect(densityHeatmap([-1, 0], [1, 2], { logX: true, logY: false, bins: 4 })).toBeNull();
  });
});

describe('densityHeatmap bookkeeping', () => {
  it('maps every counted pair back to its row, skipping the undrawable ones', () => {
    const heat = densityHeatmap([1, Number.NaN, 5, 9], [1, 2, 5, 9], { logX: false, logY: false, bins: 2 });
    expect(heat?.source).toEqual([0, 2, 3]);
    // Cell = row * bins + column: (1,1) in the corner, (9,9) in the opposite one.
    expect(heat?.cell).toEqual([0, 3, 3]);
  });
});

describe('densityColours', () => {
  const z = [
    [0, 1],
    [100, 7],
  ];

  it('leaves empty cells null so they stay transparent', () => {
    const c = densityColours(z, 'log');
    expect(c.z[0][0]).toBeNull();
    expect(c.counts[0][0]).toBeNull();
    expect(densityColours(z, 'linear').z[0][0]).toBeNull();
  });

  it('spends the colour range on orders of magnitude on a log scale', () => {
    const c = densityColours(z, 'log');
    expect(c.z[0][1]).toBe(0);
    expect(c.z[1][0]).toBe(2);
    expect(c.z[1][1]).toBeCloseTo(Math.log10(7));
    expect(c.counts[1][0]).toBe(100);
  });

  it('ticks the bar in counts, ending on the largest', () => {
    expect(densityColours(z, 'log')).toMatchObject({ tickvals: [0, 1, 2], ticktext: ['1', '10', '100'] });
    const small = densityColours([[3, 8]], 'log');
    expect(small.ticktext).toEqual(['1', '8']);
    expect(small.tickvals?.[1]).toBeCloseTo(Math.log10(8));
  });

  it('keeps a linear scale in plain counts, with default ticks', () => {
    const c = densityColours(z, 'linear');
    expect(c.z[1][0]).toBe(100);
    expect(c.tickvals).toBeUndefined();
  });

  it('copes with an empty grid', () => {
    expect(densityColours([[0, 0]], 'log').tickvals).toEqual([]);
  });
});

describe('sparseSources', () => {
  // 2 x 2 cells: three points in the left-bottom cell, one each elsewhere.
  const heat = {
    z: [
      [3, 1],
      [0, 1],
    ],
    cell: [0, 0, 0, 1, 3],
    source: [10, 11, 12, 13, 14],
  };

  it('returns the rows of cells at or under the count', () => {
    expect(sparseSources(heat, { maxCount: 1, cap: 100 })).toEqual([13, 14]);
    expect(sparseSources(heat, { maxCount: 3, cap: 100 })).toEqual([10, 11, 12, 13, 14]);
    expect(sparseSources(heat, { maxCount: 0, cap: 100 })).toEqual([]);
  });

  it('keeps the sparsest first when over the cap', () => {
    expect(sparseSources(heat, { maxCount: 3, cap: 2 })).toEqual([13, 14]);
    expect(sparseSources(heat, { maxCount: 3, cap: 0 })).toEqual([]);
  });
});
