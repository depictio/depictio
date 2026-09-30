import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from './api';
import {
  cardScopedFilters,
  chainSelectionFilterIndex,
  clearedSelectionFilters,
  filtersExcludingOwnResidue,
  mergeFiltersBySource,
  ownSelection,
  residueEntityFromFilters,
  residueRangeFilters,
  residueRangeFromFilters,
} from './selection';
import { chainSelectionFilter } from './components/advanced_viz/protein/rendererData';

const pick = (start: number | null, end?: number, entity: string | null = 'P1') =>
  residueRangeFilters('mol', {
    entityColumn: 'entity',
    positionColumn: 'position',
    entity,
    start,
    end,
    dcId: 'dc1',
  });

const apply = (filters: InteractiveFilter[], next: InteractiveFilter[]) =>
  next.reduce(mergeFiltersBySource, filters);

describe('residueRangeFilters', () => {
  it('emits an entity multi-select and an inclusive position range', () => {
    const [ent, range] = pick(12, 30);
    expect(ent).toMatchObject({
      index: 'mol',
      value: ['P1'],
      source: 'residue_selection',
      column_name: 'entity',
      interactive_component_type: 'MultiSelect',
      metadata: { dc_id: 'dc1', column_name: 'entity' },
    });
    expect(range).toMatchObject({
      index: 'mol::res',
      value: [12, 30],
      source: 'residue_selection',
      column_name: 'position',
      interactive_component_type: 'RangeSlider',
    });
  });

  it('treats a missing end as a single residue and orders a reversed range', () => {
    expect(pick(7)[1].value).toEqual([7, 7]);
    expect(pick(30, 12)[1].value).toEqual([12, 30]);
  });

  it('emits the range half alone without an entity column', () => {
    const out = residueRangeFilters('seq', { positionColumn: 'pos', start: 3, end: 4 });
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ index: 'seq::res', column_name: 'pos', value: [3, 4] });
  });

  it('replaces the residue pick another tile made on the same columns (last gesture wins)', () => {
    const fromMol = apply([], pick(22));
    const fromMsa = apply(
      fromMol,
      residueRangeFilters('msa', { entityColumn: 'entity', positionColumn: 'position', entity: 'P1', start: 40, end: 70 }),
    );
    expect(fromMsa.map((f) => f.index)).toEqual(['msa', 'msa::res']);
    expect(fromMsa[1].value).toEqual([40, 70]);
  });

  it('keeps a residue pick on other columns and every non-residue filter', () => {
    const sidebar: InteractiveFilter = { index: 'side', value: [1, 5], column_name: 'position' };
    const other = residueRangeFilters('seq', { positionColumn: 'aa_pos', start: 3, end: 4 });
    const out = apply(apply([sidebar], other), pick(22));
    expect(out.map((f) => f.index)).toEqual(['side', 'seq::res', 'mol', 'mol::res']);
  });

  it('clears both halves with start null, which mergeFiltersBySource drops', () => {
    const set = apply([], pick(12, 30));
    expect(set).toHaveLength(2);
    const cleared = pick(null);
    expect(cleared.map((f) => f.value)).toEqual([[], []]);
    expect(apply(set, cleared)).toEqual([]);
  });
});

describe('residueRangeFromFilters', () => {
  it('round-trips a tile pick', () => {
    expect(residueRangeFromFilters(pick(12, 30), 'entity', 'position')).toEqual({
      entity: 'P1',
      start: 12,
      end: 30,
    });
  });

  it('reads any source by column name, a sidebar slider included', () => {
    const sidebar: InteractiveFilter[] = [
      { index: 'side1', value: ['P9'], column_name: 'entity' },
      { index: 'side2', value: [5, 9], metadata: { column_name: 'position' } },
    ];
    expect(residueRangeFromFilters(sidebar, 'entity', 'position')).toEqual({
      entity: 'P9',
      start: 5,
      end: 9,
    });
  });

  it('ignores other column names', () => {
    expect(residueRangeFromFilters(pick(12, 30), 'protein', 'resnum')).toBeNull();
  });

  it('returns null without a range and when several entities are named', () => {
    expect(residueRangeFromFilters(pick(12, 30).slice(0, 1), 'entity', 'position')).toBeNull();
    const two: InteractiveFilter[] = [
      { index: 'side', value: ['A', 'B'], column_name: 'entity' },
      pick(1, 2)[1],
    ];
    expect(residueRangeFromFilters(two, 'entity', 'position')).toBeNull();
  });

  it('gives a null entity when no filter names one', () => {
    expect(residueRangeFromFilters([pick(3, 4)[1]], 'entity', 'position')).toEqual({
      entity: null,
      start: 3,
      end: 4,
    });
  });

  it('intersects several ranges on the position column', () => {
    const filters = [pick(10, 40)[1], { index: 'side', value: [20, 60], column_name: 'position' }];
    expect(residueRangeFromFilters(filters, null, 'position')).toEqual({
      entity: null,
      start: 20,
      end: 40,
    });
    const disjoint = [pick(1, 5)[1], { index: 'side', value: [10, 20], column_name: 'position' }];
    expect(residueRangeFromFilters(disjoint, null, 'position')).toBeNull();
  });
});

describe('residueEntityFromFilters', () => {
  it('names one entity or none', () => {
    expect(residueEntityFromFilters(pick(1, 2), 'entity')).toBe('P1');
    expect(residueEntityFromFilters([{ index: 'x', value: ['A', 'B'], column_name: 'entity' }], 'entity')).toBeNull();
    expect(residueEntityFromFilters(pick(1, 2), null)).toBeNull();
    expect(residueEntityFromFilters([{ index: 'x', value: 'Q', column_name: 'entity' }], 'entity')).toBe('Q');
  });
});

describe('residue selection in the shared selection helpers', () => {
  const other: InteractiveFilter = { index: 'side', value: ['s1'], column_name: 'sample' };

  it('filtersExcludingOwnResidue drops both own halves only', () => {
    const mine = pick(1, 2);
    const theirs = residueRangeFilters('msa', { entityColumn: 'entity', positionColumn: 'position', entity: 'P1', start: 5 });
    const out = filtersExcludingOwnResidue([...mine, ...theirs, other], 'mol');
    expect(out).toEqual([...theirs, other]);
  });

  it('ownSelection counts the pick and clears through clearedSelectionFilters', () => {
    const filters = [...pick(1, 2), other];
    const own = ownSelection(filters, 'mol');
    expect(own.filters).toHaveLength(2);
    expect(own.count).toBe(1);
    expect(apply(filters, clearedSelectionFilters(own.filters))).toEqual([other]);
  });

  it('ownSelection takes the chain half of a pick on a complex, and clearing drops it', () => {
    const chain = chainSelectionFilter('mol', 'dc1', 'chain', 'B');
    const theirs = chainSelectionFilter('msa', 'dc1', 'chain', 'A');
    expect(ownSelection([...pick(1, 2), theirs], 'mol').filters).not.toContain(theirs);
    const filters = [...pick(1, 2), chain, other];
    const own = ownSelection(filters, 'mol');
    expect(own.filters.map((f) => f.index)).toEqual(['mol', 'mol::res', chainSelectionFilterIndex('mol')]);
    expect(own.count).toBe(1);
    expect(apply(filters, clearedSelectionFilters(own.filters))).toEqual([other]);
    // A chain pick left on its own is still something to clear.
    expect(ownSelection([chain], 'mol')).toEqual({ filters: [chain], count: 1 });
  });

  it('ownSelection counts a range with no entity half as one selection', () => {
    const f = residueRangeFilters('seq', { positionColumn: 'position', start: 3 });
    expect(ownSelection(f, 'seq').count).toBe(1);
  });

  it('cards ignore a residue range unless they follow the region filter', () => {
    const filters = [...pick(1, 2), other];
    expect(cardScopedFilters(filters, {})).toEqual([other]);
    expect(cardScopedFilters(filters, { follow_region_filter: true })).toBe(filters);
  });
});
