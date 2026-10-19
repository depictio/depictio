import { describe, expect, it } from 'vitest';

import type { InteractiveFilter, StoredMetadata } from './api';
import {
  advancedVizChromeReset,
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  isSourceFilterActive,
  mapSelectionValues,
  mergeFiltersBySource,
  selectionValuesFor,
  supportsSelectionGrouping,
} from './selection';

const upset = (config: Record<string, unknown>): StoredMetadata =>
  ({
    index: 'adv-upset',
    component_type: 'advanced_viz',
    viz_kind: 'upset_plot',
    dc_id: 'dc-upset',
    config: { viz_kind: 'upset_plot', ...config },
  }) as unknown as StoredMetadata;

describe('the UpSet as a selection source', () => {
  it('selects on the column it names, and only once opted in', () => {
    expect(advancedVizSelectionColumn(upset({ selection_enabled: true, selection_column: 'Phylum' }))).toBe('Phylum');
    expect(advancedVizSelectionColumn(upset({ selection_column: 'Phylum' }))).toBeUndefined();
    // No fallback: nothing else in its config names what an intersection holds.
    expect(advancedVizSelectionColumn(upset({ selection_enabled: true }))).toBeUndefined();
  });

  it('is offered for analysis groups like the other selection sources', () => {
    const on = upset({ selection_enabled: true, selection_column: 'Phylum' });
    expect(supportsSelectionGrouping(on, true)).toBe(true);
    expect(supportsSelectionGrouping(on, false)).toBe(false);
  });

  it('emits a scatter_selection on its column, from its own collection', () => {
    const f = advancedVizSelectionFilter(upset({}), 'Phylum', ['Fungi']);
    expect(f).toMatchObject({
      index: 'adv-upset',
      source: 'scatter_selection',
      column_name: 'Phylum',
      value: ['Fungi'],
      metadata: { dc_id: 'dc-upset', column_name: 'Phylum' },
    });
  });

  it('gets the chrome Reset, which the scatter kinds do not', () => {
    expect(advancedVizChromeReset(upset({ selection_enabled: true, selection_column: 'Phylum' }))).toBe(true);
    expect(advancedVizChromeReset(upset({}))).toBe(false);
    const embedding = {
      index: 'emb',
      viz_kind: 'embedding',
      config: { selection_enabled: true, sample_id_col: 'sample' },
    } as unknown as StoredMetadata;
    expect(advancedVizSelectionColumn(embedding)).toBe('sample');
    expect(advancedVizChromeReset(embedding)).toBe(false);
  });
});

describe('reading a selection back out of the filter list', () => {
  const filters: InteractiveFilter[] = [
    { index: 'adv-upset', source: 'scatter_selection', value: ['Fungi', 'Metazoa'] },
    { index: 'adv-upset', value: ['ignored: not a selection'] },
    { index: 'map', source: 'map_selection', value: ['S1'] },
  ];

  it('finds the component own values for the source', () => {
    expect(selectionValuesFor(filters, 'adv-upset', 'scatter_selection')).toEqual(['Fungi', 'Metazoa']);
    expect(selectionValuesFor(filters, 'adv-upset', 'table_selection')).toBeNull();
    expect(mapSelectionValues(filters, 'map')).toEqual(['S1']);
    expect(mapSelectionValues(filters, 'adv-upset')).toEqual([]);
  });

  it('treats a cleared selection as none', () => {
    const cleared = [{ index: 'adv-upset', source: 'scatter_selection' as const, value: [] }];
    expect(selectionValuesFor(cleared, 'adv-upset', 'scatter_selection')).toBeNull();
    expect(isSourceFilterActive(cleared, 'adv-upset', 'scatter_selection')).toBe(false);
    expect(isSourceFilterActive(filters, 'adv-upset', 'scatter_selection')).toBe(true);
  });

  it('is gone once the empty selection a second click emits is merged', () => {
    const next = mergeFiltersBySource(filters, advancedVizSelectionFilter(upset({}), 'Phylum', []));
    expect(selectionValuesFor(next, 'adv-upset', 'scatter_selection')).toBeNull();
    expect(next).toHaveLength(2);
  });
});

const alleleGrid = (config: Record<string, unknown>): StoredMetadata =>
  ({
    index: 'adv-alleles',
    component_type: 'advanced_viz',
    viz_kind: 'allele_grid',
    dc_id: 'dc-hla',
    config: { viz_kind: 'allele_grid', ...config },
  }) as unknown as StoredMetadata;

describe('the allele grid as a selection source', () => {
  it('selects on the allele column once opted in, and on a named column over it', () => {
    expect(advancedVizSelectionColumn(alleleGrid({ allele_col: 'hla_allele' }))).toBeUndefined();
    expect(
      advancedVizSelectionColumn(alleleGrid({ selection_enabled: true, allele_col: 'hla_allele' })),
    ).toBe('hla_allele');
    expect(advancedVizSelectionColumn(alleleGrid({ selection_enabled: true }))).toBe('allele');
    expect(
      advancedVizSelectionColumn(
        alleleGrid({ selection_enabled: true, allele_col: 'hla_allele', selection_column: 'allele4' }),
      ),
    ).toBe('allele4');
  });

  it('gets the chrome Reset, since it repaints its picks from the filter list', () => {
    expect(advancedVizChromeReset(alleleGrid({ selection_enabled: true }))).toBe(true);
    expect(advancedVizChromeReset(alleleGrid({}))).toBe(false);
  });

  it('emits an allele pick and a sample pick on the same filter key', () => {
    const md = alleleGrid({ selection_enabled: true });
    const byAllele = advancedVizSelectionFilter(md, 'allele', ['A*02:01']);
    const bySample = advancedVizSelectionFilter(md, 'sample_id', ['DONOR_07']);
    expect(byAllele).toMatchObject({ index: 'adv-alleles', source: 'scatter_selection', column_name: 'allele' });
    expect(bySample).toMatchObject({ index: 'adv-alleles', source: 'scatter_selection', column_name: 'sample_id' });
    const merged = mergeFiltersBySource(mergeFiltersBySource([], byAllele), bySample);
    expect(merged).toHaveLength(1);
    expect(merged[0].column_name).toBe('sample_id');
  });
});
