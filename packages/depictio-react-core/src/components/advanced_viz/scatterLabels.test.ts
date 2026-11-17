import { describe, expect, it } from 'vitest';

import { extentFraction, labelPlacement } from './scatterLabels';

describe('extentFraction', () => {
  it('places a value in its range, clamped', () => {
    expect(extentFraction(5, 0, 10)).toBe(0.5);
    expect(extentFraction(-3, 0, 10)).toBe(0);
    expect(extentFraction(30, 0, 10)).toBe(1);
  });

  it('is the middle for an empty range (a single point)', () => {
    expect(extentFraction(4, 4, 4)).toBe(0.5);
    expect(extentFraction(Number.NaN, 0, 10)).toBe(0.5);
  });
});

describe('labelPlacement', () => {
  it('centres the label above a point in the middle of the data', () => {
    expect(labelPlacement(0.5, 0.5)).toEqual({ xanchor: 'center', xshift: 0, yshift: 10 });
  });

  it('starts the label at a left-most point and ends it at a right-most one', () => {
    expect(labelPlacement(0, 0.5)).toMatchObject({ xanchor: 'left', xshift: 4 });
    expect(labelPlacement(1, 0.5)).toMatchObject({ xanchor: 'right', xshift: -4 });
  });

  it('puts the label under the highest point, so it stays inside the plot', () => {
    expect(labelPlacement(0.5, 1).yshift).toBe(-10);
    expect(labelPlacement(0.5, 0.9).yshift).toBe(-10);
    expect(labelPlacement(0.5, 0.2).yshift).toBe(10);
  });
});
