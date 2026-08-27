/**
 * Subtree-selection helpers for the phylogenetic renderer's "filter to
 * subtree" action. Pure functions over `PhyloTree` / `InteractiveFilter` so
 * the selection protocol is unit-testable without Plotly or React.
 *
 * The filter protocol mirrors the scatter/table/map selection sources in
 * `selection.ts`: one `(index, 'tree_selection')` entry whose `value` is the
 * list of taxon names under the selected clade; `[]` clears.
 */

import type { InteractiveFilter } from '../../../api';
import type { PhyloNode, PhyloTree } from './newick';
import { descendants } from './layout';

/** Taxon names of every leaf under the node with the given id. Unnamed
 *  leaves are skipped — they can't be matched against the metadata DC. */
export function collectSubtreeTaxa(tree: PhyloTree, rootId: number): string[] {
  const root = tree.nodes.find((n) => n.id === rootId);
  if (!root) return [];
  const out: string[] = [];
  for (const n of descendants(root)) {
    if (n.children.length === 0 && n.name) out.push(n.name);
  }
  return out;
}

/**
 * The filter entry the phylogeny emits for a selected clade.
 *
 * Unlike `mapSelectionFilter`, `metadata.dc_id` is set explicitly to the
 * *metadata* DC: the component's own `dc_id` in stored metadata is the tree
 * DC (the Newick file), which no other component can join on — so relying on
 * `enrichFilterWithDcId` would mistarget the filter. Passing `[]` clears.
 */
export function buildTreeSelectionFilter(
  componentIndex: string,
  metadataDcId: string,
  taxonCol: string,
  values: string[],
): InteractiveFilter {
  return {
    index: componentIndex,
    value: values,
    source: 'tree_selection',
    column_name: taxonCol,
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: metadataDcId,
      column_name: taxonCol,
      interactive_component_type: 'MultiSelect',
      selection_column: taxonCol,
    },
  };
}

/**
 * Taxa this phylogeny currently has filtered, read back out of the filter
 * list. The tree strips its own entry before fetching (it must keep showing
 * the whole tree), so the filter list is the only record of the selection —
 * this is how the highlight is restored after a tab switch remounts the
 * component.
 */
export function treeSelectionValues(
  filters: InteractiveFilter[],
  componentIndex: string,
): string[] {
  for (const f of filters) {
    if (f.index !== componentIndex || f.source !== 'tree_selection') continue;
    if (Array.isArray(f.value)) return f.value.map((v) => String(v));
  }
  return [];
}

/**
 * Recover the selected clade's root from a set of taxon names.
 *
 * Node ids are parse-order-dependent (reassigned on every `parseNewick`), so
 * a persisted selection can only be restored by name: find the MRCA of the
 * named tips and accept it only when its leaf set matches `values` exactly —
 * otherwise the names no longer describe a clade of this tree (topology
 * changed, tips renamed) and we return null rather than highlight a superset.
 */
export function findSubtreeRootByLeafSet(tree: PhyloTree, values: string[]): number | null {
  if (values.length === 0) return null;
  const wanted = new Set(values);
  const matched = tree.leaves.filter((l) => l.name != null && wanted.has(l.name));
  if (matched.length === 0) return null;

  // MRCA: ancestor chain of the first tip, then ascend each other tip until
  // it lands on that chain, trimming the chain to the meeting point.
  const chain: PhyloNode[] = [];
  for (let n: PhyloNode | null = matched[0]; n; n = n.parent) chain.push(n);
  const chainIndex = new Map<number, number>(chain.map((n, i) => [n.id, i]));
  let mrcaIdx = 0;
  for (const leaf of matched.slice(1)) {
    let n: PhyloNode | null = leaf;
    while (n && !chainIndex.has(n.id)) n = n.parent;
    if (!n) return null;
    mrcaIdx = Math.max(mrcaIdx, chainIndex.get(n.id)!);
  }
  const mrca = chain[mrcaIdx];

  const mrcaTaxa = collectSubtreeTaxa(tree, mrca.id);
  if (mrcaTaxa.length !== wanted.size) return null;
  for (const t of mrcaTaxa) if (!wanted.has(t)) return null;
  return mrca.id;
}
