import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import { residueRangeFilters } from '../../../selection';
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
  it('takes every source for "any" and for an unset value', () => {
    const all = ['scatter_selection', 'table_selection', 'residue_selection'];
    expect(honouredSelectionSources('any')).toEqual(all);
    expect(honouredSelectionSources(undefined)).toEqual(all);
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

describe('readRecordSelection with a linked component', () => {
  it('follows only the linked tile, whatever the configured source', () => {
    const filters = [scatter(['S1']), table(['R1'])];
    expect(
      readRecordSelection(filters, {
        dcId: 'dc-1',
        selectionSource: 'scatter_selection',
        linkedIndex: 'tile-b',
      })?.values,
    ).toEqual(['R1']);
    expect(readRecordSelection([scatter(['S1'])], { linkedIndex: 'tile-b' })).toBeNull();
  });
});

describe('readRecordSelection with a residue pick', () => {
  const pick = (start: number, end: number, entity: string | null = 'P1', dcId = 'dc-var') =>
    residueRangeFilters('mol', {
      entityColumn: entity === null ? null : 'entity',
      positionColumn: 'position',
      entity,
      start,
      end,
      dcId,
    });

  it('reads the pair as one selection on the entity', () => {
    expect(readRecordSelection(pick(10, 20), { dcId: 'dc-var' })).toEqual({
      source: 'residue_selection',
      column: 'entity',
      values: ['P1'],
      ownCollection: true,
    });
  });

  it('matches on the spanned positions when there is no entity half', () => {
    const picked = readRecordSelection(pick(3, 5, null), { dcId: 'dc-var' });
    expect(picked).toMatchObject({ column: 'position', values: ['3', '4', '5'] });
  });

  it('follows the linked protein tile through both halves', () => {
    const filters = [scatter(['S1']), ...pick(10, 20)];
    expect(readRecordSelection(filters, { dcId: 'dc-var', linkedIndex: 'mol' })?.source).toBe(
      'residue_selection',
    );
    expect(readRecordSelection(pick(10, 20), { linkedIndex: 'other' })).toBeNull();
  });

  it('is not followed when the card names another source', () => {
    expect(
      readRecordSelection(pick(10, 20), { dcId: 'dc-var', selectionSource: 'scatter_selection' }),
    ).toBeNull();
  });

  it('ignores a cleared pick', () => {
    const cleared = residueRangeFilters('mol', {
      entityColumn: 'entity',
      positionColumn: 'position',
      start: null,
    });
    expect(readRecordSelection(cleared, { dcId: 'dc-var' })).toBeNull();
  });
});
