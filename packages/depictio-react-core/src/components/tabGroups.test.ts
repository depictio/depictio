import { describe, expect, it } from 'vitest';

import { groupTabs, tabGroupNames, tabGroupOf } from './tabGroups';

interface Tab {
  id: string;
  parent_dashboard_id?: string | null;
  tab_group?: string | null;
}

const main: Tab = { id: 'overview' };
const child = (id: string, tab_group?: string | null): Tab => ({
  id,
  parent_dashboard_id: 'overview',
  tab_group,
});

/** Sections as `[group, ids]` pairs, which reads better in a failing diff. */
const shape = (tabs: Tab[]) => groupTabs(tabs).map((s) => [s.group, s.tabs.map((t) => t.id)]);

describe('groupTabs', () => {
  it('keeps an ungrouped family as one heading-less section', () => {
    expect(shape([main, child('a'), child('b')])).toEqual([[null, ['overview', 'a', 'b']]]);
  });

  it('orders groups by their first tab, each in tab_order', () => {
    const tabs = [
      main,
      child('campaign', 'Campaign'),
      child('ctd', 'Campaign'),
      child('alpha', 'Analysis'),
      child('ordination', 'Analysis'),
      child('qc', 'Quality'),
    ];
    expect(shape(tabs)).toEqual([
      [null, ['overview']],
      ['Campaign', ['campaign', 'ctd']],
      ['Analysis', ['alpha', 'ordination']],
      ['Quality', ['qc']],
    ]);
  });

  it('gathers a group whose tabs were interleaved with another', () => {
    const tabs = [main, child('a1', 'A'), child('b1', 'B'), child('a2', 'A'), child('b2', 'B')];
    expect(shape(tabs)).toEqual([
      [null, ['overview']],
      ['A', ['a1', 'a2']],
      ['B', ['b1', 'b2']],
    ]);
  });

  it('lists ungrouped tabs with the main tab, ahead of every group', () => {
    const tabs = [main, child('alpha', 'Analysis'), child('downloads'), child('qc', 'Quality')];
    expect(shape(tabs)).toEqual([
      [null, ['overview', 'downloads']],
      ['Analysis', ['alpha']],
      ['Quality', ['qc']],
    ]);
  });

  it('never groups the main tab', () => {
    const groupedMain: Tab = { id: 'overview', tab_group: 'Analysis' };
    expect(shape([groupedMain, child('alpha', 'Analysis')])).toEqual([
      [null, ['overview']],
      ['Analysis', ['alpha']],
    ]);
  });

  it('treats a blank group as no group', () => {
    expect(shape([main, child('a', '  '), child('b', '')])).toEqual([[null, ['overview', 'a', 'b']]]);
  });

  it('merges spellings that differ in case or spacing, keeping the first', () => {
    const tabs = [main, child('a', 'Quality  control'), child('b', ' quality control')];
    expect(shape(tabs)).toEqual([
      [null, ['overview']],
      ['Quality  control', ['a', 'b']],
    ]);
  });

  it('starts with a group when there is nothing ungrouped', () => {
    expect(shape([child('a', 'A')])).toEqual([['A', ['a']]]);
    expect(groupTabs([])).toEqual([]);
  });
});

describe('tabGroupOf', () => {
  it('trims the name', () => {
    expect(tabGroupOf(child('a', '  Analysis '))).toBe('Analysis');
  });
});

describe('tabGroupNames', () => {
  it('lists each group once, in sidebar order', () => {
    const tabs = [main, child('q', 'Quality'), child('a', 'Analysis'), child('q2', 'Quality')];
    expect(tabGroupNames(tabs)).toEqual(['Quality', 'Analysis']);
  });
});
