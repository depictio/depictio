import { describe, expect, it } from 'vitest';

import { groupIndices, largestGroup, sortCurveIndices, trapezoidArea } from './prCurves';

describe('groupIndices', () => {
  it('puts every row in one bucket when no group column is bound', () => {
    const groups = groupIndices(null, 3);
    expect(Array.from(groups.keys())).toEqual(['']);
    expect(groups.get('')).toEqual([0, 1, 2]);
  });

  it('buckets by value, in first-seen order', () => {
    const groups = groupIndices(['b', 'a', 'b'], 3);
    expect(Array.from(groups.keys())).toEqual(['b', 'a']);
    expect(groups.get('b')).toEqual([0, 2]);
    expect(groups.get('a')).toEqual([1]);
  });

  it('reads null and undefined as one empty-named group', () => {
    const groups = groupIndices([null, undefined], 2);
    expect(groups.get('')).toEqual([0, 1]);
  });
});

describe('largestGroup', () => {
  it('is zero for no rows and the longest bucket otherwise', () => {
    expect(largestGroup(groupIndices(null, 0))).toBe(0);
    expect(largestGroup(groupIndices(['a', 'b', 'b'], 3))).toBe(2);
  });
});

describe('trapezoidArea', () => {
  it('measures the unit square under a flat curve', () => {
    expect(trapezoidArea([0, 1], [1, 1])).toBeCloseTo(1);
  });

  it('is independent of the order the points arrive in', () => {
    const sorted = trapezoidArea([0, 0.5, 1], [1, 0.8, 0.2]);
    const shuffled = trapezoidArea([1, 0, 0.5], [0.2, 1, 0.8]);
    expect(shuffled).toBeCloseTo(sorted);
    expect(sorted).toBeCloseTo(0.7);
  });

  it('skips pairs with a non-finite coordinate rather than returning NaN', () => {
    expect(trapezoidArea([0, Number.NaN, 1], [1, 0.5, 1])).toBeCloseTo(1);
  });

  it('is zero for fewer than two usable points', () => {
    expect(trapezoidArea([], [])).toBe(0);
    expect(trapezoidArea([0.5], [0.5])).toBe(0);
  });
});

describe('sortCurveIndices', () => {
  it('follows the swept threshold when one is bound', () => {
    expect(sortCurveIndices([0, 1, 2], [0.9, 0.1, 0.5], [30, 10, 20])).toEqual([1, 2, 0]);
  });

  it('falls back to the x coordinate the curve is drawn against', () => {
    expect(sortCurveIndices([0, 1, 2], [0.9, 0.1, 0.5], null)).toEqual([1, 2, 0]);
  });

  it('leaves the array it was given alone', () => {
    const idx = [2, 0, 1];
    sortCurveIndices(idx, [0, 1, 2], null);
    expect(idx).toEqual([2, 0, 1]);
  });
});
