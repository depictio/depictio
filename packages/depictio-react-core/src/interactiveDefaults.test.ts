import { describe, expect, it } from 'vitest';

import type { InteractiveFilter, StoredMetadata } from './api';
import { defaultFilterValue, withInteractiveDefaults } from './interactiveDefaults';

const control = (
  index: string,
  kind: string,
  default_state?: StoredMetadata['default_state'],
): StoredMetadata => ({
  index,
  component_type: 'interactive',
  interactive_component_type: kind,
  column_name: `col_${index}`,
  dc_id: 'dc1',
  default_state,
});

describe('defaultFilterValue', () => {
  it('wraps a Select default into the list the renderer emits', () => {
    expect(defaultFilterValue(control('a', 'Select', { default_value: 'Q10' }))).toEqual(['Q10']);
    expect(defaultFilterValue(control('a', 'MultiSelect', { default_value: ['x', 2] }))).toEqual([
      'x',
      '2',
    ]);
  });

  it('reads a numeric RangeSlider range', () => {
    expect(defaultFilterValue(control('r', 'RangeSlider', { default_range: [1, '5'] }))).toEqual([
      1, 5,
    ]);
    expect(defaultFilterValue(control('r', 'RangeSlider', { default_range: [1] }))).toBeUndefined();
  });

  it('handles Slider, SegmentedControl and Switch', () => {
    expect(defaultFilterValue(control('s', 'Slider', { default_value: 3 }))).toBe(3);
    expect(defaultFilterValue(control('g', 'SegmentedControl', { default_value: 'stage1' }))).toBe(
      'stage1',
    );
    expect(defaultFilterValue(control('w', 'Switch', { default_value: 'true' }))).toBe(true);
  });

  it('ignores controls without a declared default', () => {
    expect(defaultFilterValue(control('n', 'MultiSelect'))).toBeUndefined();
    expect(defaultFilterValue(control('n', 'MultiSelect', { default_value: [] }))).toBeUndefined();
    // A RangeSlider's default_value is not its range.
    expect(defaultFilterValue(control('n', 'RangeSlider', { default_value: 3 }))).toBeUndefined();
  });
});

describe('withInteractiveDefaults', () => {
  const md = [
    control('sel', 'Select', { default_value: 'Q10' }),
    control('rng', 'RangeSlider', { default_range: [0, 1] }),
    control('none', 'MultiSelect'),
    { index: 'card', component_type: 'card', dc_id: 'dc1' } as StoredMetadata,
  ];

  it('seeds one entry per declared default, with the dc binding', () => {
    const out = withInteractiveDefaults([], md);
    expect(out.map((f) => [f.index, f.value])).toEqual([
      ['sel', ['Q10']],
      ['rng', [0, 1]],
    ]);
    expect(out[0].metadata?.dc_id).toBe('dc1');
  });

  it('never overrides an existing value, even a cleared one', () => {
    const existing: InteractiveFilter[] = [{ index: 'sel', value: null }];
    const out = withInteractiveDefaults(existing, md);
    expect(out.find((f) => f.index === 'sel')?.value).toBeNull();
    expect(out.map((f) => f.index)).toEqual(['sel', 'rng']);
  });

  it('returns the same array when nothing applies', () => {
    const filters: InteractiveFilter[] = [];
    expect(withInteractiveDefaults(filters, [control('none', 'MultiSelect')])).toBe(filters);
  });
});
