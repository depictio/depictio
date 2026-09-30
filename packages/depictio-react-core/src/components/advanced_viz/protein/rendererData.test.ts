import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import {
  chainSelectionFilter,
  entitiesByRowCount,
  entityScopeFilter,
  foreignValuesOn,
  frameLength,
  numberOrNull,
  ownSelectionValues,
  rowIndicesWhere,
  withoutOwnChainPick,
  withoutPositionSelections,
} from './rendererData';

const f = (partial: Partial<InteractiveFilter>): InteractiveFilter =>
  ({ index: 'x', value: [], ...partial }) as InteractiveFilter;

describe('withoutPositionSelections', () => {
  it('drops selection filters on a position column and keeps sidebar ones', () => {
    const filters = [
      f({ index: 'a::res', source: 'residue_selection', column_name: 'position', value: [3, 9] }),
      f({ index: 'a', source: 'residue_selection', column_name: 'entity', value: ['P1'] }),
      f({ index: 'side', column_name: 'position', value: [1, 50] }),
      f({ index: 'b', source: 'scatter_selection', metadata: { column_name: 'position' }, value: [7] }),
    ];
    const kept = withoutPositionSelections(filters, ['position', null]);
    expect(kept.map((k) => k.index)).toEqual(['a', 'side']);
  });
});

describe('selection readers', () => {
  const filters = [
    f({ index: 'msa', source: 'scatter_selection', value: ['s1', 's2'] }),
    f({ index: 'table', column_name: 'seq_id', value: ['s9'] }),
    f({ index: 'msa', column_name: 'seq_id', source: 'residue_selection', value: ['ignored'] }),
  ];

  it("reads a component's own scatter selection", () => {
    expect(ownSelectionValues(filters, 'msa')).toEqual(['s1', 's2']);
    expect(ownSelectionValues(filters, 'other')).toEqual([]);
  });

  it('reads what other components picked on a column', () => {
    expect(foreignValuesOn(filters, 'msa', 'seq_id')).toEqual(['s9']);
  });
});

describe('entityScopeFilter', () => {
  it('is a plain one-value MultiSelect keyed off the tile', () => {
    const out = entityScopeFilter('t1', 'dc', 'msa_id', 'P04637');
    expect(out).toMatchObject({
      index: 't1::scope',
      value: ['P04637'],
      column_name: 'msa_id',
      interactive_component_type: 'MultiSelect',
    });
    expect(out.source).toBeUndefined();
  });
});

describe('frames', () => {
  const frame = { entity: ['A', 'B', 'A'], position: [1, 2, 3] };

  it('counts and filters rows by value', () => {
    expect(frameLength(frame)).toBe(3);
    expect(frameLength(null)).toBe(0);
    expect(rowIndicesWhere(frame, 'entity', 'A')).toEqual([0, 2]);
    expect(rowIndicesWhere(frame, 'missing', 'A')).toEqual([0, 1, 2]);
    expect(rowIndicesWhere(frame, 'entity', null)).toEqual([0, 1, 2]);
  });

  it('parses numbers strictly', () => {
    expect(numberOrNull('4')).toBe(4);
    expect(numberOrNull('')).toBeNull();
    expect(numberOrNull('abc')).toBeNull();
  });
});

describe('chainSelectionFilter / withoutOwnChainPick', () => {
  it('names the chain of a complex pick and clears with an empty value', () => {
    const pick = chainSelectionFilter('m', 'dc1', 'chain', 'B');
    expect(pick).toMatchObject({
      index: 'm::chain',
      value: ['B'],
      source: 'residue_selection',
      column_name: 'chain',
      interactive_component_type: 'MultiSelect',
    });
    expect(chainSelectionFilter('m', 'dc1', 'chain', null).value).toEqual([]);
  });

  it('drops only the tile own chain pick', () => {
    const own = chainSelectionFilter('m', 'dc1', 'chain', 'B');
    const other = chainSelectionFilter('msa', 'dc2', 'chain', 'A');
    const sidebar = f({ index: 'side', column_name: 'chain', value: ['A'] });
    expect(withoutOwnChainPick([own, other, sidebar], 'm')).toEqual([other, sidebar]);
  });
});

describe('entitiesByRowCount', () => {
  it('puts the entity with the most rows first, ties in first-appearance order', () => {
    expect(entitiesByRowCount(['B', 'A', 'C', 'A', null, '', 'C', 'A'])).toEqual(['A', 'C', 'B']);
    expect(entitiesByRowCount(['Q2', 'Q1'])).toEqual(['Q2', 'Q1']);
    expect(entitiesByRowCount([])).toEqual([]);
  });
});
