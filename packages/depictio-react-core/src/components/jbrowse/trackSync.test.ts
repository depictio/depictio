import { describe, expect, it } from 'vitest';

import {
  jbrowseSelectionFilter,
  planTrackSync,
  selectionValuesFor,
  toggleValue,
} from './trackSync';

const rows = [
  { track_id: 'a', name: 'A', format: 'bed', sample: 's1', selection_value: 's1' },
  { track_id: 'b', name: 'B', format: 'bed', sample: 's2', selection_value: 's2' },
  { track_id: 'c', name: 'C', format: 'bigwig', sample: 's1', selection_value: 's1' },
  { track_id: 'd', name: 'D', format: 'bigwig', sample: null, selection_value: null },
];

describe('planTrackSync', () => {
  it('hides managed tracks no longer wanted and shows the missing ones', () => {
    const plan = planTrackSync(['a', 'b'], ['b', 'c'], new Set(['a', 'b', 'c']));
    expect(plan).toEqual({ hide: ['a'], show: ['c'] });
  });

  it('never hides tracks it does not manage (annotation, user-opened)', () => {
    const plan = planTrackSync(['genes', 'a'], ['b'], new Set(['a', 'b']));
    expect(plan.hide).toEqual(['a']);
    expect(plan.show).toEqual(['b']);
  });

  it('is a no-op when the open set already matches', () => {
    expect(planTrackSync(['a'], ['a'], new Set(['a']))).toEqual({ hide: [], show: [] });
  });
});

describe('selectionValuesFor', () => {
  it('maps tracks to distinct selection values and skips unknown/null ones', () => {
    expect(selectionValuesFor(['a', 'c', 'b', 'd', 'zz'], rows)).toEqual(['s1', 's2']);
  });
});

describe('toggleValue', () => {
  it('adds then removes a value', () => {
    expect(toggleValue(['x'], 'y')).toEqual(['x', 'y']);
    expect(toggleValue(['x', 'y'], 'x')).toEqual(['y']);
  });
});

describe('jbrowseSelectionFilter', () => {
  it('targets the manifest DC so links carry it to the sample tables', () => {
    const f = jbrowseSelectionFilter('comp-1', 'cell', 'dc-tracks', ['c1']);
    expect(f.source).toBe('jbrowse_selection');
    expect(f.metadata?.dc_id).toBe('dc-tracks');
    expect(f.column_name).toBe('cell');
    expect(f.value).toEqual(['c1']);
  });
});
