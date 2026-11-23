import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import {
  chainSelectionFilter,
  chooseEntity,
  entitiesByRowCount,
  entityScopeFilter,
  foreignValuesOn,
  frameLength,
  heldEntities,
  numberOrNull,
  ownSelectionValues,
  rowIndicesWhere,
  withoutFiltersOn,
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

describe('withoutFiltersOn', () => {
  const filters = [
    f({ index: 'side', column_name: 'position', value: [30, 100] }),
    f({ index: 'a::res', source: 'residue_selection', column_name: 'position', value: [3, 9] }),
    f({ index: 'nested', source: 'scatter_selection', metadata: { column_name: 'chain' }, value: ['A'] }),
    f({ index: 'chain-side', column_name: 'chain', value: ['B'] }),
    f({ index: 'ent', column_name: 'entity', value: ['P1'] }),
    f({ index: 'bare', value: ['x'] }),
  ];

  it('drops every filter on the columns, sidebar or selection, top-level or nested', () => {
    const kept = withoutFiltersOn(filters, ['position', 'chain']);
    expect(kept.map((k) => k.index)).toEqual(['ent', 'bare']);
  });

  it('keeps what withoutPositionSelections keeps, minus the sidebar filter on the column', () => {
    const viaSelections = withoutPositionSelections(filters, ['position']);
    expect(viaSelections.map((k) => k.index)).toContain('side');
    const viaColumns = withoutFiltersOn(viaSelections, ['position']);
    expect(viaColumns.map((k) => k.index)).not.toContain('side');
    expect(viaColumns.map((k) => k.index)).toEqual(['nested', 'chain-side', 'ent', 'bare']);
  });

  it('ignores unset roles and returns the filters whole when no column is named', () => {
    expect(withoutFiltersOn(filters, [null, undefined, ''])).toEqual(filters);
    expect(withoutFiltersOn(filters, [])).toEqual(filters);
  });

  it('does not touch its input', () => {
    const copy = [...filters];
    withoutFiltersOn(filters, ['position']);
    expect(filters).toEqual(copy);
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

describe('heldEntities / chooseEntity (#1418)', () => {
  // The model list stopped at 1,000 of 4,333 families: the family the sidebar
  // picked was not in it, so the logo fell back to the list's first family and
  // ANDed it with the picked one into an empty fetch.
  const cut = Array.from({ length: 1000 }, (_, i) => `bu_proteins_${i + 1}`);

  it('keeps the opening entity a cut list leaves out', () => {
    const held = heldEntities(cut, 'bu_proteins_3052');
    expect(held).toContain('bu_proteins_3052');
    expect(held).toHaveLength(1001);
    expect(chooseEntity(held, null, 'bu_proteins_3052')).toBe('bu_proteins_3052');
  });

  it('sorts the added entity in natural order and does not duplicate a listed one', () => {
    expect(heldEntities(['a_2', 'a_10'], 'a_3')).toEqual(['a_2', 'a_3', 'a_10']);
    expect(heldEntities(['a_2', 'a_10'], 'a_2')).toEqual(['a_2', 'a_10']);
    expect(heldEntities(null, 'a_2')).toBeNull();
  });

  it('prefers the reader pick, then the agreed one, then the first held', () => {
    const held = ['a', 'b', 'c'];
    expect(chooseEntity(held, 'c', 'b')).toBe('c');
    expect(chooseEntity(held, 'z', 'b')).toBe('b');
    expect(chooseEntity(held, null, 'z')).toBe('a');
    expect(chooseEntity([], 'a', 'a')).toBeNull();
    expect(chooseEntity(null, 'a', 'a')).toBeNull();
  });
});

describe('chooseEntity with the entities in scope (#1418)', () => {
  const held = ['fam_1', 'fam_2', 'fam_3'];

  it('drops a reader pick the dashboard filters no longer leave', () => {
    // The reader picked fam_1 in the tile, then fam_3 on the sidebar.
    expect(chooseEntity(held, 'fam_1', 'fam_3', new Set(['fam_3']))).toBe('fam_3');
  });

  it('keeps a pick still in scope, and any pick when the scope is unknown', () => {
    expect(chooseEntity(held, 'fam_1', 'fam_3', new Set(['fam_1', 'fam_3']))).toBe('fam_1');
    expect(chooseEntity(held, 'fam_1', 'fam_3', null)).toBe('fam_1');
  });
});
