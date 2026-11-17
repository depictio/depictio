import { describe, expect, it } from 'vitest';

import type { GroupRenderState } from '../../selectionGroups';
import { foreignGroups, groupsToTranslate, isRunGroup, runsAmbiguous, withResolvedGroups } from './groupsForDc';

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

describe('groups of runs (the Overlay of "What\'s new")', () => {
  const runs = (): GroupRenderState => ({
    colorByGroup: true,
    groups: [
      { name: 'New: 2 runs', column_name: 'depictio_run_id', values: ['b', 'c'], color: '#228be6' },
      { name: 'Seen before', column_name: 'depictio_run_id', values: ['a'], color: '#adb5bd' },
      { name: 'Loose', column_name: 'sample', values: ['s2'], color: '#d62728' },
    ],
  });

  it('are asked for only with a component to aim at', () => {
    expect(groupsToTranslate(runs().groups, 'libs', undefined)).toEqual([]);
    expect(groupsToTranslate(runs().groups, 'libs', 'emb').map((g) => g.name)).toEqual([
      'New: 2 runs',
      'Seen before',
    ]);
    expect(isRunGroup(runs().groups[2])).toBe(false);
  });

  it('become the component ids the server returns', () => {
    const resolved = {
      groups: [
        { name: 'New: 2 runs', column_name: 'sample_id', values: ['s2', 's3'], color: '#228be6' },
        { name: 'Seen before', column_name: 'sample_id', values: ['s1'], color: '#adb5bd' },
      ],
      status: [],
    };
    const out = withResolvedGroups(runs(), 'libs', resolved, 'emb');
    expect(out.groups.map((g) => [g.name, g.values])).toEqual([
      ['New: 2 runs', ['s2', 's3']],
      ['Seen before', ['s1']],
      ['Loose', ['s2']],
    ]);
  });

  it('are refused when a mark holds rows of both sides', () => {
    const refused = {
      groups: [],
      status: [
        { name: 'New: 2 runs', status: 'runs_ambiguous', applied: false, matched_values: 0 },
        { name: 'Seen before', status: 'runs_ambiguous', applied: false, matched_values: 0 },
      ],
    };
    expect(runsAmbiguous(refused)).toBe(true);
    expect(withResolvedGroups(runs(), 'libs', refused, 'emb').groups.map((g) => g.name)).toEqual(['Loose']);
    expect(runsAmbiguous(null)).toBe(false);
  });
});
