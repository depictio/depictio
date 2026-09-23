import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import { honouredSelectionSources, readRecordSelection } from './recordSelection';

const scatter = (values: unknown[], dcId = 'dc-1'): InteractiveFilter => ({
  index: 'tile-a',
  value: values,
  source: 'scatter_selection',
  column_name: 'sample',
  interactive_component_type: 'MultiSelect',
  metadata: { dc_id: dcId, column_name: 'sample', selection_column: 'sample' },
});

const table = (values: unknown[], dcId = 'dc-1'): InteractiveFilter => ({
  index: 'tile-b',
  value: values,
  source: 'table_selection',
  column_name: 'run',
  metadata: { dc_id: dcId, column_name: 'run' },
});

describe('honouredSelectionSources', () => {
  it('takes both sources for "any" and for an unset value', () => {
    expect(honouredSelectionSources('any')).toEqual(['scatter_selection', 'table_selection']);
    expect(honouredSelectionSources(undefined)).toEqual([
      'scatter_selection',
      'table_selection',
    ]);
  });

  it('narrows to the named source', () => {
    expect(honouredSelectionSources('table_selection')).toEqual(['table_selection']);
  });
});

describe('readRecordSelection', () => {
  it('returns null when nothing is selected', () => {
    expect(readRecordSelection([], { dcId: 'dc-1' })).toBeNull();
    expect(readRecordSelection(undefined, { dcId: 'dc-1' })).toBeNull();
  });

  it('ignores a cleared selection and ordinary filters', () => {
    const plain: InteractiveFilter = { index: 'slider', value: [1, 9], column_name: 'reads' };
    expect(readRecordSelection([scatter([]), plain], { dcId: 'dc-1' })).toBeNull();
  });

  it('reads the values and the column of the honoured selection', () => {
    expect(readRecordSelection([scatter(['S1', 'S2'])], { dcId: 'dc-1' })).toEqual({
      source: 'scatter_selection',
      column: 'sample',
      values: ['S1', 'S2'],
      ownCollection: true,
    });
  });

  it('honours only the named source', () => {
    const filters = [scatter(['S1']), table(['R9'])];
    expect(
      readRecordSelection(filters, { dcId: 'dc-1', selectionSource: 'table_selection' })?.values,
    ).toEqual(['R9']);
  });

  it('prefers a pick on the card own collection over a linked one', () => {
    const filters = [scatter(['S1'], 'dc-other'), table(['R9'], 'dc-1')];
    const picked = readRecordSelection(filters, { dcId: 'dc-1' });
    expect(picked?.source).toBe('table_selection');
    expect(picked?.ownCollection).toBe(true);
  });

  it('still follows a pick that has to travel through a link', () => {
    const picked = readRecordSelection([scatter(['S1'], 'dc-other')], { dcId: 'dc-1' });
    expect(picked?.values).toEqual(['S1']);
    expect(picked?.ownCollection).toBe(false);
  });
});
