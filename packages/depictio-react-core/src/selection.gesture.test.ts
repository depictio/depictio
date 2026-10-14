import { describe, expect, it } from 'vitest';

import type { InteractiveFilter, StoredMetadata } from './api';
import {
  advancedVizSelectionFilter,
  clearedSelectionFilters,
  mergeFiltersBySource,
  ownSelection,
  pairedWithResiduePick,
  residueEntityFromFilters,
  residueRangeFilters,
  residueRangeFromFilters,
} from './selection';
import { chainSelectionFilter } from './components/advanced_viz/protein/rendererData';

// "Last gesture wins" for the whole gesture: a residue pick replaces the
// residue pick of another tile together with what that tile emitted in the
// same gesture (its chain half, the label of a domain), and nothing else.

const apply = (filters: InteractiveFilter[], next: InteractiveFilter[]) =>
  next.reduce(mergeFiltersBySource, filters);

const pick = (
  index: string,
  entity: string | null,
  start: number | null,
  end?: number,
  columns: { entity?: string; position?: string } = {},
) =>
  residueRangeFilters(index, {
    entityColumn: columns.entity ?? 'entity',
    positionColumn: columns.position ?? 'position',
    entity,
    start,
    end,
    dcId: 'dc',
  });

const tile = (index: string): StoredMetadata =>
  ({ index, dc_id: 'dc', component_type: 'advanced_viz' }) as unknown as StoredMetadata;

/** A domain click as `DomainArchitectureRenderer` emits it: the span, then
 *  the domain's label paired with it. */
const domainClick = (entity: string, start: number, end: number, label: string) => [
  ...pick('fam-arch', entity, start, end),
  pairedWithResiduePick(advancedVizSelectionFilter(tile('fam-arch'), 'label', [label])),
];

/** A pick on a complex as the 3D, PAE and Ramachandran tiles emit it: the
 *  pair, then the chain. */
const complexPick = (index: string, entity: string, start: number, end: number, chain: string) => [
  ...pick(index, entity, start, end),
  chainSelectionFilter(index, 'dc', 'chain', chain),
];

const shape = (filters: InteractiveFilter[]) =>
  filters.map((f) => [f.index, f.source ?? null, f.column_name, f.value]);

describe('a residue pick replaces the whole gesture of the tile it supersedes', () => {
  it('a 3D click drops the domain label picked with the replaced domain', () => {
    let filters = apply([], domainClick('P7', 110, 170, 'DemoFamB'));
    expect(residueEntityFromFilters(filters, 'label')).toBe('DemoFamB');

    filters = apply(filters, pick('fam-3d', 'demo_protein', 40, 40));
    expect(shape(filters)).toEqual([
      ['fam-3d', 'residue_selection', 'entity', ['demo_protein']],
      ['fam-3d::res', 'residue_selection', 'position', [40, 40]],
    ]);
    // The logo no longer follows DemoFamB and the hits table is no longer
    // narrowed to it; residue 40 is the pick everyone reads.
    expect(residueEntityFromFilters(filters, 'label')).toBeNull();
    expect(residueRangeFromFilters(filters, 'entity', 'position')).toEqual({
      entity: 'demo_protein',
      start: 40,
      end: 40,
    });
  });

  it('a pick in the secondary structure drops the chain of the PAE pick it replaces', () => {
    let filters = apply([], complexPick('pae', 'X', 10, 20, 'B'));
    filters = apply(filters, pick('ss', 'Z', 5, 5));
    expect(shape(filters)).toEqual([
      ['ss', 'residue_selection', 'entity', ['Z']],
      ['ss::res', 'residue_selection', 'position', [5, 5]],
    ]);
  });

  it('a pick on a complex after another complex pick keeps only the new chain', () => {
    let filters = apply([], complexPick('rama', 'cx', 10, 20, 'B'));
    filters = apply(filters, complexPick('mol', 'cx', 30, 30, 'A'));
    expect(shape(filters)).toEqual([
      ['mol', 'residue_selection', 'entity', ['cx']],
      ['mol::res', 'residue_selection', 'position', [30, 30]],
      ['mol::chain', 'residue_selection', 'chain', ['A']],
    ]);
  });

  it('drops the replaced tile whole when only one column is shared', () => {
    // The old pick names its protein on another column: only the position
    // range collides, and the protein half goes with it.
    let filters = apply([], pick('lolli', 'GENE1', 3, 3, { entity: 'gene' }));
    filters = apply(filters, pick('mol', 'P1', 8, 9));
    expect(filters.map((f) => f.index)).toEqual(['mol', 'mol::res']);
  });

  it('a gene pick elsewhere drops the paired label with the pick it leaves behind', () => {
    let filters = apply([], domainClick('P7', 110, 170, 'DemoFamB'));
    const scatter = advancedVizSelectionFilter(tile('sc'), 'entity', ['P9']);
    filters = mergeFiltersBySource(filters, scatter);
    expect(filters).toEqual([scatter]);
  });
});

describe('a tile starting a new pick drops what its previous gesture left', () => {
  it('a pick on another entity does not keep the chain of the complex', () => {
    // The single-chain protein emits no chain half (`multiChain` is false).
    let filters = apply([], complexPick('mol', 'complex', 10, 20, 'B'));
    filters = apply(filters, pick('mol', 'monomer', 5, 5));
    expect(shape(filters)).toEqual([
      ['mol', 'residue_selection', 'entity', ['monomer']],
      ['mol::res', 'residue_selection', 'position', [5, 5]],
    ]);
  });

  it('a new pick on the complex keeps its own new chain', () => {
    let filters = apply([], complexPick('mol', 'complex', 10, 20, 'B'));
    filters = apply(filters, complexPick('mol', 'complex', 40, 41, 'A'));
    expect(shape(filters)).toEqual([
      ['mol', 'residue_selection', 'entity', ['complex']],
      ['mol::res', 'residue_selection', 'position', [40, 41]],
      ['mol::chain', 'residue_selection', 'chain', ['A']],
    ]);
  });

  it('another domain replaces the label, a protein name drops it', () => {
    let filters = apply([], domainClick('P7', 110, 170, 'DemoFamB'));
    filters = apply(filters, domainClick('P7', 10, 60, 'DemoFamA'));
    expect(residueEntityFromFilters(filters, 'label')).toBe('DemoFamA');
    expect(filters).toHaveLength(3);
    // A protein name click is a span with no label.
    filters = apply(filters, pick('fam-arch', 'P7', 1, 300));
    expect(filters.map((f) => f.index)).toEqual(['fam-arch', 'fam-arch::res']);
    expect(residueEntityFromFilters(filters, 'label')).toBeNull();
  });

  it('the chain half itself does not drop the selection paired with the pair', () => {
    let filters = apply([], domainClick('P7', 110, 170, 'DemoFamB'));
    filters = mergeFiltersBySource(filters, chainSelectionFilter('fam-arch', 'dc', 'chain', 'A'));
    expect(filters.map((f) => [f.index, f.source])).toEqual([
      ['fam-arch', 'residue_selection'],
      ['fam-arch::res', 'residue_selection'],
      ['fam-arch', 'scatter_selection'],
      ['fam-arch::chain', 'residue_selection'],
    ]);
  });
});

describe('selections that are not part of the replaced gesture stay', () => {
  const sidebarChain: InteractiveFilter = {
    index: 'side-chain',
    value: ['B'],
    column_name: 'chain',
    interactive_component_type: 'MultiSelect',
  };

  it('an independent scatter selection survives, on its own tile or another', () => {
    const scatter = advancedVizSelectionFilter(tile('sc'), 'label', ['DemoFamA']);
    // An msa row click is the tile's own selection, not part of its brush.
    const msaRow = advancedVizSelectionFilter(tile('msa'), 'seq_id', ['hit3']);
    let filters = apply([scatter], pick('msa', 'P1', 10, 30));
    filters = mergeFiltersBySource(filters, msaRow);
    filters = apply(filters, pick('fam-3d', 'P1', 40, 40));
    expect(filters.map((f) => [f.index, f.source])).toEqual([
      ['sc', 'scatter_selection'],
      ['msa', 'scatter_selection'],
      ['fam-3d', 'residue_selection'],
      ['fam-3d::res', 'residue_selection'],
    ]);
  });

  it('an architecture group (a point pick with no span) survives a pick elsewhere', () => {
    const group = advancedVizSelectionFilter(tile('fam-arch'), 'entity', ['P1', 'P7']);
    const filters = apply([group], pick('fam-3d', 'P1', 40, 40));
    expect(filters.map((f) => f.index)).toEqual(['fam-arch', 'fam-3d', 'fam-3d::res']);
  });

  it("another tile's chain survives when its pick is not the one replaced", () => {
    // The PAE picks on its own columns; the secondary structure and the 3D
    // tile share `entity` / `position`.
    const paeColumns = { entity: 'protein', position: 'resnum' };
    let filters = apply([], [
      ...pick('pae', 'X', 10, 20, paeColumns),
      chainSelectionFilter('pae', 'dc', 'chain_id', 'B'),
    ]);
    filters = apply(filters, pick('ss', 'Z', 5, 5));
    filters = apply(filters, pick('mol', 'Z', 7, 7));
    expect(filters.map((f) => f.index)).toEqual(['pae', 'pae::res', 'pae::chain', 'mol', 'mol::res']);
  });

  it('a sidebar control and an unmarked selection on the chain column survive', () => {
    const chainPoint = advancedVizSelectionFilter(tile('chains'), 'chain', ['A']);
    let filters = apply([sidebarChain, chainPoint], complexPick('pae', 'X', 10, 20, 'B'));
    filters = apply(filters, pick('ss', 'Z', 5, 5));
    expect(filters.map((f) => f.index)).toEqual(['side-chain', 'chains', 'ss', 'ss::res']);
  });
});

describe('clearing a pick clears its gesture', () => {
  it("the tile's Clear removes entity, range, chain and the paired label", () => {
    const other: InteractiveFilter = { index: 'side', value: ['s1'], column_name: 'sample' };
    const filters = apply([other], [
      ...domainClick('P7', 110, 170, 'DemoFamB'),
      chainSelectionFilter('fam-arch', 'dc', 'chain', 'A'),
    ]);
    const own = ownSelection(filters, 'fam-arch');
    expect(own.filters).toHaveLength(4);
    expect(apply(filters, clearedSelectionFilters(own.filters))).toEqual([other]);
  });

  it('a cleared pair takes its chain and its paired label along', () => {
    let filters = apply([], complexPick('mol', 'cx', 10, 20, 'B'));
    filters = apply(filters, pick('mol', null, null));
    expect(filters).toEqual([]);
    filters = apply([], domainClick('P7', 110, 170, 'DemoFamB'));
    filters = apply(filters, pick('fam-arch', null, null));
    expect(filters).toEqual([]);
  });

  it('clearing the paired label alone keeps the span', () => {
    let filters = apply([], domainClick('P7', 110, 170, 'DemoFamB'));
    const label = filters.find((f) => f.source === 'scatter_selection')!;
    filters = mergeFiltersBySource(filters, { ...label, value: null });
    expect(filters.map((f) => f.index)).toEqual(['fam-arch', 'fam-arch::res']);
  });
});

describe('pairedWithResiduePick', () => {
  it('only marks the filter: same key, same payload otherwise', () => {
    const plain = advancedVizSelectionFilter(tile('fam-arch'), 'label', ['DemoFamB']);
    const paired = pairedWithResiduePick(plain);
    expect(paired).toEqual({ ...plain, paired_with: 'residue_selection' });
    // Still one entry per (index, source): an unmarked group pick replaces it.
    const group = advancedVizSelectionFilter(tile('fam-arch'), 'entity', ['P1']);
    expect(apply([paired], [group])).toEqual([group]);
  });
});
