import { describe, expect, it } from 'vitest';

import { medianIqrByX, quantileSorted } from './profileAggregate';

describe('quantileSorted', () => {
  it('interpolates linearly between ranks, like numpy', () => {
    expect(quantileSorted([1, 2, 3, 4], 0.5)).toBe(2.5);
    expect(quantileSorted([1, 2, 3, 4], 0.25)).toBe(1.75);
    expect(quantileSorted([7], 0.75)).toBe(7);
  });
});

describe('medianIqrByX', () => {
  it('collapses the rows of each x into a median with its quartile band', () => {
    const out = medianIqrByX([
      { x: 2, y: 10 },
      { x: 0, y: 1 },
      { x: 0, y: 3 },
      { x: 0, y: 2 },
      { x: 2, y: 30 },
    ]);
    expect(out).toEqual([
      { x: 0, y: 2, lo: 1.5, hi: 2.5 },
      { x: 2, y: 20, lo: 15, hi: 25 },
    ]);
  });

  it('returns nothing for no rows', () => {
    expect(medianIqrByX([])).toEqual([]);
  });
});
