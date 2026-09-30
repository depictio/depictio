import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from '../../api';
import { autoPickValue, isAlwaysSelected, singlePick } from './alwaysSelected';

const opts = (...values: string[]) => values.map((value) => ({ value }));

describe('isAlwaysSelected', () => {
  const meta = (kind: string, flag?: boolean): StoredMetadata => ({
    index: 'a',
    component_type: 'interactive',
    interactive_component_type: kind,
    always_selected: flag,
  });

  it('is on only for a Select that sets the flag', () => {
    expect(isAlwaysSelected(meta('Select', true))).toBe(true);
    expect(isAlwaysSelected(meta('Select'))).toBe(false);
    expect(isAlwaysSelected(meta('MultiSelect', true))).toBe(false);
  });
});

describe('autoPickValue', () => {
  const base = { enabled: true, loading: false, selected: [] as string[], options: opts('b', 'c') };

  it('picks the first option shown when the filter is empty', () => {
    expect(autoPickValue(base)).toEqual(['b']);
  });

  it('skips a greyed-out option, unless every option is greyed out', () => {
    const options = [{ value: 'x', disabled: true }, { value: 'y' }];
    expect(autoPickValue({ ...base, options })).toEqual(['y']);
    expect(autoPickValue({ ...base, options: [{ value: 'x', disabled: true }] })).toEqual(['x']);
  });

  it('does nothing when off, loading, already set or without options', () => {
    expect(autoPickValue({ ...base, enabled: false })).toBeNull();
    expect(autoPickValue({ ...base, loading: true })).toBeNull();
    expect(autoPickValue({ ...base, selected: ['c'] })).toBeNull();
    expect(autoPickValue({ ...base, options: [] })).toBeNull();
    expect(autoPickValue({ ...base, selected: ['gone'], options: [] })).toBeNull();
  });

  it('re-picks when the held value is greyed out or gone from the list', () => {
    const narrowed = [{ value: 'b', disabled: true }, { value: 'c' }];
    expect(autoPickValue({ ...base, selected: ['b'], options: narrowed })).toEqual(['c']);
    expect(autoPickValue({ ...base, selected: ['old_run'] })).toEqual(['b']);
    // The re-pick is stable: once it is held, nothing more is emitted.
    expect(autoPickValue({ ...base, selected: ['c'], options: narrowed })).toBeNull();
  });

  it('keeps a listed value when every option is greyed out', () => {
    const allGrey = [
      { value: 'x', disabled: true },
      { value: 'y', disabled: true },
    ];
    expect(autoPickValue({ ...base, selected: ['y'], options: allGrey })).toBeNull();
    expect(autoPickValue({ ...base, selected: ['gone'], options: allGrey })).toEqual(['x']);
  });
});

describe('singlePick', () => {
  it('keeps only the newest value of a multi-value change', () => {
    expect(singlePick(['b', 'c'], opts('b', 'c'))).toEqual(['c']);
    expect(singlePick(['c'], opts('b', 'c'))).toEqual(['c']);
  });

  it('falls back to the first option instead of going empty', () => {
    expect(singlePick([], opts('b', 'c'))).toEqual(['b']);
    expect(singlePick([], [])).toEqual([]);
  });
});
