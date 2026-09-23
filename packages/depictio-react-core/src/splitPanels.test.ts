import { describe, expect, it } from 'vitest';

import type { GroupRenderState } from './selectionGroups';
import {
  GROUPING_MODE_BY_KIND,
  MAX_PANELS,
  crossPanels,
  groupingModeForKind,
  panelFilters,
  panelsForGrouping,
  panelsFromColumnValues,
  panelsFromGroups,
  shouldSplitIntoPanels,
} from './splitPanels';

const GROUPS = [
  { name: 'North', column_name: 'sample', values: ['s1', 's2'], color: '#4C72B0', dc_id: 'dc1' },
  { name: 'South', column_name: 'sample', values: ['s3'], color: '#DD8452', dc_id: 'dc1' },
];

describe('splitPanels', () => {
  it('makes one cell per group, carrying the source collection', () => {
    const panels = panelsFromGroups(GROUPS);
    expect(panels.map((p) => p.name)).toEqual(['North', 'South']);
    expect(panels[0].constraints).toHaveLength(1);
    expect(panels[0].constraints[0].value).toEqual(['s1', 's2']);
    // The source DC rides along so the server can resolve a cross-collection link.
    expect(panels[0].constraints[0].metadata?.dc_id).toBe('dc1');
  });

  it('skips a group with no values', () => {
    expect(panelsFromGroups([{ ...GROUPS[0], values: [] }])).toEqual([]);
  });

  it('makes one cell per value of a column', () => {
    const panels = panelsFromColumnValues('habitat', ['Soil', 'River'], { Soil: '#E24A33' });
    expect(panels.map((p) => p.name)).toEqual(['Soil', 'River']);
    expect(panels[0].color).toBe('#E24A33');
    expect(panels[1].color).toBeUndefined();
    expect(panels[0].constraints[0].column_name).toBe('habitat');
  });

  it('crosses two dimensions by concatenating their constraints', () => {
    const cells = crossPanels(
      panelsFromGroups(GROUPS),
      panelsFromColumnValues('habitat', ['Soil', 'River']),
    );
    expect(cells.map((c) => c.name)).toEqual([
      'North · Soil',
      'North · River',
      'South · Soil',
      'South · River',
    ]);
    // Two dimensions is two constraints. Nothing downstream counts them.
    expect(cells[0].constraints).toHaveLength(2);
    expect(cells[0].constraints.map((c) => c.column_name)).toEqual(['sample', 'habitat']);
  });

  it('leaves a single dimension alone when the other is empty', () => {
    const only = panelsFromGroups(GROUPS);
    expect(crossPanels(only, [])).toBe(only);
    expect(crossPanels([], only)).toBe(only);
  });

  it('appends a cell constraints to the dashboard filters, in that order', () => {
    const base = [{ index: 'f1', value: ['x'], column_name: 'c' }] as any;
    const out = panelFilters(base, panelsFromGroups(GROUPS)[0]);
    expect(out).toHaveLength(2);
    expect(out[0]).toBe(base[0]);
  });

  it('resolves both halves of the Color by control, and only in facet display', () => {
    const groups: GroupRenderState = {
      groups: GROUPS,
      colorByGroup: true,
      display: 'facet',
    };
    expect(panelsForGrouping(groups).map((p) => p.name)).toEqual(['North', 'South']);
    expect(panelsForGrouping({ ...groups, display: 'color' })).toEqual([]);

    const column: GroupRenderState = {
      groups: [],
      colorByGroup: false,
      colorByColumn: { columnName: 'habitat', colorMap: { Soil: '#a', River: '#b' } },
      display: 'facet',
    };
    expect(panelsForGrouping(column).map((p) => p.name)).toEqual(['Soil', 'River']);
    // No palette yet means no known value set, so no split rather than a guess.
    expect(
      panelsForGrouping({ ...column, colorByColumn: { columnName: 'habitat' } }),
    ).toEqual([]);
  });

  describe('the split policy', () => {
    // Every kind in `AdvancedVizKind` (depictio/models/components/types.py),
    // by the bucket it was placed in. The map is typed over the client's copy
    // of that enum, so a kind missing here and there fails to compile; this
    // pins where each one landed.
    const SPLIT = [
      'qq',
      'rarefaction',
      'coverage_track',
      'stacked_taxonomy',
      'sunburst',
      'sankey',
      'oncoplot',
      'signal_matrix',
    ];
    const COLOUR = [
      'embedding',
      'manhattan',
      'scatter_xy',
      'profile',
      'volcano',
      'ma',
      'lollipop',
      'da_barplot',
      'metric_ci_bars',
    ];
    const NONE = [
      'phylogenetic',
      'complex_heatmap',
      'dot_plot',
      'upset_plot',
      'enrichment',
      'pr_benchmark',
      'roc_pr_curve',
      'confusion_matrix',
      'fusion_structure',
      'gene_arrow_track',
      'gsea_running_score',
      'sashimi',
      'contact_map',
      'knee_plot',
      'damage_profile',
      'genome_view',
      'group_compare',
      'transcript_structure',
      'cnv_profile',
      'genome_chord',
      'record_card',
      'parallel_coordinates',
    ];

    it('places every model kind in its bucket, and no kind twice', () => {
      const all = [...SPLIT, ...COLOUR, ...NONE];
      expect(new Set(all).size).toBe(all.length);
      expect(Object.keys(GROUPING_MODE_BY_KIND).sort()).toEqual([...all].sort());
      for (const kind of SPLIT) expect(groupingModeForKind(kind), kind).toBe('split');
      for (const kind of COLOUR) expect(groupingModeForKind(kind), kind).toBe('colour');
      for (const kind of NONE) expect(groupingModeForKind(kind), kind).toBe('none');
    });

    it('splits a kind it has never heard of, as every kind did before', () => {
      expect(groupingModeForKind('some_future_kind')).toBe('split');
      expect(groupingModeForKind('')).toBe('split');
      // Not fooled by names every object inherits.
      expect(groupingModeForKind('constructor')).toBe('split');
    });

    it('reads the legacy differential kind as the bar plot it became', () => {
      expect(groupingModeForKind('ancombc_differentials')).toBe('colour');
    });

    it('deals only split kinds into panels', () => {
      const panels = panelsFromGroups(GROUPS);
      for (const kind of SPLIT) expect(shouldSplitIntoPanels(panels, kind), kind).toBe(true);
      // One shared space, and the lasso groups are drawn with: as read-only
      // panels it could no longer create or refine a group.
      for (const kind of COLOUR) expect(shouldSplitIntoPanels(panels, kind), kind).toBe(false);
      for (const kind of NONE) expect(shouldSplitIntoPanels(panels, kind), kind).toBe(false);
      expect(shouldSplitIntoPanels(panels, 'some_future_kind')).toBe(true);
    });
  });

  it('splits only between two and MAX_PANELS cells', () => {
    const many = Array.from({ length: MAX_PANELS + 1 }, (_, i) => ({ ...GROUPS[0], name: `G${i}` }));
    expect(shouldSplitIntoPanels(panelsFromGroups(GROUPS), 'qq')).toBe(true);
    expect(shouldSplitIntoPanels(panelsFromGroups(GROUPS.slice(0, 1)), 'qq')).toBe(false);
    expect(shouldSplitIntoPanels(panelsFromGroups(many), 'qq')).toBe(false);
  });

  describe('narrowing by an active filter', () => {
    const wide: GroupRenderState = {
      groups: [],
      colorByGroup: false,
      colorByColumn: {
        columnName: 'Phylum',
        colorMap: { Firmicutes: '#a', Bacteroidota: '#b', Proteobacteria: '#c' },
      },
      display: 'facet',
    };
    const select = (value: unknown, column = 'Phylum') =>
      [
        {
          index: 'f1',
          value,
          column_name: column,
          interactive_component_type: 'MultiSelect',
        },
      ] as any;

    it('cuts the cells down to what a categorical filter selects', () => {
      const out = panelsForGrouping(wide, select(['Bacteroidota', 'Firmicutes']));
      // Palette order, not selection order: a value keeps its place and its tint.
      expect(out.map((p) => p.name)).toEqual(['Firmicutes', 'Bacteroidota']);
      expect(out.map((p) => p.color)).toEqual(['#a', '#b']);
    });

    it('reads the column off metadata when the filter carries it there', () => {
      const filters = [
        {
          index: 'f1',
          value: ['Proteobacteria'],
          metadata: { column_name: 'Phylum', interactive_component_type: 'Select' },
        },
      ] as any;
      expect(panelsForGrouping(wide, filters).map((p) => p.name)).toEqual(['Proteobacteria']);
    });

    it('ignores filters on other columns, and ones that name no values', () => {
      expect(panelsForGrouping(wide, select(['Soil'], 'habitat'))).toHaveLength(3);
      expect(panelsForGrouping(wide, select([]))).toHaveLength(3);
      const range = [
        { index: 'f1', value: [0, 1], column_name: 'Phylum', interactive_component_type: 'RangeSlider' },
      ] as any;
      expect(panelsForGrouping(wide, range)).toHaveLength(3);
    });

    it('splits on nothing when the filter names values the palette never saw', () => {
      expect(panelsForGrouping(wide, select(['Chordata']))).toEqual([]);
    });
  });
});
