import { describe, expect, it } from 'vitest';

import { sequentialOrder } from './categoryColors';
import { orderCategoricalOptions, optionOrderOf } from './components/interactive/categoricalOptions';
import { facetValues } from './components/advanced_viz/genomespy/genomeSpySpec';
import { parseDurationHours, sortNaturalOrDuration } from './durationOrder';

describe('parseDurationHours', () => {
  it('reads the trailing duration', () => {
    expect(parseDurationHours('30min')).toBe(0.5);
    expect(parseDurationHours('2h')).toBe(2);
    expect(parseDurationHours('1d')).toBe(24);
    expect(parseDurationHours('GM_12h')).toBe(12);
    expect(parseDurationHours('1.5 hr')).toBe(1.5);
    expect(parseDurationHours('45s')).toBeCloseTo(0.0125);
  });
  it('reads nothing from an id that merely ends in a number', () => {
    expect(parseDurationHours('REP12')).toBeNull();
    expect(parseDurationHours('Sample_2')).toBeNull();
    expect(parseDurationHours('')).toBeNull();
    expect(parseDurationHours(null)).toBeNull();
  });
});

describe('sortNaturalOrDuration', () => {
  it('puts 30min after 0h and before 1h, 18h after 4h', () => {
    expect(sortNaturalOrDuration(['18h', '1h', '30min', '2h', '0h', '4h', '1d'])).toEqual([
      '0h',
      '30min',
      '1h',
      '2h',
      '4h',
      '18h',
      '1d',
    ]);
  });
  it('sorts naturally when a value is no duration', () => {
    expect(sortNaturalOrDuration(['Sample_10', 'Sample_2'])).toEqual(['Sample_2', 'Sample_10']);
    expect(sortNaturalOrDuration(['30min', 'control', '1h'])).toEqual(['1h', '30min', 'control']);
  });
});

describe('orderCategoricalOptions', () => {
  it('orders durations by duration, available values first', () => {
    const out = orderCategoricalOptions(['18h', '30min', '1h'], new Set(['18h', '30min']));
    expect(out).toEqual(['30min', '18h', '1h']);
  });
  it('keeps the arrival order for a filter with order_by', () => {
    const arrived = ['30min', '1h', '18h'];
    expect(orderCategoricalOptions(arrived, null, 'given')).toEqual(arrived);
    // available values still come first
    expect(orderCategoricalOptions(arrived, new Set(['18h']), 'given')).toEqual(['18h', '30min', '1h']);
    expect(optionOrderOf({ order_by: 'time_order' })).toBe('given');
    expect(optionOrderOf({})).toBe('natural');
  });
});

describe('time course orders elsewhere', () => {
  it('walks a colour ramp in time with no order_by', () => {
    expect(sequentialOrder(['18h', '30min', '2h'])).toEqual(['30min', '2h', '18h']);
  });
  it('stacks the lanes of a time course in time', () => {
    const rows = ['GM_18h', 'GM_30min', 'GM_1h'].map((sample) => ({ sample }));
    expect(facetValues(rows, 'sample', 8).kept).toEqual(['GM_30min', 'GM_1h', 'GM_18h']);
  });
});
