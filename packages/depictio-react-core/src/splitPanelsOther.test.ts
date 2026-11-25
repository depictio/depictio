import { describe, expect, it } from 'vitest';

import type { GroupRenderState } from './selectionGroups';
import {
  OTHER_LABEL,
  groupingModeForComponent,
  panelsForGrouping,
  panelsFromGroups,
  shouldSplitIntoPanels,
} from './splitPanels';

const river = { name: 'River', column_name: 'sample', values: ['s1', 's2'], color: '#f00', dc_id: 'pcoa' };
const soil = { name: 'Soil', column_name: 'sample', values: ['s3'], color: '#0f0', dc_id: 'pcoa' };
const byHabitat = { name: 'Wet', column_name: 'habitat', values: ['lake'], color: '#00f', dc_id: 'meta' };

const facet = (groups: GroupRenderState['groups'], extra: Partial<GroupRenderState> = {}): GroupRenderState => ({
  groups,
  colorByGroup: true,
  display: 'facet',
  ...extra,
});

describe('the "Other" panel of an analysis split (#1476)', () => {
  it('turns a single saved group into a split: the group, then Other', () => {
    const panels = panelsForGrouping(facet([river]));
    expect(panels.map((p) => p.name)).toEqual(['River', OTHER_LABEL]);
    expect(shouldSplitIntoPanels(panels, 'rarefaction')).toBe(true);
    const [other] = panels[1].constraints;
    expect(other.value).toEqual(['s1', 's2']);
    expect(other.metadata?.exclude).toBe(true);
    expect(other.metadata?.dc_id).toBe('pcoa');
    // The group panel itself excludes nothing.
    expect(panels[0].constraints[0].metadata?.exclude).toBeUndefined();
  });

  it('holds every group of one column in one excluding constraint', () => {
    const other = panelsForGrouping(facet([river, soil])).slice(-1)[0];
    expect(other.constraints).toHaveLength(1);
    expect(other.constraints[0].value).toEqual(['s1', 's2', 's3']);
  });

  it('excludes per collection and column when groups were drawn on several', () => {
    const other = panelsFromGroups([river, byHabitat], { showOther: true }).slice(-1)[0];
    expect(other.constraints.map((c) => [c.metadata?.dc_id, c.column_name, c.value])).toEqual([
      ['pcoa', 'sample', ['s1', 's2']],
      ['meta', 'habitat', ['lake']],
    ]);
  });

  it('is dropped when the reader hides Other, and never added to the runs split', () => {
    expect(panelsForGrouping(facet([river], { showOther: false })).map((p) => p.name)).toEqual(['River']);
    expect(
      panelsForGrouping(facet([river, soil], { keepColor: true })).map((p) => p.name),
    ).toEqual(['River', 'Soil']);
  });

  it('keeps the bare builder free of Other for its existing callers', () => {
    expect(panelsFromGroups([river]).map((p) => p.name)).toEqual(['River']);
  });
});

describe('phylogenetic policy follows its view', () => {
  it('splits the summary by rank and not the full tree', () => {
    expect(groupingModeForComponent('phylogenetic', {})).toBe('none');
    expect(groupingModeForComponent('rarefaction')).toBe('split');
  });
});
