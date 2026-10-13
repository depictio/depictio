import { describe, expect, it } from 'vitest';

import { binEdges, densityGrid, densityHeatmap } from './densityBins';

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
