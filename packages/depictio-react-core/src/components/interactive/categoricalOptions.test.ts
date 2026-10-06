import { describe, expect, it } from 'vitest';

import {
  MAX_STRIP_CHIPS,
  categoricalDisplay,
  chipFilterValue,
  chipSelectionMode,
  filterEvent,
  orderCategoricalOptions,
  selectedValues,
  toggleChip,
} from './categoricalOptions';
import { rangeSliderBounds, sliderBounds } from './numericScale';

describe('orderCategoricalOptions', () => {
  it('sorts naturally when every value is available', () => {
    expect(orderCategoricalOptions(['S10', 's2', 'S1'], null)).toEqual(['S1', 's2', 'S10']);
  });

  it('puts available values first, natural order within each bucket', () => {
    const available = new Set(['b', 'd']);
    expect(orderCategoricalOptions(['d', 'c', 'b', 'a'], available)).toEqual(['b', 'd', 'a', 'c']);
  });

  it('does not mutate its input', () => {
    const input = ['b', 'a'];
    orderCategoricalOptions(input, null);
    expect(input).toEqual(['b', 'a']);
  });
});

describe('categoricalDisplay', () => {
  it('draws chips up to the limit and a select beyond it', () => {
    expect(categoricalDisplay(0)).toBe('chips');
    expect(categoricalDisplay(4)).toBe('chips');
    expect(categoricalDisplay(MAX_STRIP_CHIPS)).toBe('chips');
    expect(categoricalDisplay(MAX_STRIP_CHIPS + 1)).toBe('select');
    expect(categoricalDisplay(5, 4)).toBe('select');
  });
});

describe('chip selection', () => {
  it('is multi for a MultiSelect, single for the one-of-N types', () => {
    expect(chipSelectionMode('MultiSelect')).toBe('multi');
    expect(chipSelectionMode('Select')).toBe('single');
    expect(chipSelectionMode('SegmentedControl')).toBe('single');
  });

  it('toggles membership in multi mode', () => {
    expect(toggleChip([], 'a', 'multi')).toEqual(['a']);
    expect(toggleChip(['a'], 'b', 'multi')).toEqual(['a', 'b']);
    expect(toggleChip(['a', 'b'], 'a', 'multi')).toEqual(['b']);
  });

  it('replaces, or clears on a second click, in single mode', () => {
    expect(toggleChip([], 'a', 'single')).toEqual(['a']);
    expect(toggleChip(['a'], 'b', 'single')).toEqual(['b']);
    expect(toggleChip(['a'], 'a', 'single')).toEqual([]);
  });

  it('reads every stored value shape as a list of selected values', () => {
    expect(selectedValues(['a', 'b'])).toEqual(['a', 'b']);
    expect(selectedValues('a')).toEqual(['a']);
    expect(selectedValues('')).toEqual([]);
    expect(selectedValues(null)).toEqual([]);
    expect(selectedValues(undefined)).toEqual([]);
    expect(selectedValues([1, null])).toEqual(['1']);
  });
});

describe('emitted values', () => {
  it('match what each type’s panel renderer emits', () => {
    // MultiSelectRenderer emits the list for MultiSelect and Select alike.
    expect(chipFilterValue(['a', 'b'], 'MultiSelect')).toEqual(['a', 'b']);
    expect(chipFilterValue(['a'], 'Select')).toEqual(['a']);
    expect(chipFilterValue([], 'MultiSelect')).toEqual([]);
    // SegmentedControlRenderer emits the one value, null when cleared.
    expect(chipFilterValue(['a'], 'SegmentedControl')).toBe('a');
    expect(chipFilterValue([], 'SegmentedControl')).toBeNull();
  });

  it('builds the event in the renderers’ shape', () => {
    const metadata = {
      index: 'i1',
      column_name: 'habitat',
      interactive_component_type: 'MultiSelect',
      filter_expr: "col('depth') > 3",
    };
    expect(filterEvent(metadata, ['Soil'])).toEqual({
      index: 'i1',
      value: ['Soil'],
      column_name: 'habitat',
      interactive_component_type: 'MultiSelect',
      filter_expr: "col('depth') > 3",
    });
    expect(filterEvent(metadata, [1, 2], 'RangeSlider').interactive_component_type).toBe(
      'RangeSlider',
    );
  });
});

describe('slider bounds', () => {
  it('fall back to 0–100 for a range slider missing an end', () => {
    expect(rangeSliderBounds({ min: null, max: 7 })).toEqual({ min: 0, max: 7, dtype: undefined, unique: undefined });
    expect(rangeSliderBounds({ min: 2, max: null, dtype: 'int64', unique: 4 })).toEqual({
      min: 2,
      max: 100,
      dtype: 'int64',
      unique: 4,
    });
    expect(rangeSliderBounds(null)).toBeNull();
  });

  it('are an error for a single slider missing an end', () => {
    expect(sliderBounds({ min: null, max: 7 }, 'depth', false)).toEqual({
      bounds: null,
      error: 'No numeric min/max available for column "depth".',
    });
  });

  it('are log10-transformed on a log scale, and refuse non-positive ends', () => {
    expect(sliderBounds({ min: 1, max: 1000 }, 'reads', true)).toEqual({
      bounds: { min: 0, max: 3 },
      error: null,
    });
    expect(sliderBounds({ min: 0, max: 1000 }, 'reads', true).error).toMatch(/non-positive/);
  });

  it('pass through on a linear scale', () => {
    expect(sliderBounds({ min: 1, max: 5, dtype: 'int64', unique: 5 }, 'x', false).bounds).toEqual({
      min: 1,
      max: 5,
      dtype: 'int64',
      unique: 5,
    });
  });
});
