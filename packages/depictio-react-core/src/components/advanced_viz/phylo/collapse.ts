/**
 * Collapsing clades into triangles.
 *
 * Focus (see `prune.ts`) answers "show me only these tips". Collapsing answers
 * the other half: "I know what is in there, stop drawing it". A clade the user
 * has finished reading becomes one wedge whose width still shows how deep it
 * runs and whose label still says how many tips it holds, and the hundreds of
 * edges underneath stop costing anything.
 *
 * The transform turns each collapsed node into a leaf of the display tree, so
 * the layout code needs no notion of collapsing at all — it just lays out a
 * smaller tree. Node `id`s carry over, which is what lets the renderer look the
 * original subtree back up to size the triangle, and lets a click on the wedge
 * expand it again.
 */

import type { PhyloNode, PhyloTree } from './newick';

/** Matches `FALLBACK_LEN` in layout.ts — an edge with no length still has to
 *  take up room, or a cladogram collapses onto a single x. */
const FALLBACK_LEN = 0.1;

const lenOf = (n: PhyloNode): number =>
  Number.isFinite(n.branchLength) ? n.branchLength : FALLBACK_LEN;

/**
 * Display tree in which every id in `collapsed` is a leaf.
 *
 * Returns `null` when nothing was collapsed — either the set is empty or none
 * of its ids names an internal node of this tree, which is the normal case
 * after a Focus prune drops the clade the id referred to.
 */
export function collapseNodes(tree: PhyloTree, collapsed: Set<number>): PhyloTree | null {
  if (collapsed.size === 0) return null;
  let hit = false;

  function rec(n: PhyloNode): PhyloNode {
    const copy: PhyloNode = {
      id: n.id,
      name: n.name,
      branchLength: n.branchLength,
      parent: null,
      children: [],
    };
    if (n.children.length > 0 && collapsed.has(n.id)) {
      hit = true;
      return copy;
    }
    for (const c of n.children) {
      const kid = rec(c);
      kid.parent = copy;
      copy.children.push(kid);
    }
    return copy;
  }

  const root = rec(tree.root);
  if (!hit) return null;

  const leaves: PhyloNode[] = [];
  const nodes: PhyloNode[] = [];
  function walk(n: PhyloNode): number {
    nodes.push(n);
    if (n.children.length === 0) {
      n.leafCount = 1;
      leaves.push(n);
      return 1;
    }
    let count = 0;
    for (const c of n.children) count += walk(c);
    n.leafCount = count;
    return count;
  }
  walk(root);

  return { root, leaves, nodes };
}

export interface CladeExtent {
  /** Tips hidden inside the wedge — the number the label reports. */
  leafCount: number;
  /** Deepest root-to-tip distance below the node, so the wedge can be drawn
   *  as wide as the clade actually runs rather than as a fixed stub. */
  depth: number;
}

/**
 * Size of the clade hidden behind a collapsed node, measured on the *original*
 * tree — the display tree no longer has the children to measure.
 */
export function cladeExtent(tree: PhyloTree, nodeId: number): CladeExtent | null {
  const node = tree.nodes.find((n) => n.id === nodeId);
  if (!node || node.children.length === 0) return null;
  let leafCount = 0;
  let depth = 0;
  function walk(n: PhyloNode, d: number): void {
    if (n.children.length === 0) {
      leafCount += 1;
      if (d > depth) depth = d;
      return;
    }
    for (const c of n.children) walk(c, d + lenOf(c));
  }
  walk(node, 0);
  return { leafCount, depth };
}
