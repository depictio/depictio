import { describe, expect, it } from 'vitest';

import { rainfallDistances } from './rainfallDistances';

describe('rainfallDistances', () => {
  it('differences within a chromosome and drops its first variant', () => {
    const out = rainfallDistances(['chr1', 'chr1', 'chr1'], [100, 200, 1200]);
    expect(out.map((d) => d.row)).toEqual([1, 2]);
    expect(out.map((d) => d.distance)).toEqual([100, 1000]);
    expect(out[1].logDistance).toBeCloseTo(3);
  });

  it('never differences across a chromosome boundary', () => {
    const out = rainfallDistances(['chr1', 'chr2', 'chr2'], [1_000_000, 10, 20]);
    // chr2's first variant has no predecessor, so the one surviving distance
    // is the 10 bp step inside chr2 rather than the huge chr1 -> chr2 jump.
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ row: 2, distance: 10 });
  });

  it('sorts by position before differencing, whatever order the rows arrive in', () => {
    const shuffled = rainfallDistances(['c', 'c', 'c'], [1200, 100, 200]);
    expect(shuffled.map((d) => d.distance).sort((a, b) => a - b)).toEqual([100, 1000]);
    // The row that is dropped is the leftmost one, not the first row stored.
    expect(shuffled.map((d) => d.row)).not.toContain(1);
  });

  it('drops zero distances rather than inventing a base pair', () => {
    const out = rainfallDistances(['c', 'c', 'c'], [500, 500, 900]);
    expect(out.every((d) => Number.isFinite(d.logDistance))).toBe(true);
    expect(out.map((d) => d.distance)).toEqual([400]);
  });

  it('ignores rows with an unparseable position', () => {
    const out = rainfallDistances(['c', 'c', 'c'], [100, 'n/a', 300]);
    expect(out.map((d) => d.distance)).toEqual([200]);
  });

  it('returns nothing for a single variant', () => {
    expect(rainfallDistances(['c'], [42])).toEqual([]);
  });
});
