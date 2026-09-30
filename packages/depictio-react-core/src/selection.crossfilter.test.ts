import { describe, expect, it } from 'vitest';

import type { InteractiveFilter, StoredMetadata } from './api';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filtersForSelector,
  mergeFiltersBySource,
  residueRangeFilters,
  valuesOnColumn,
} from './selection';

const scatter = {
  index: 'sc',
  dc_id: 'dc_scores',
  component_type: 'advanced_viz',
  viz_kind: 'scatter_xy',
  config: { x_col: 'x', y_col: 'y', selection_enabled: true, selection_column: 'entity' },
} as unknown as StoredMetadata;

const residuePick = (entity: string) =>
  residueRangeFilters('mol', {
    entityColumn: 'entity',
    positionColumn: 'position',
    entity,
    start: 10,
    end: 12,
    dcId: 'dc_residues',
  });

const sidebar = (column: string, value: unknown): InteractiveFilter => ({
  index: `side-${column}`,
  value,
  column_name: column,
  interactive_component_type: 'MultiSelect',
  metadata: { dc_id: 'dc_scores', column_name: column, interactive_component_type: 'MultiSelect' },
});

describe('filtersForSelector (crossfilter rule)', () => {
  const column = advancedVizSelectionColumn(scatter);

  it('resolves the scatter selection column', () => {
    expect(column).toBe('entity');
  });

  it('drops the tile own selection and every filter on its selection column', () => {
    const own = advancedVizSelectionFilter(scatter, 'entity', ['A']);
    const filters = [own, ...residuePick('B'), sidebar('entity', ['C'])];
    const kept = filtersForSelector(filters, 'sc', 'scatter_selection', column);
    // Only the position half of the residue pick survives (a column the
    // scatter does not select on).
    expect(kept).toHaveLength(1);
    expect(kept[0].column_name).toBe('position');
  });

  it('keeps filters on other columns narrowing the tile', () => {
    const filters = [sidebar('engine', ['alphafold2']), ...residuePick('B')];
    const kept = filtersForSelector(filters, 'sc', 'scatter_selection', column);
    expect(kept.map((f) => f.column_name).sort()).toEqual(['engine', 'position']);
  });

  it('is filtersExcludingOwn without a selection column', () => {
    const own = advancedVizSelectionFilter(scatter, 'entity', ['A']);
    const filters = [own, sidebar('entity', ['C'])];
    expect(filtersForSelector(filters, 'sc', 'scatter_selection', undefined)).toEqual([
      filters[1],
    ]);
  });

  it('still lets another tile be narrowed by the scatter pick', () => {
    // The rule only concerns the selector itself: the 3D tile reads the same
    // filter list and sees the scatter's pick on `entity`.
    const own = advancedVizSelectionFilter(scatter, 'entity', ['A']);
    const forOther = filtersForSelector([own], 'mol', 'scatter_selection', 'position');
    expect(forOther).toEqual([own]);
  });
});

describe('valuesOnColumn', () => {
  it('collects the values every source names on the column', () => {
    const own = advancedVizSelectionFilter(scatter, 'entity', ['A']);
    const filters = [own, ...residuePick('B'), sidebar('entity', 'C'), sidebar('engine', ['x'])];
    expect(Array.from(valuesOnColumn(filters, 'entity')).sort()).toEqual(['A', 'B', 'C']);
  });

  it('skips the excluded entry and cleared filters', () => {
    const own = advancedVizSelectionFilter(scatter, 'entity', ['A']);
    const cleared = advancedVizSelectionFilter({ ...scatter, index: 'other' }, 'entity', []);
    const filters = [own, cleared, ...residuePick('B')];
    const values = valuesOnColumn(filters, 'entity', { index: 'sc', source: 'scatter_selection' });
    expect(Array.from(values)).toEqual(['B']);
    expect(valuesOnColumn(filters, null).size).toBe(0);
  });

  it('round-trips a clear: the emptied own entry names nothing', () => {
    let filters: InteractiveFilter[] = [advancedVizSelectionFilter(scatter, 'entity', ['A'])];
    filters = mergeFiltersBySource(filters, advancedVizSelectionFilter(scatter, 'entity', []));
    expect(valuesOnColumn(filters, 'entity').size).toBe(0);
  });
});
