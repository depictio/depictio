import { describe, expect, it } from 'vitest';

import type { GroupRenderState } from '../../selectionGroups';
import { foreignGroups, withResolvedGroups } from './groupsForDc';

const state = (): GroupRenderState => ({
  colorByGroup: true,
  groups: [
    { name: 'Group 1', column_name: 'guide', values: ['AAA', 'CCC'], color: '#1f77b4', dc_id: 'guides' },
    { name: 'Group 2', column_name: 'guide', values: ['GGG'], color: '#ff7f0e', dc_id: 'guides' },
    { name: 'Local', column_name: 'sample', values: ['s1'], color: '#2ca02c', dc_id: 'libs' },
    { name: 'Loose', column_name: 'sample', values: ['s2'], color: '#d62728' },
  ],
});

describe('foreignGroups', () => {
  it('keeps groups captured on another collection only', () => {
    expect(foreignGroups(state().groups, 'libs').map((g) => g.name)).toEqual(['Group 1', 'Group 2']);
  });
  it('asks for nothing when the collection is unknown', () => {
    expect(foreignGroups(state().groups, undefined)).toEqual([]);
  });
});

describe('withResolvedGroups', () => {
  const resolved = {
    groups: [{ name: 'Group 1', column_name: 'sample', values: ['s7', 's8'], color: '#1f77b4', dc_id: 'libs' }],
    status: [],
  };

  it('swaps a translated group in place and drops one that could not be translated', () => {
    const out = withResolvedGroups(state(), 'libs', resolved);
    expect(out.groups.map((g) => g.name)).toEqual(['Group 1', 'Local', 'Loose']);
    expect(out.groups[0]).toMatchObject({ column_name: 'sample', values: ['s7', 's8'], color: '#1f77b4' });
  });

  it('drops every foreign group while the translation is pending', () => {
    const out = withResolvedGroups(state(), 'libs', null);
    expect(out.groups.map((g) => g.name)).toEqual(['Local', 'Loose']);
  });

  it('returns the state untouched when every group is native', () => {
    const native = { ...state(), groups: state().groups.slice(2) };
    expect(withResolvedGroups(native, 'libs', null)).toBe(native);
  });
});
