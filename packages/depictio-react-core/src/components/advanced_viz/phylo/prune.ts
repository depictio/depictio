/**
 * Prune a tree down to a set of tips — the "Focus" view.
 *
 * Ghosting out-of-scope tips keeps the whole topology on screen, which is what
 * you want to see where a selection sits. It is the wrong answer when the
 * point is to *read* the surviving clade: a few dozen kept tips still pay for
 * every edge of the original tree, both in render cost and in visual noise.
 * Focus rebuilds the induced tree instead, so what is left is all there is.
 *
 * Two properties matter for the result to still be a tree anyone can trust:
 *
 *   - internal nodes that keep only one child are **collapsed**, and their
 *     branch folded into that child's. Dropping them without adding their
 *     length back would silently shorten every root-to-tip distance below
 *     them, which is the sort of error a phylogeny is used to detect.
 *   - the surviving root is the MRCA of the kept tips and carries no incoming
 *     branch — the stem above it is outside the induced tree, so drawing it
 *     would imply a parent that isn't there.
 *
 * Node `id`s are carried over from the source tree, which is what lets clade
 * selection (`subtree.ts`) and the highlight keep working across a prune.
 */

import type { PhyloNode, PhyloTree } from './newick';

/** Branch lengths are optional in Newick; NaN means "no length given". Adding
 *  a known length to an unknown one yields the known one rather than NaN, so a
 *  partially-annotated tree doesn't lose the lengths it does have. */
function addLength(a: number, b: number): number {
  const aOk = Number.isFinite(a);
  const bOk = Number.isFinite(b);
  if (aOk && bOk) return a + b;
  if (aOk) return a;
  if (bOk) return b;
  return NaN;
}

/**
 * Induced subtree over the tips named in `keep`.
 *
 * Returns `null` when pruning would be a no-op or nonsense — no tip matched,
 * or every tip matched — so callers can fall back to the full tree without
 * special-casing.
 */
export function pruneToTips(tree: PhyloTree, keep: Set<string>): PhyloTree | null {
  if (keep.size === 0) return null;
  let kept = 0;
  for (const leaf of tree.leaves) if (keep.has(leaf.name ?? '')) kept++;
  if (kept === 0 || kept === tree.leaves.length) return null;

  function rec(n: PhyloNode): PhyloNode | null {
    if (n.children.length === 0) {
      if (!keep.has(n.name ?? '')) return null;
      return { id: n.id, name: n.name, branchLength: n.branchLength, parent: null, children: [] };
    }
    const kids: PhyloNode[] = [];
    for (const c of n.children) {
      const kid = rec(c);
      if (kid) kids.push(kid);
    }
    if (kids.length === 0) return null;
    // One surviving child: this node no longer branches, so it isn't a node of
    // the induced tree. Fold its branch into the child's on the way out.
    if (kids.length === 1) {
      kids[0].branchLength = addLength(n.branchLength, kids[0].branchLength);
      return kids[0];
    }
    const copy: PhyloNode = {
      id: n.id,
      name: n.name,
      branchLength: n.branchLength,
      parent: null,
      children: kids,
    };
    for (const k of kids) k.parent = copy;
    return copy;
  }

  const root = rec(tree.root);
  if (!root) return null;
  root.parent = null;
  root.branchLength = NaN;

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
