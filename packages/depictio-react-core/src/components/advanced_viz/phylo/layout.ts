/**
 * Tree-layout algorithms producing per-node (x, y) coordinates and a flat
 * list of edges for the Plotly renderer.
 *
 * Reference: prototype_plotly.py + tree_utils.py from the
 * claude/phylogenetic-tree-components-zJhGm branch (Biopython-based Python
 * implementations ported to TypeScript).
 *
 * Five layouts:
 *   rectangular  — x = cumulative branch length, y = leaf order
 *   hierarchical — same as rectangular, rotated 90° (x = leaf order, y down)
 *   circular     — polar of rectangular (angle ∝ y, radius ∝ x)
 *   radial       — equal-angle (Felsenstein) for unrooted trees
 *   diagonal     — same as rectangular, but edges are straight diagonals
 */

import type { PhyloNode, PhyloTree } from './newick';

export type Layout = 'rectangular' | 'hierarchical' | 'circular' | 'radial' | 'diagonal';

export interface EdgeSegment {
  /** Series of [x, y] points along the edge — passed to a single plotly trace. */
  pts: [number, number][];
  /** Source/destination nodes (for hover + subtree-highlight). */
  from: PhyloNode;
  to: PhyloNode;
}

export interface LayoutResult {
  /** All nodes in the tree, with x/y/angle assigned. */
  nodes: PhyloNode[];
  /** Leaves only, in display order (top → bottom for rectangular). */
  leaves: PhyloNode[];
  /** Edge segments — concatenate with `null` separators to feed into one
   *  plotly scatter trace per styling group. */
  edges: EdgeSegment[];
  /** Bounding box of the layout — useful for axis range hints. */
  bbox: { minX: number; minY: number; maxX: number; maxY: number };
}

const FALLBACK_LEN = 0.1; // when branch_length is NaN — keep edges visible.

function depthFromRoot(n: PhyloNode): number {
  let d = 0;
  let cur: PhyloNode | null = n;
  while (cur) {
    d += Number.isFinite(cur.branchLength) ? cur.branchLength : FALLBACK_LEN;
    cur = cur.parent;
  }
  return d - (Number.isFinite(n.branchLength) ? n.branchLength : FALLBACK_LEN);
}

/** Rectangular: x = distance from root, y = leaf index (internal = mean of children). */
function layoutRectangular(tree: PhyloTree): LayoutResult {
  for (let i = 0; i < tree.leaves.length; i++) tree.leaves[i].y = i;

  function visit(n: PhyloNode): { x: number; y: number } {
    n.x = depthFromRoot(n) + (Number.isFinite(n.branchLength) ? n.branchLength : FALLBACK_LEN);
    if (n.children.length === 0) {
      n.y = n.y!;
      return { x: n.x, y: n.y };
    }
    const ys: number[] = [];
    for (const c of n.children) ys.push(visit(c).y);
    n.y = (Math.min(...ys) + Math.max(...ys)) / 2;
    return { x: n.x, y: n.y };
  }
  // Root depth = 0 (no leading branch).
  tree.root.x = 0;
  for (const c of tree.root.children) visit(c);
  if (tree.root.children.length > 0) {
    const ys = tree.root.children.map((c) => c.y!);
    tree.root.y = (Math.min(...ys) + Math.max(...ys)) / 2;
  } else {
    tree.root.y = 0;
  }

  // Edges: square-bracket "phylogram" style (horizontal then vertical).
  const edges: EdgeSegment[] = [];
  for (const n of tree.nodes) {
    if (!n.parent) continue;
    // Horizontal from parent's x → node's x at node's y, then vertical
    // from node's y → parent's y at parent's x. Drawn as one polyline
    // (parent.x, parent.y) → (parent.x, n.y) → (n.x, n.y).
    edges.push({
      pts: [
        [n.parent.x!, n.parent.y!],
        [n.parent.x!, n.y!],
        [n.x!, n.y!],
      ],
      from: n.parent,
      to: n,
    });
  }
  return {
    nodes: tree.nodes,
    leaves: tree.leaves,
    edges,
    bbox: bbox(tree.nodes),
  };
}

function layoutHierarchical(tree: PhyloTree): LayoutResult {
  const r = layoutRectangular(tree);
  // Rotate 90°: new_x = y, new_y = -x. Leaves end up across the top.
  for (const n of r.nodes) {
    const oldX = n.x!;
    const oldY = n.y!;
    n.x = oldY;
    n.y = -oldX;
  }
  for (const e of r.edges) {
    e.pts = e.pts.map(([x, y]) => [y, -x]);
  }
  return { ...r, bbox: bbox(r.nodes) };
}

function layoutDiagonal(tree: PhyloTree): LayoutResult {
  const r = layoutRectangular(tree);
  // Replace polyline with a straight segment from parent to child.
  r.edges = r.edges.map((e) => ({
    pts: [
      [e.from.x!, e.from.y!],
      [e.to.x!, e.to.y!],
    ],
    from: e.from,
    to: e.to,
  }));
  return r;
}

function layoutCircular(tree: PhyloTree): LayoutResult {
  // Start from rectangular coords; polar-transform: radius = x, angle ∝ y.
  layoutRectangular(tree);
  const nLeaves = Math.max(1, tree.leaves.length);
  // Use 350° (leave a gap at the top to avoid first==last overlap).
  const angularSpan = (350 * Math.PI) / 180;
  for (const n of tree.nodes) {
    const angle = (n.y! / Math.max(1, nLeaves - 1)) * angularSpan;
    const r = n.x!;
    n.angle = angle;
    n.x = r * Math.cos(angle);
    n.y = r * Math.sin(angle);
  }

  const edges: EdgeSegment[] = [];
  // For curved edges between parent and child, draw the arc at parent's
  // radius from parent's angle to child's angle, then the radial line out
  // to child's radius.
  const ARC_STEPS = 24;
  for (const n of tree.nodes) {
    if (!n.parent) continue;
    const pAngle = n.parent.angle ?? 0;
    const cAngle = n.angle ?? 0;
    const pRadius = depthFromRoot(n.parent) +
      (Number.isFinite(n.parent.branchLength) ? n.parent.branchLength : FALLBACK_LEN);
    const cRadius = depthFromRoot(n) +
      (Number.isFinite(n.branchLength) ? n.branchLength : FALLBACK_LEN);
    const arcPts: [number, number][] = [];
    for (let i = 0; i <= ARC_STEPS; i++) {
      const t = i / ARC_STEPS;
      const a = pAngle + (cAngle - pAngle) * t;
      arcPts.push([pRadius * Math.cos(a), pRadius * Math.sin(a)]);
    }
    arcPts.push([cRadius * Math.cos(cAngle), cRadius * Math.sin(cAngle)]);
    edges.push({ pts: arcPts, from: n.parent, to: n });
  }
  return { nodes: tree.nodes, leaves: tree.leaves, edges, bbox: bbox(tree.nodes) };
}

/** Equal-angle (Felsenstein) layout — unrooted radial. */
function layoutRadial(tree: PhyloTree): LayoutResult {
  const nLeaves = Math.max(1, tree.leaves.length);
  // Assign each leaf a slice of the full circle.
  let leafIdx = 0;
  function visit(n: PhyloNode, fromAngle: number, toAngle: number, originX: number, originY: number): void {
    n.x = originX;
    n.y = originY;
    if (n.children.length === 0) {
      n.angle = (fromAngle + toAngle) / 2;
      leafIdx++;
      return;
    }
    let cursor = fromAngle;
    for (const c of n.children) {
      const slice = ((c.leafCount ?? 1) / nLeaves) * (toAngle - fromAngle);
      const cFrom = cursor;
      const cTo = cursor + slice;
      const cMid = (cFrom + cTo) / 2;
      const len = Number.isFinite(c.branchLength) ? c.branchLength : FALLBACK_LEN;
      const cx = originX + len * Math.cos(cMid);
      const cy = originY + len * Math.sin(cMid);
      visit(c, cFrom, cTo, cx, cy);
      cursor = cTo;
    }
  }
  visit(tree.root, 0, 2 * Math.PI, 0, 0);
  const edges: EdgeSegment[] = [];
  for (const n of tree.nodes) {
    if (!n.parent) continue;
    edges.push({
      pts: [
        [n.parent.x!, n.parent.y!],
        [n.x!, n.y!],
      ],
      from: n.parent,
      to: n,
    });
  }
  return { nodes: tree.nodes, leaves: tree.leaves, edges, bbox: bbox(tree.nodes) };
}

function bbox(nodes: PhyloNode[]): { minX: number; minY: number; maxX: number; maxY: number } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    if (n.x == null || n.y == null) continue;
    if (n.x < minX) minX = n.x;
    if (n.x > maxX) maxX = n.x;
    if (n.y < minY) minY = n.y;
    if (n.y > maxY) maxY = n.y;
  }
  return { minX, minY, maxX, maxY };
}

export function computeLayout(tree: PhyloTree, kind: Layout): LayoutResult {
  switch (kind) {
    case 'hierarchical':
      return layoutHierarchical(tree);
    case 'circular':
      return layoutCircular(tree);
    case 'radial':
      return layoutRadial(tree);
    case 'diagonal':
      return layoutDiagonal(tree);
    case 'rectangular':
    default:
      return layoutRectangular(tree);
  }
}

/** Collect every descendant of `root` (including `root` itself). */
export function descendants(root: PhyloNode): PhyloNode[] {
  const out: PhyloNode[] = [];
  const stack = [root];
  while (stack.length > 0) {
    const n = stack.pop()!;
    out.push(n);
    for (const c of n.children) stack.push(c);
  }
  return out;
}
