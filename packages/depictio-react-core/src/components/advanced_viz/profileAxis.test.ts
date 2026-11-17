import { describe, expect, it } from 'vitest';

import {
  integerTickValues,
  markerSizeFor,
  MARKER_MAX_POINTS,
  MAX_INTEGER_TICKS,
  showsMarkers,
} from './profileAxis';

describe('markerSizeFor', () => {
  it('is twice the line width plus three, never under 6', () => {
    expect(markerSizeFor(2)).toBe(7);
    expect(markerSizeFor(4)).toBe(11);
    expect(markerSizeFor(1)).toBe(6);
    expect(markerSizeFor(0.5)).toBe(6);
  });

  it('falls back to the default width for a bad value', () => {
    expect(markerSizeFor(Number.NaN)).toBe(7);
    expect(markerSizeFor(0)).toBe(7);
  });
});

describe('showsMarkers', () => {
  it('marks every point of a short series, a single point included', () => {
    expect(showsMarkers(1)).toBe(true);
    expect(showsMarkers(MARKER_MAX_POINTS)).toBe(true);
  });

  it('leaves a dense curve as a plain line', () => {
    expect(showsMarkers(MARKER_MAX_POINTS + 1)).toBe(false);
  });
});

describe('integerTickValues', () => {
  it('labels each distinct step of an integer axis, ascending, once', () => {
    expect(integerTickValues([2, 0, 1, 1, 0, 2])).toEqual([0, 1, 2]);
  });

  it('works for a single step (a one-point series)', () => {
    expect(integerTickValues([0])).toEqual([0]);
  });

  it('is null when any x is fractional', () => {
    expect(integerTickValues([0, 1, 1.5])).toBeNull();
  });

  it('is null for a long integer axis, where Plotly ticks are fine', () => {
    const xs = Array.from({ length: MAX_INTEGER_TICKS + 1 }, (_, i) => i);
    expect(integerTickValues(xs)).toBeNull();
    expect(integerTickValues(xs.slice(0, MAX_INTEGER_TICKS))).toHaveLength(MAX_INTEGER_TICKS);
  });

  it('is null for no data', () => {
    expect(integerTickValues([])).toBeNull();
  });
});
