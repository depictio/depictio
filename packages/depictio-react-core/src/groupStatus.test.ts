import { describe, expect, it } from 'vitest';

import {
  GROUP_DECLINED_REASONS,
  advancedVizGroupOutcome,
  groupBadgeLabel,
  groupBadgeReasons,
  groupKindNotSplitReasons,
  groupUnmatchedReasons,
  groupUnreachableReasons,
  summarizeGroupStatus,
  type AdvancedVizGroupInputs,
  type GroupStatusEntry,
} from './groupStatus';

const applied = (name: string): GroupStatusEntry => ({ name, status: 'applied', applied: true });
const linked = (name: string): GroupStatusEntry => ({ name, status: 'linked', applied: true });
const missed = (name: string, status: string): GroupStatusEntry => ({
  name,
  status,
  applied: false,
});

describe('summarizeGroupStatus', () => {
  it('says nothing when grouping was never requested', () => {
    expect(summarizeGroupStatus(undefined)).toBeNull();
    expect(summarizeGroupStatus([])).toBeNull();
  });

  it('counts a clean run with no explanation to give', () => {
    const s = summarizeGroupStatus([applied('Soil'), linked('River')]);
    expect(s).toEqual({ applied: 2, total: 2, unapplied: [], faulted: false });
  });

  it('phrases each refusal for a dashboard reader', () => {
    const s = summarizeGroupStatus([
      applied('Soil'),
      missed('River', 'column_absent'),
      missed('Lake', 'no_link'),
    ]);
    expect(s?.applied).toBe(1);
    expect(s?.total).toBe(3);
    expect(s?.unapplied).toEqual([
      { name: 'River', reason: 'the column it was drawn on is not in this dataset' },
      { name: 'Lake', reason: 'no declared link joins this dataset to the one it was drawn on' },
    ]);
  });

  it('separates a fault from an honest mismatch', () => {
    expect(summarizeGroupStatus([missed('River', 'link_no_match')])?.faulted).toBe(false);
    expect(summarizeGroupStatus([missed('River', 'link_failed')])?.faulted).toBe(true);
  });

  it('still names the group when the server invents a new status', () => {
    const s = summarizeGroupStatus([missed('River', 'something_new')]);
    expect(s?.unapplied[0].name).toBe('River');
    expect(s?.unapplied[0].reason).toContain('something_new');
  });

  it('treats an undecided group as having reached the frame', () => {
    // `unknown` means the schema could not be read, so the server passed the
    // group through rather than dropping it — claiming it missed would be worse.
    const s = summarizeGroupStatus([{ name: 'Soil', status: 'unknown', applied: true }]);
    expect(s?.applied).toBe(1);
    expect(s?.unapplied).toEqual([]);
  });
});

describe('groupBadgeLabel', () => {
  it('is plain when every group landed', () => {
    expect(groupBadgeLabel(true, summarizeGroupStatus([applied('Soil')]))).toBe('grouped');
  });

  it('counts when only some landed', () => {
    const s = summarizeGroupStatus([applied('Soil'), missed('River', 'no_link')]);
    expect(groupBadgeLabel(true, s)).toBe('grouped (1 of 2)');
  });

  it('says so when none landed', () => {
    const s = summarizeGroupStatus([missed('River', 'column_absent')]);
    expect(groupBadgeLabel(false, s)).toBe('not grouped');
  });

  it('stays silent when grouping was never requested', () => {
    expect(groupBadgeLabel(false, null)).toBeNull();
  });

  it('says so when the groups landed but the figure declined the override', () => {
    // `group_colored: false` with every group applied is a code figure that
    // ignores `depictio_group_kwargs`, or a visu type refusing the repaint.
    // Either way the reader sees an ungrouped tile, and silence would read as
    // a tile that simply ignores the feature.
    expect(groupBadgeLabel(false, summarizeGroupStatus([applied('Soil')]))).toBe('not grouped');
  });
});

describe('groupBadgeReasons', () => {
  it('has nothing to explain when every group landed and the figure repainted', () => {
    expect(groupBadgeReasons(true, summarizeGroupStatus([applied('Soil')]), 'unused')).toEqual([]);
  });

  it('lists each group that missed', () => {
    const s = summarizeGroupStatus([applied('Soil'), missed('River', 'no_link')]);
    expect(groupBadgeReasons(true, s, GROUP_DECLINED_REASONS.code)).toEqual([
      'River: no declared link joins this dataset to the one it was drawn on',
    ]);
  });

  it("names the figure's code when the groups landed but nothing was drawn", () => {
    const s = summarizeGroupStatus([applied('Soil')]);
    expect(groupBadgeReasons(false, s, GROUP_DECLINED_REASONS.code)).toEqual([
      "This figure's code does not use analysis groups.",
    ]);
  });

  it('does not blame the code when no group reached the frame at all', () => {
    const s = summarizeGroupStatus([missed('River', 'column_absent')]);
    expect(groupBadgeReasons(false, s, GROUP_DECLINED_REASONS.code)).toEqual([
      'River: the column it was drawn on is not in this dataset',
    ]);
  });
});

describe('groupUnreachableReasons', () => {
  it('explains a component the groups cannot narrow', () => {
    expect(groupUnreachableReasons()).toEqual([
      'The groups were drawn on another dataset and no declared link reaches this one.',
    ]);
  });
});

describe('groupKindNotSplitReasons', () => {
  it('blames the chart type, not a missing link', () => {
    // A reader who sees the link reason would go and declare a link, which
    // would change nothing for a kind that is never split.
    expect(groupKindNotSplitReasons()).toEqual([
      'This chart type is not split or coloured by analysis groups.',
    ]);
    expect(groupKindNotSplitReasons()).not.toEqual(groupUnreachableReasons());
  });
});

describe('groupUnmatchedReasons', () => {
  it('blames the rows, not a missing link or the chart type', () => {
    // The groups may come from this very dataset, drawn on a column this plot
    // is not keyed by: neither a link nor another chart type would help.
    expect(groupUnmatchedReasons()).toEqual([
      "None of this figure's points belong to a group: its rows carry no value the groups were drawn on.",
    ]);
    expect(groupUnmatchedReasons()).not.toEqual(groupUnreachableReasons());
    expect(groupUnmatchedReasons()).not.toEqual(groupKindNotSplitReasons());
  });
});

describe('advancedVizGroupOutcome', () => {
  const whole: AdvancedVizGroupInputs = {
    groupsActive: true,
    split: false,
    declinedByKind: false,
    splitIneffective: false,
    coloured: null,
    drawnHere: false,
  };

  it('says nothing when no groups are active', () => {
    expect(advancedVizGroupOutcome({ ...whole, groupsActive: false, coloured: false })).toEqual({
      badge: null,
      reach: null,
    });
  });

  it('blames the chart type for a kind that declines, whatever else is known', () => {
    expect(advancedVizGroupOutcome({ ...whole, declinedByKind: true, drawnHere: true })).toEqual({
      badge: 'kind',
      reach: false,
    });
  });

  it('counts a drawing split as reached', () => {
    expect(advancedVizGroupOutcome({ ...whole, split: true })).toEqual({
      badge: null,
      reach: true,
    });
  });

  it('counts a whole render whose recolour matched, wherever the groups were drawn', () => {
    expect(advancedVizGroupOutcome({ ...whole, coloured: true })).toEqual({
      badge: null,
      reach: true,
    });
  });

  it('badges a whole render whose recolour matched nothing, even on its own dataset', () => {
    // Groups of samples drawn on this dataset still miss a plot keyed per
    // peak: the dataset guess must not outvote what the renderer saw.
    expect(advancedVizGroupOutcome({ ...whole, coloured: false, drawnHere: true })).toEqual({
      badge: 'unmatched',
      reach: false,
    });
  });

  it('keeps the link reason for a split that proved ineffective', () => {
    expect(advancedVizGroupOutcome({ ...whole, splitIneffective: true })).toEqual({
      badge: 'unreachable',
      reach: false,
    });
    expect(
      advancedVizGroupOutcome({ ...whole, splitIneffective: true, coloured: false }),
    ).toEqual({ badge: 'unreachable', reach: false });
  });

  it('does not badge a tile that did colour after an ineffective split', () => {
    expect(advancedVizGroupOutcome({ ...whole, splitIneffective: true, coloured: true })).toEqual({
      badge: null,
      reach: true,
    });
  });

  it('falls back to the dataset guess when the renderer reports nothing', () => {
    expect(advancedVizGroupOutcome({ ...whole, drawnHere: true })).toEqual({
      badge: null,
      reach: true,
    });
    expect(advancedVizGroupOutcome(whole)).toEqual({ badge: null, reach: null });
  });
});
