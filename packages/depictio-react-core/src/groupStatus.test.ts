import { describe, expect, it } from 'vitest';

import { groupBadgeLabel, summarizeGroupStatus, type GroupStatusEntry } from './groupStatus';

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

  it('stays silent when the groups landed but the figure declined the override', () => {
    // `group_colored: false` with every group applied is a visu type refusing
    // the repaint, not a group that missed — the tile is not "not grouped".
    expect(groupBadgeLabel(false, summarizeGroupStatus([applied('Soil')]))).toBeNull();
  });
});
