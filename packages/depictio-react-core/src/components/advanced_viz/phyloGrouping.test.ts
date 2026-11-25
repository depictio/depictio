import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../api';
import { panelFilters, panelsFromGroups } from '../../splitPanels';
import { parseNewick } from './phylo/newick';
import { aggregateAbundance, summariseByRank } from './phylo/rankSummary';
import { hasGroupConstraint, phyloDrawsSummary, phyloGroupingMode } from './phyloGrouping';

const BASE = {
  tree_wf_id: 'wf',
  tree_dc_id: 'tree',
  metadata_wf_id: 'wf',
  metadata_dc_id: 'meta',
  color_col: 'Kingdom',
};

describe('phyloGroupingMode', () => {
  it('splits the summary', () => {
    expect(phyloGroupingMode({ ...BASE, collapse_rank: 'Phylum' })).toBe('split');
  });

  it('keeps the full tree whole', () => {
    expect(phyloGroupingMode(BASE)).toBe('none');
    expect(phyloGroupingMode({ ...BASE, collapse_rank: null })).toBe('none');
    expect(phyloGroupingMode(undefined)).toBe('none');
  });

  it('draws the full tree when the config cannot draw the summary', () => {
    // No tip metadata: the router falls back to the tree, so the policy must too.
    const noMeta = { tree_wf_id: 'wf', tree_dc_id: 'tree', collapse_rank: 'Phylum' };
    expect(phyloDrawsSummary(noMeta)).toBe(false);
    expect(phyloGroupingMode(noMeta)).toBe('none');
  });
});

describe('hasGroupConstraint', () => {
  it('sees a split panel cell, and nothing else', () => {
    const [panel] = panelsFromGroups([
      { name: 'North', color: '#000', column_name: 'sample', values: ['a', 'b'], dc_id: 'dc' },
    ]);
    const dashboard: InteractiveFilter[] = [
      {
        index: 'f1',
        value: ['x'],
        column_name: 'Kingdom',
        interactive_component_type: 'MultiSelect',
      } as InteractiveFilter,
    ];
    expect(hasGroupConstraint(dashboard)).toBe(false);
    expect(hasGroupConstraint(panelFilters(dashboard, panel))).toBe(true);
  });
});

describe('a Split panel of the summary', () => {
  // What a panel does with its fetch: the abundance rows narrowed to the group's
  // samples, summarised over the same tree and the same tip metadata.
  const tree = () => parseNewick('((A1:1,A2:1):1,(B1:1,B2:1):1);');
  const groupOf = (tip: string) => tip[0];
  const rows = {
    sample: ['s1', 's1', 's2', 's2', 's3'],
    Phylum: ['A', 'B', 'A', 'B', 'A'],
    rel_abundance: [0.8, 0.2, 0.1, 0.9, 1],
  };
  const panel = (samples: string[]) => {
    const keep = rows.sample.map((s) => samples.includes(s));
    const narrowed = Object.fromEntries(
      Object.entries(rows).map(([k, v]) => [k, v.filter((_, i) => keep[i])]),
    );
    const abundance = aggregateAbundance(narrowed, {
      rank: 'Phylum',
      value: 'rel_abundance',
      sample: 'sample',
    });
    return summariseByRank(tree(), groupOf, { topN: 10, colourOf: () => null, abundance });
  };

  const shares = (summary: ReturnType<typeof panel>) =>
    Object.fromEntries((summary?.shown ?? []).map((g) => [g.group, g.share]));

  it('computes each lineage share from that group alone', () => {
    const first = shares(panel(['s1']));
    const second = shares(panel(['s2']));
    expect(first.A).toBeCloseTo(0.8);
    expect(first.B).toBeCloseTo(0.2);
    expect(second.A).toBeCloseTo(0.1);
    expect(second.B).toBeCloseTo(0.9);
  });

  it('drops a lineage the group has no reads of', () => {
    const only = panel(['s3']);
    expect(only?.shown.map((g) => g.group)).toEqual(['A']);
  });
});
