import { describe, expect, it } from 'vitest';

import { buildAxisScale, formatAxisTick, toNumbers } from './axisScaling';

describe('toNumbers', () => {
  it('reads numbers and turns everything else into a gap', () => {
    expect(toNumbers([1, '2', null, undefined, '', 'n/a', Number.NaN])).toEqual([
      1,
      2,
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});

describe('formatAxisTick', () => {
  it('stays short at both ends of the range', () => {
    expect(formatAxisTick(40_000_000)).toBe('4.0e+7');
    expect(formatAxisTick(0.00002)).toBe('2.0e-5');
    expect(formatAxisTick(1234)).toBe('1,234');
    expect(formatAxisTick(0.1234)).toBe('0.123');
  });
});

describe('buildAxisScale', () => {
  const values = [0, 5, 10];

  it('leaves raw values and their bounds alone', () => {
    const scale = buildAxisScale(values, 'raw');
    expect(scale.values).toEqual([0, 5, 10]);
    expect(scale.range).toEqual([0, 10]);
    expect(scale.tickvals).toBeUndefined();
    expect(scale.toOriginal(7)).toBe(7);
  });

  it('rescales minmax onto [0, 1] and inverts back to the column units', () => {
    const scale = buildAxisScale(values, 'minmax');
    expect(scale.values).toEqual([0, 0.5, 1]);
    expect(scale.range).toEqual([0, 1]);
    expect(scale.toOriginal(0.25)).toBe(2.5);
  });

  it('rescales zscore around the mean and inverts back', () => {
    const scale = buildAxisScale(values, 'zscore');
    const sd = Math.sqrt(((0 - 5) ** 2 + 0 + (10 - 5) ** 2) / 3);
    expect(scale.values).toEqual([-5 / sd, 0, 5 / sd]);
    expect(scale.toOriginal(1)).toBeCloseTo(5 + sd, 10);
  });

  it('round-trips a value through the projection and back', () => {
    for (const mode of ['raw', 'minmax', 'zscore'] as const) {
      const scale = buildAxisScale(values, mode);
      expect(scale.toOriginal(scale.toPlotted(7))).toBeCloseTo(7, 10);
    }
  });

  it('labels the ticks with the original values, not the rescaled ones', () => {
    const scale = buildAxisScale([100, 200, 300], 'minmax', 3);
    expect(scale.tickvals).toEqual([0, 0.5, 1]);
    expect(scale.ticktext).toEqual(['100', '200', '300']);
  });

  it('keeps nulls as gaps rather than as zeros', () => {
    const scale = buildAxisScale([0, null, 10], 'minmax');
    expect(scale.values).toEqual([0, null, 1]);
  });

  it('draws a constant column as one flat line with one honest tick', () => {
    const scale = buildAxisScale([7, 7, 7], 'minmax');
    expect(scale.values).toEqual([0.5, 0.5, 0.5]);
    expect(scale.range).toEqual([0, 1]);
    expect(scale.ticktext).toEqual(['7']);
    expect(scale.toOriginal(0.9)).toBe(7);
  });

  it('survives an axis with no values at all', () => {
    const scale = buildAxisScale([null, ''], 'zscore');
    expect(scale.values).toEqual([null, null]);
    expect(scale.range).toEqual([0, 1]);
  });
});
