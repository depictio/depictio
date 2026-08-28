import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import { ladderise, parseNewick } from './newick';
import {
  buildTreeSelectionFilter,
  collectSubtreeTaxa,
  findSubtreeRootByLeafSet,
  treeSelectionValues,
} from './subtree';

const NWK = '((A:1,B:2)AB:0.5,(C:1,(D:1,E:1)DE:0.3)CDE:0.7)root;';

function nodeId(tree: ReturnType<typeof parseNewick>, name: string): number {
  return tree.nodes.find((n) => n.name === name)!.id;
}

describe('collectSubtreeTaxa', () => {
  it('returns the leaf names under an internal node', () => {
    const tree = parseNewick(NWK);
    expect(collectSubtreeTaxa(tree, nodeId(tree, 'CDE')).sort()).toEqual(['C', 'D', 'E']);
  });

  it('returns a single name for a leaf and [] for an unknown id', () => {
    const tree = parseNewick(NWK);
    expect(collectSubtreeTaxa(tree, nodeId(tree, 'A'))).toEqual(['A']);
    expect(collectSubtreeTaxa(tree, 9999)).toEqual([]);
  });
});

describe('buildTreeSelectionFilter', () => {
  it('targets the metadata DC explicitly with the tree_selection source', () => {
    const f = buildTreeSelectionFilter('phylo-tree', 'meta-dc-1', 'taxon', ['C', 'D']);
    expect(f).toEqual({
      index: 'phylo-tree',
      value: ['C', 'D'],
      source: 'tree_selection',
      column_name: 'taxon',
      interactive_component_type: 'MultiSelect',
      metadata: {
        dc_id: 'meta-dc-1',
        column_name: 'taxon',
        interactive_component_type: 'MultiSelect',
        selection_column: 'taxon',
      },
    });
  });

  it('clears with an empty value list (mergeFiltersBySource drops it)', () => {
    expect(buildTreeSelectionFilter('phylo-tree', 'meta-dc-1', 'taxon', []).value).toEqual([]);
  });
});

describe('treeSelectionValues', () => {
  const filters: InteractiveFilter[] = [
    { index: 'phylo-tree', value: ['x'], column_name: 'group' }, // regular filter, no source
    { index: 'other', value: ['C'], source: 'tree_selection' },
    { index: 'phylo-tree', value: ['C', 'D'], source: 'tree_selection' },
  ];

  it('reads back only this component’s tree_selection entry', () => {
    expect(treeSelectionValues(filters, 'phylo-tree')).toEqual(['C', 'D']);
  });

  it('returns [] when no entry matches', () => {
    expect(treeSelectionValues(filters, 'missing')).toEqual([]);
  });
});

describe('findSubtreeRootByLeafSet', () => {
  it('recovers the clade root from its exact leaf set', () => {
    const tree = parseNewick(NWK);
    expect(findSubtreeRootByLeafSet(tree, ['D', 'E', 'C'])).toBe(nodeId(tree, 'CDE'));
    expect(findSubtreeRootByLeafSet(tree, ['D', 'E'])).toBe(nodeId(tree, 'DE'));
    expect(findSubtreeRootByLeafSet(tree, ['A'])).toBe(nodeId(tree, 'A'));
  });

  it('rejects a set that is not exactly one clade', () => {
    const tree = parseNewick(NWK);
    // MRCA of {C, D} is CDE, whose leaf set {C, D, E} is a superset — must
    // not silently highlight the wider clade.
    expect(findSubtreeRootByLeafSet(tree, ['C', 'D'])).toBeNull();
    expect(findSubtreeRootByLeafSet(tree, ['A', 'E'])).toBeNull();
    expect(findSubtreeRootByLeafSet(tree, [])).toBeNull();
    expect(findSubtreeRootByLeafSet(tree, ['nope'])).toBeNull();
  });

  it('is stable across re-parse and ladderise (the restore-by-name path)', () => {
    const first = parseNewick(NWK);
    const taxa = collectSubtreeTaxa(first, nodeId(first, 'DE'));
    const second = parseNewick(NWK);
    ladderise(second, false);
    expect(findSubtreeRootByLeafSet(second, taxa)).toBe(nodeId(second, 'DE'));
  });
});
