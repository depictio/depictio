import { describe, expect, it } from 'vitest';

import {
  groupTabs,
  sameTabGroup,
  tabGroupNames,
  tabGroupOf,
  tabIdsInGroup,
  tabOrderAfterGroupMove,
  tabOrderAfterRegroup,
  tabOrderEntries,
} from './tabGroups';

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

// ---------------------------------------------------------------------------
// Editing groups
// ---------------------------------------------------------------------------

interface ETab {
  dashboard_id: string;
  parent_dashboard_id?: string | null;
  tab_group?: string | null;
}
const emain: ETab = { dashboard_id: 'overview' };
const ec = (id: string, tab_group?: string | null): ETab => ({
  dashboard_id: id,
  parent_dashboard_id: 'overview',
  tab_group,
});
// overview, downloads | Campaign: campaign, ctd | Analysis: alpha, beta | Quality: qc
const family = [
  emain,
  ec('campaign', 'Campaign'),
  ec('downloads'),
  ec('alpha', 'Analysis'),
  ec('ctd', 'Campaign'),
  ec('beta', 'Analysis'),
  ec('qc', 'Quality'),
];

describe('sameTabGroup', () => {
  it('ignores case and spacing, and treats blank as no group', () => {
    expect(sameTabGroup('Quality  control', ' quality control')).toBe(true);
    expect(sameTabGroup('A', 'B')).toBe(false);
    expect(sameTabGroup('', null)).toBe(true);
    expect(sameTabGroup('A', null)).toBe(false);
  });
});

describe('tabIdsInGroup', () => {
  it('lists every child tab of the group, matching loosely', () => {
    expect(tabIdsInGroup(family, 'campaign')).toEqual(['campaign', 'ctd']);
    expect(tabIdsInGroup(family, 'Analysis')).toEqual(['alpha', 'beta']);
  });

  it('never includes the main tab, even if it names the group', () => {
    const tabs = [{ ...emain, tab_group: 'Quality' }, ec('qc', 'Quality')];
    expect(tabIdsInGroup(tabs, 'Quality')).toEqual(['qc']);
  });

  it('is empty for an unknown group', () => {
    expect(tabIdsInGroup(family, 'Nope')).toEqual([]);
  });
});

describe('tabOrderAfterGroupMove', () => {
  it('moves a whole group down past the next one', () => {
    expect(tabOrderAfterGroupMove(family, 'Campaign', 'down')).toEqual([
      'downloads',
      'alpha',
      'beta',
      'campaign',
      'ctd',
      'qc',
    ]);
  });

  it('moves a group up, keeping the ungrouped tabs first', () => {
    expect(tabOrderAfterGroupMove(family, 'Quality', 'up')).toEqual([
      'downloads',
      'campaign',
      'ctd',
      'qc',
      'alpha',
      'beta',
    ]);
  });

  it('refuses to move the first group above the ungrouped tabs', () => {
    expect(tabOrderAfterGroupMove(family, 'Campaign', 'up')).toBeNull();
  });

  it('refuses to move the last group down, or an unknown group', () => {
    expect(tabOrderAfterGroupMove(family, 'Quality', 'down')).toBeNull();
    expect(tabOrderAfterGroupMove(family, 'Nope', 'up')).toBeNull();
  });

  it('can move the first group up when nothing is ungrouped', () => {
    const tabs = [ec('a', 'A'), ec('b', 'B')];
    expect(tabOrderAfterGroupMove(tabs, 'B', 'up')).toEqual(['b', 'a']);
  });
});

describe('tabOrderAfterRegroup', () => {
  it('appends a tab to the end of an existing group', () => {
    expect(tabOrderAfterRegroup(family, ['qc'], 'campaign')).toEqual([
      'downloads',
      'campaign',
      'ctd',
      'qc',
      'alpha',
      'beta',
    ]);
  });

  it('adds a new group after the others', () => {
    expect(tabOrderAfterRegroup(family, ['downloads', 'ctd'], 'Extras')).toEqual([
      'campaign',
      'alpha',
      'beta',
      'qc',
      'downloads',
      'ctd',
    ]);
  });

  it('moves tabs out of their group to the end of the ungrouped tabs', () => {
    expect(tabOrderAfterRegroup(family, ['alpha', 'beta'], null)).toEqual([
      'downloads',
      'alpha',
      'beta',
      'campaign',
      'ctd',
      'qc',
    ]);
  });

  it('never moves the main tab', () => {
    expect(tabOrderAfterRegroup(family, ['overview'], 'Quality')).toEqual([
      'downloads',
      'campaign',
      'ctd',
      'alpha',
      'beta',
      'qc',
    ]);
  });
});

describe('tabOrderEntries', () => {
  it('numbers children from 1', () => {
    expect(tabOrderEntries(['a', 'b'])).toEqual([
      { dashboard_id: 'a', tab_order: 1 },
      { dashboard_id: 'b', tab_order: 2 },
    ]);
  });
});
