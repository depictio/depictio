import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from './api';
import { residueRangeFilters } from './selection';
import { groupFromSelectionFilter, selectableSelectionFilters } from './selectionGroups';

describe('selectableSelectionFilters with a residue selection', () => {
  const pair = residueRangeFilters('mol', {
    entityColumn: 'entity',
    positionColumn: 'position',
    entity: 'P1',
    start: 10,
    end: 20,
    dcId: 'dc1',
  });

  it('offers the entity half and never the position span', () => {
    const out = selectableSelectionFilters(pair);
    expect(out).toHaveLength(1);
    expect(out[0].column_name).toBe('entity');
    const group = groupFromSelectionFilter(out[0], 'P1 pick', 'blue');
    expect(group).toMatchObject({ columnName: 'entity', values: ['P1'], dcId: 'dc1' });
  });

  it('keeps the existing sources selectable', () => {
    const scatter: InteractiveFilter = {
      index: 'sc',
      value: ['a'],
      source: 'scatter_selection',
      column_name: 'sample',
    };
    expect(selectableSelectionFilters([scatter, ...pair])).toEqual([scatter, pair[0]]);
  });
});
