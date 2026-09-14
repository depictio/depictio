import { describe, expect, it } from 'vitest';

import { splitFigureByGroups } from './components/advanced_viz/groupSplit';
import {
  getGroupReach,
  groupColouringOutcome,
  noTileReceivesGroups,
  reportGroupReach,
  subscribeGroupReach,
} from './groupReach';
import type { GroupRenderState } from './selectionGroups';

describe('groupReach', () => {
  it('pools what each tile reported, and forgets a tile that withdraws', () => {
    reportGroupReach('fig-1', false);
    reportGroupReach('viz-1', false);
    expect(getGroupReach()).toEqual({ reported: 2, applied: 0 });
    expect(noTileReceivesGroups(getGroupReach())).toBe(true);

    reportGroupReach('viz-1', true);
    expect(getGroupReach()).toEqual({ reported: 2, applied: 1 });
    expect(noTileReceivesGroups(getGroupReach())).toBe(false);

    reportGroupReach('fig-1', null);
    reportGroupReach('viz-1', null);
    expect(getGroupReach()).toEqual({ reported: 0, applied: 0 });
  });

  it('says nothing until some tile has answered', () => {
    expect(noTileReceivesGroups({ reported: 0, applied: 0 })).toBe(false);
  });

  it('keeps the snapshot and stays quiet when nothing changed', () => {
    let calls = 0;
    const unsubscribe = subscribeGroupReach(() => {
      calls += 1;
    });
    reportGroupReach('fig-2', true);
    const before = getGroupReach();
    reportGroupReach('fig-2', true);
    reportGroupReach('never-reported', null);
    expect(getGroupReach()).toBe(before);
    expect(calls).toBe(1);
    reportGroupReach('fig-2', null);
    unsubscribe();
  });
});

describe('groupColouringOutcome', () => {
  /** Two points whose sample id sits at customdata slot 0. */
  const figure = () => ({
    data: [{ type: 'scatter', x: [1, 2], y: [1, 2], customdata: [['s1'], ['s2']] }],
    layout: {},
  });
  const groupsOf = (values: string[]): GroupRenderState => ({
    colorByGroup: true,
    groups: [{ name: 'Soil', column_name: 'sample_id', values, color: 'soil' }],
  });

  it('has nothing to judge without active groups or a figure', () => {
    const f = figure();
    const other = figure();
    expect(groupColouringOutcome(undefined, f, other)).toBeNull();
    expect(groupColouringOutcome({ ...groupsOf(['s1']), colorByGroup: false }, f, other)).toBeNull();
    expect(groupColouringOutcome({ colorByGroup: true, groups: [] }, f, other)).toBeNull();
    expect(groupColouringOutcome(groupsOf(['s1']), null, null)).toBeNull();
  });

  it('reads a changed figure as grouped and an identical one as not', () => {
    const f = figure();
    expect(groupColouringOutcome(groupsOf(['s1']), f, figure())).toBe(true);
    expect(groupColouringOutcome(groupsOf(['s1']), f, f)).toBe(false);
  });

  it("follows splitFigureByGroups' refusal to repaint a figure nothing matched", () => {
    const f = figure();
    const matched = groupsOf(['s1']);
    const unmatched = groupsOf(['peak_7']);
    const opts = { identitySlot: 0, facetable: false };
    expect(
      groupColouringOutcome(matched, f, splitFigureByGroups(f, { ...opts, groupRender: matched })),
    ).toBe(true);
    expect(
      groupColouringOutcome(unmatched, f, splitFigureByGroups(f, { ...opts, groupRender: unmatched })),
    ).toBe(false);
  });
});
