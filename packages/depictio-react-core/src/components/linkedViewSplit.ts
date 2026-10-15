/**
 * The split tree of a linked view: its tiles as nested panes with a draggable
 * gutter between every two neighbours. Pure geometry, so the grid, the gutter
 * handles and the tests all apply one rule.
 *
 * A linked view's stored layout is a set of rectangles on 8 columns. When it can
 * be cut into its tiles by straight lines that run edge to edge (a guillotine
 * layout), those lines are the gutters: a full-height vertical cut first, else
 * a full-width horizontal one, then the same inside each part. Several cuts at
 * one level make one multi-way split, so three stacked tiles are one `column`
 * split with two gutters. Dragging a gutter moves one shared edge, and every
 * tile that lies against it follows (`moveGutterTree`).
 *
 * A layout that is not a guillotine one (a pinwheel), or that does not fill its
 * bounding box (a hole, a section narrower than the grid), has no tree: the
 * caller keeps drawing it with react-grid-layout. The four shipped linked views
 * (a tall structure beside a stack, optionally under a full-width table) are
 * all guillotine layouts.
 *
 * Sizes are in the unit the layout is counted in: grid columns across, and
 * whole rows (the editor) or half rows (a read-only grid, `ROW_SPLIT`) down.
 *
 * The last section holds the floors: the least height a pane keeps by default,
 * the height a tree needs to give every pane its floor, and how the stored
 * sizes are bent to honour them (`floorTree`), measured and shared out in px.
 */
import { GRID_MAX_COLS } from '../gridConfig';
import { LINKED_VIEW_MIN_PANE_PX } from './sectionGroups';
import type { GroupTile } from './sectionGroups';

/** `row`: children side by side, sized by width. `column`: children stacked,
 *  sized by height. */
export type SplitDir = 'row' | 'column';

/** The axis a split's sizes run along: `x` for a row, `y` for a column. */
export type SplitAxis = 'x' | 'y';

export interface SplitLeaf {
  kind: 'leaf';
  /** The tile's layout key (`GroupTile.i`). */
  key: string;
}

export interface SplitBranch {
  kind: 'split';
  dir: SplitDir;
  children: SplitNode[];
  /** Each child's extent along the split's axis, in grid units. Children share
   *  the split's other extent. */
  sizes: number[];
}

export type SplitNode = SplitLeaf | SplitBranch;

/** A tree and the box it fills, in grid units. */
export interface SplitTree {
  root: SplitNode;
  /** Columns across. */
  w: number;
  /** Rows (or half rows) down. */
  h: number;
}

/** One grid unit on each axis: the least a tile keeps, and how far a keyboard
 *  nudge moves a gutter. A stored row is 2 units tall on a read-only grid. */
export interface SplitUnit {
  x: number;
  y: number;
}

export const ONE_UNIT: SplitUnit = { x: 1, y: 1 };

export interface SplitRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const axisOf = (dir: SplitDir): SplitAxis => (dir === 'row' ? 'x' : 'y');

const EPS = 1e-9;

interface Item extends SplitRect {
  key: string;
}

const lo = (b: SplitRect, axis: SplitAxis) => (axis === 'x' ? b.x : b.y);
const span = (b: SplitRect, axis: SplitAxis) => (axis === 'x' ? b.w : b.h);
const hi = (b: SplitRect, axis: SplitAxis) => lo(b, axis) + span(b, axis);

/** Every tile lies inside `box`. */
const inside = (t: SplitRect, box: SplitRect) =>
  t.x >= box.x - EPS &&
  t.y >= box.y - EPS &&
  t.x + t.w <= box.x + box.w + EPS &&
  t.y + t.h <= box.y + box.h + EPS;

/** Positions strictly inside `box` along `axis` that no tile straddles. */
function cutsAlong(items: readonly Item[], box: SplitRect, axis: SplitAxis): number[] {
  const from = lo(box, axis);
  const to = hi(box, axis);
  const candidates: number[] = [];
  for (const t of items) {
    for (const c of [lo(t, axis), hi(t, axis)]) {
      if (c > from + EPS && c < to - EPS && !candidates.some((k) => Math.abs(k - c) < EPS)) {
        candidates.push(c);
      }
    }
  }
  return candidates
    .filter((c) => items.every((t) => !(lo(t, axis) < c - EPS && hi(t, axis) > c + EPS)))
    .sort((a, b) => a - b);
}

function build(items: readonly Item[], box: SplitRect): SplitNode | null {
  // The tiles tile the box exactly: nothing outside it, no gap, no overlap
  // (overlaps are ruled out once, for the whole layout).
  const area = items.reduce((sum, t) => sum + t.w * t.h, 0);
  if (!items.every((t) => inside(t, box)) || Math.abs(area - box.w * box.h) > EPS) return null;
  if (items.length === 1) return { kind: 'leaf', key: items[0].key };
  for (const dir of ['row', 'column'] as const) {
    const axis = axisOf(dir);
    const cuts = cutsAlong(items, box, axis);
    if (cuts.length === 0) continue;
    const edges = [lo(box, axis), ...cuts, hi(box, axis)];
    const children: SplitNode[] = [];
    const sizes: number[] = [];
    for (let k = 0; k + 1 < edges.length; k += 1) {
      const from = edges[k];
      const to = edges[k + 1];
      const group = items.filter(
        (t) => lo(t, axis) >= from - EPS && hi(t, axis) <= to + EPS,
      );
      const part: SplitRect =
        axis === 'x'
          ? { x: from, y: box.y, w: to - from, h: box.h }
          : { x: box.x, y: from, w: box.w, h: to - from };
      const child = build(group, part);
      if (!child) return null;
      children.push(child);
      sizes.push(to - from);
    }
    return { kind: 'split', dir, children, sizes };
  }
  return null;
}

/**
 * The split tree of `layouts`, or null when it has none: no tiles, tiles that
 * overlap or share a key, a layout that leaves a gap or does not span the grid's
 * `cols` columns from the first row down, or one no sequence of edge-to-edge
 * cuts takes apart (a pinwheel). A single tile is a tree of one leaf.
 */
export function buildSplitTree(
  layouts: readonly GroupTile[],
  cols: number = GRID_MAX_COLS,
): SplitTree | null {
  if (layouts.length === 0) return null;
  const items: Item[] = layouts.map((t) => ({ key: t.i, x: t.x, y: t.y, w: t.w, h: t.h }));
  if (new Set(items.map((t) => t.key)).size !== items.length) return null;
  for (const t of items) {
    if (![t.x, t.y, t.w, t.h].every(Number.isFinite) || t.w <= 0 || t.h <= 0) return null;
  }
  for (let a = 0; a < items.length; a += 1) {
    for (let b = a + 1; b < items.length; b += 1) {
      const p = items[a];
      const q = items[b];
      const apart =
        p.x + p.w <= q.x + EPS ||
        q.x + q.w <= p.x + EPS ||
        p.y + p.h <= q.y + EPS ||
        q.y + q.h <= p.y + EPS;
      if (!apart) return null;
    }
  }
  const right = items.reduce((m, t) => Math.max(m, t.x + t.w), 0);
  const bottom = items.reduce((m, t) => Math.max(m, t.y + t.h), 0);
  const left = items.reduce((m, t) => Math.min(m, t.x), Infinity);
  const top = items.reduce((m, t) => Math.min(m, t.y), Infinity);
  if (Math.abs(left) > EPS || Math.abs(top) > EPS || Math.abs(right - cols) > EPS) return null;
  const root = build(items, { x: 0, y: 0, w: right, h: bottom });
  return root ? { root, w: right, h: bottom } : null;
}

/** The node at `path` (child indexes from the root), or null past a leaf. */
export function nodeAt(root: SplitNode, path: readonly number[]): SplitNode | null {
  let node: SplitNode = root;
  for (const i of path) {
    if (node.kind !== 'split' || i < 0 || i >= node.children.length) return null;
    node = node.children[i];
  }
  return node;
}

function replaceAt(node: SplitNode, path: readonly number[], next: SplitNode): SplitNode {
  if (path.length === 0) return next;
  if (node.kind !== 'split') return node;
  const [i, ...rest] = path;
  const children = node.children.slice();
  children[i] = replaceAt(children[i], rest, next);
  return { ...node, children };
}

/** Where each tile sits. */
export function treeRects(tree: SplitTree): Map<string, SplitRect> {
  const out = new Map<string, SplitRect>();
  const walk = (node: SplitNode, rect: SplitRect) => {
    if (node.kind === 'leaf') {
      out.set(node.key, rect);
      return;
    }
    const axis = axisOf(node.dir);
    let at = lo(rect, axis);
    node.children.forEach((child, i) => {
      const size = node.sizes[i];
      walk(
        child,
        axis === 'x' ? { ...rect, x: at, w: size } : { ...rect, y: at, h: size },
      );
      at += size;
    });
  };
  walk(tree.root, { x: 0, y: 0, w: tree.w, h: tree.h });
  return out;
}

/** `layouts` with the geometry of `tree`, every other property kept. A tile the
 *  tree does not hold is left as it was. */
export function treeLayouts<T extends GroupTile>(tree: SplitTree, layouts: readonly T[]): T[] {
  const rects = treeRects(tree);
  return layouts.map((t) => {
    const r = rects.get(t.i);
    return r ? { ...t, x: r.x, y: r.y, w: r.w, h: r.h } : { ...t };
  });
}

/** The least a node may measure along `axis`: a tile keeps `unit`, nodes add up
 *  along their own axis and take the larger of their children across it. */
export function minSpan(node: SplitNode, axis: SplitAxis, unit: SplitUnit = ONE_UNIT): number {
  if (node.kind === 'leaf') return unit[axis];
  const spans = node.children.map((c) => minSpan(c, axis, unit));
  return axisOf(node.dir) === axis
    ? spans.reduce((a, b) => a + b, 0)
    : spans.reduce((a, b) => Math.max(a, b), 0);
}

/**
 * How much `node`, `size` long along `axis`, can lose from its `anchor` edge.
 * Only the tile that lies against that edge gives way (moving a gutter does not
 * reshuffle the tiles behind it), so a node is as flexible as its edge tile; a
 * node split across the axis is as flexible as its least flexible part.
 */
function shrinkRoom(
  node: SplitNode,
  axis: SplitAxis,
  anchor: 'start' | 'end',
  size: number,
  unit: SplitUnit,
): number {
  if (node.kind === 'leaf') return Math.max(0, size - unit[axis]);
  if (axisOf(node.dir) === axis) {
    const i = anchor === 'end' ? node.children.length - 1 : 0;
    return shrinkRoom(node.children[i], axis, anchor, node.sizes[i], unit);
  }
  return node.children.reduce(
    (room, c) => Math.min(room, shrinkRoom(c, axis, anchor, size, unit)),
    Infinity,
  );
}

/** `node` with its `anchor` edge moved by `delta` along `axis` (positive grows
 *  it): the tiles against that edge take the change. */
function moveEdge(
  node: SplitNode,
  axis: SplitAxis,
  anchor: 'start' | 'end',
  delta: number,
): SplitNode {
  if (node.kind === 'leaf' || delta === 0) return node;
  if (axisOf(node.dir) === axis) {
    const i = anchor === 'end' ? node.children.length - 1 : 0;
    const sizes = node.sizes.slice();
    sizes[i] += delta;
    const children = node.children.slice();
    children[i] = moveEdge(children[i], axis, anchor, delta);
    return { ...node, sizes, children };
  }
  return { ...node, children: node.children.map((c) => moveEdge(c, axis, anchor, delta)) };
}

/**
 * How far gutter `gutter` of the split at `path` may move: `min` is the most
 * it may go back (a negative number), `max` the most it may go forward.
 */
export function gutterRange(
  tree: SplitTree,
  path: readonly number[],
  gutter: number,
  unit: SplitUnit = ONE_UNIT,
): { min: number; max: number } {
  const node = nodeAt(tree.root, path);
  if (!node || node.kind !== 'split' || gutter < 0 || gutter + 1 >= node.children.length) {
    return { min: 0, max: 0 };
  }
  const axis = axisOf(node.dir);
  const back = shrinkRoom(node.children[gutter], axis, 'end', node.sizes[gutter], unit);
  const forward = shrinkRoom(node.children[gutter + 1], axis, 'start', node.sizes[gutter + 1], unit);
  return { min: 0 - back, max: forward };
}

/**
 * The tree with one gutter moved by `delta` units (positive: right or down),
 * clamped so no tile drops below `unit`; `delta` in the result is what was
 * applied. Of the two neighbours, the one before grows (or shrinks) at its far
 * edge and the one after shifts and shrinks (or grows) at its near edge: only
 * the tiles that lie against the gutter change, the others keep their size.
 */
export function moveGutterTree(
  tree: SplitTree,
  path: readonly number[],
  gutter: number,
  delta: number,
  unit: SplitUnit = ONE_UNIT,
): { tree: SplitTree; delta: number } {
  const node = nodeAt(tree.root, path);
  if (!node || node.kind !== 'split' || gutter < 0 || gutter + 1 >= node.children.length) {
    return { tree, delta: 0 };
  }
  const range = gutterRange(tree, path, gutter, unit);
  const applied = Math.min(range.max, Math.max(range.min, Number.isFinite(delta) ? delta : 0)) || 0;
  if (applied === 0) return { tree, delta: 0 };
  const axis = axisOf(node.dir);
  const sizes = node.sizes.slice();
  const children = node.children.slice();
  sizes[gutter] += applied;
  sizes[gutter + 1] -= applied;
  children[gutter] = moveEdge(children[gutter], axis, 'end', applied);
  children[gutter + 1] = moveEdge(children[gutter + 1], axis, 'start', -applied);
  const next: SplitBranch = { ...node, sizes, children };
  return { tree: { ...tree, root: replaceAt(tree.root, path, next) }, delta: applied };
}

/**
 * `layouts` with one gutter moved by `deltaUnits`, rounded to whole grid units
 * (the editor stores integers). The layout comes back unchanged when it has no
 * split tree, `path` and `gutter` name nothing, or the move is clamped to zero.
 * `path` is the split's child indexes from the root, `gutter` the index of the
 * child before it.
 */
export function moveGutter<T extends GroupTile>(
  layouts: readonly T[],
  path: readonly number[],
  gutter: number,
  deltaUnits: number,
  unit: SplitUnit = ONE_UNIT,
): T[] {
  const tree = buildSplitTree(layouts);
  if (!tree) return layouts.map((t) => ({ ...t }));
  const moved = moveGutterTree(tree, path, gutter, Math.round(deltaUnits), unit);
  return moved.delta === 0 ? layouts.map((t) => ({ ...t })) : treeLayouts(moved.tree, layouts);
}

// ---- Personal gutter positions ----------------------------------------------
//
// A reader's drag is not written to the dashboard: it is kept as fractions of
// each split, per path, so it survives a resize of the window. The signature
// names the structure the fractions belong to, so a dashboard whose layout was
// re-cut since is not handed positions that mean something else.

/** Each split's children as shares of the split's own extent (summing to 1),
 *  by `pathKey`. */
export type SplitFractions = Record<string, number[]>;

export const pathKey = (path: readonly number[]): string => (path.length ? path.join('.') : 'root');

/** The tree's shape and tile keys, without any size. */
export function splitSignature(tree: SplitTree): string {
  const shape = (node: SplitNode): unknown =>
    node.kind === 'leaf' ? node.key : [node.dir === 'row' ? 'r' : 'c', ...node.children.map(shape)];
  return JSON.stringify(shape(tree.root));
}

/** Every split's sizes as shares of its extent. */
export function treeFractions(tree: SplitTree): SplitFractions {
  const out: SplitFractions = {};
  const walk = (node: SplitNode, path: number[]) => {
    if (node.kind === 'leaf') return;
    const total = node.sizes.reduce((a, b) => a + b, 0);
    out[pathKey(path)] = node.sizes.map((s) => s / total);
    node.children.forEach((c, i) => walk(c, [...path, i]));
  };
  walk(tree.root, []);
  return out;
}

/** Whether two fraction sets name the same positions, give or take rounding. */
export function sameFractions(a: SplitFractions, b: SplitFractions, tolerance = 1e-6): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) {
    const p = a[k];
    const q = b[k];
    if (!p || !q || p.length !== q.length) return false;
    if (p.some((v, i) => Math.abs(v - q[i]) > tolerance)) return false;
  }
  return true;
}

/** Smallest share a stored fraction may hold before it is taken as garbage. */
const MIN_STORED_FRACTION = 0.01;

const usable = (f: unknown, n: number): f is number[] =>
  Array.isArray(f) &&
  f.length === n &&
  f.every((v) => typeof v === 'number' && Number.isFinite(v) && v >= MIN_STORED_FRACTION);

/**
 * `tree` with each split's sizes taken from `fractions` where they fit it
 * (same child count, sane values) and from its own proportions elsewhere,
 * rescaled to the extent the split has once the splits above it moved. Null
 * fractions give the tree back as it is.
 */
export function withFractions(tree: SplitTree, fractions: SplitFractions | null | undefined): SplitTree {
  if (!fractions) return tree;
  const walk = (node: SplitNode, w: number, h: number, path: number[]): SplitNode => {
    if (node.kind === 'leaf') return node;
    const axis = axisOf(node.dir);
    const total = axis === 'x' ? w : h;
    const given = fractions[pathKey(path)];
    const weights = usable(given, node.children.length) ? given : node.sizes;
    const sum = weights.reduce((a, b) => a + b, 0);
    const sizes = weights.map((v) => (v / sum) * total);
    const children = node.children.map((c, i) =>
      walk(c, axis === 'x' ? sizes[i] : w, axis === 'x' ? h : sizes[i], [...path, i]),
    );
    return { ...node, sizes, children };
  };
  return { ...tree, root: walk(tree.root, tree.w, tree.h, []) };
}

/**
 * `current` with one gutter back where `base` (the dashboard's own layout)
 * has it, as a share of the split. The other gutters stay where they are.
 */
export function resetGutter(
  current: SplitTree,
  base: SplitTree,
  path: readonly number[],
  gutter: number,
  unit: SplitUnit = ONE_UNIT,
): { tree: SplitTree; delta: number } {
  const was = nodeAt(base.root, path);
  const now = nodeAt(current.root, path);
  if (!was || !now || was.kind !== 'split' || now.kind !== 'split') return { tree: current, delta: 0 };
  const share =
    was.sizes.slice(0, gutter + 1).reduce((a, b) => a + b, 0) /
    was.sizes.reduce((a, b) => a + b, 0);
  const total = now.sizes.reduce((a, b) => a + b, 0);
  const at = now.sizes.slice(0, gutter + 1).reduce((a, b) => a + b, 0);
  return moveGutterTree(current, path, gutter, share * total - at, unit);
}

/** Where a dashboard's reader keeps their gutter positions for one section. */
export function linkedViewSplitStorageKey(dashboardId: string, sectionKey: string): string {
  return `depictio:linked-view-split:${dashboardId}:${sectionKey}`;
}

/** What is written under the storage key. */
export function serializeStoredSplit(signature: string, fractions: SplitFractions): string {
  return JSON.stringify({ v: 1, sig: signature, fractions });
}

/** The fractions stored for a tree with `signature`, or null for anything else
 *  (nothing stored, unreadable, another version, another structure). */
export function parseStoredSplit(raw: string | null | undefined, signature: string): SplitFractions | null {
  if (!raw) return null;
  try {
    const data = JSON.parse(raw) as { v?: unknown; sig?: unknown; fractions?: unknown };
    if (data?.v !== 1 || data.sig !== signature) return null;
    const fractions = data.fractions;
    if (!fractions || typeof fractions !== 'object' || Array.isArray(fractions)) return null;
    const out: SplitFractions = {};
    for (const [k, v] of Object.entries(fractions as Record<string, unknown>)) {
      if (Array.isArray(v) && v.every((n) => typeof n === 'number' && Number.isFinite(n))) {
        out[k] = v as number[];
      }
    }
    return Object.keys(out).length > 0 ? out : null;
  } catch {
    return null;
  }
}

// ---- Floors: the least a pane keeps by default --------------------------------
//
// A stack of three tiles on a laptop's screen leaves each one a sliver, and a
// track or an alignment in it spills past its box. So every tile has a floor, in
// px (`LINKED_VIEW_MIN_PANE_PX` unless the caller knows better, a card or a text
// tile has none): the linked view is made as tall as its stacks need to honour
// them, and the stored proportions are bent to them, the way a flex column with
// a `min-height` on each child shares its room (`shareWithFloors`).
//
// Only the dashboard's own split (the stored layout, and what "reset" returns
// to) is floored. A reader's drag is theirs: it is free down to one grid unit,
// or a tight stack of three would have no room to move at all.

/** Thickness of a gutter, in px. Also the gap between two neighbouring tiles. */
export const LINKED_VIEW_GUTTER_PX = 4;

/** The least height, in px, the tile of a layout key keeps by default. */
export type FloorOf = (key: string) => number;

/** Every tile keeps `LINKED_VIEW_MIN_PANE_PX`. */
export const uniformFloor: FloorOf = () => LINKED_VIEW_MIN_PANE_PX;

const sumOf = (values: readonly number[]): number => values.reduce((a, b) => a + b, 0);

const positive = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0;

/**
 * The height, in px, `node` needs for every tile under it to keep its floor: a
 * stack adds its tiles and the gutters between them, parts side by side take
 * the tallest.
 */
export function paneNeedPx(
  node: SplitNode,
  floorOf: FloorOf = uniformFloor,
  gutterPx: number = LINKED_VIEW_GUTTER_PX,
): number {
  if (node.kind === 'leaf') {
    const floor = floorOf(node.key);
    return positive(floor) ? floor : 0;
  }
  const needs = node.children.map((c) => paneNeedPx(c, floorOf, gutterPx));
  return node.dir === 'row'
    ? needs.reduce((a, b) => Math.max(a, b), 0)
    : sumOf(needs) + (needs.length - 1) * gutterPx;
}

/** The height, in px, a whole tree needs: the linked view is never shorter. */
export function treeMinHeightPx(
  tree: SplitTree,
  floorOf: FloorOf = uniformFloor,
  gutterPx: number = LINKED_VIEW_GUTTER_PX,
): number {
  return paneNeedPx(tree.root, floorOf, gutterPx);
}

/** `sizes` rescaled to sum to `to`, proportions kept. */
function scaleSizes(sizes: readonly number[], to: number): number[] {
  const sum = sumOf(sizes);
  return sum > 0 ? sizes.map((s) => (s / sum) * to) : sizes.map(() => to / Math.max(1, sizes.length));
}

/**
 * `room` shared out in proportion to `weights`, no share under its floor: the
 * way a flex column with a `min-height` on each child does it. A share that
 * falls under its floor is frozen at it and the others split what is left,
 * again, until none is under. Null when the floors alone do not fit (no split
 * can honour them): the caller keeps the proportions.
 */
export function shareWithFloors(
  weights: readonly number[],
  floors: readonly number[],
  room: number,
): number[] | null {
  const n = weights.length;
  if (n === 0 || !(room > 0)) return null;
  const least = floors.map((f) => (positive(f) ? f : 0));
  if (sumOf(least) > room + EPS) return null;
  const weight = weights.map((w) => (positive(w) ? w : 0));
  const out = new Array<number>(n).fill(0);
  const frozen = new Array<boolean>(n).fill(false);
  let left = room;
  for (let round = 0; round <= n; round += 1) {
    const free: number[] = [];
    for (let i = 0; i < n; i += 1) if (!frozen[i]) free.push(i);
    if (free.length === 0) return out;
    const sum = free.reduce((a, i) => a + weight[i], 0);
    const share = (i: number) => (sum > 0 ? (left * weight[i]) / sum : left / free.length);
    const under = free.filter((i) => share(i) < least[i] - EPS);
    if (under.length === 0) {
      for (const i of free) out[i] = share(i);
      return out;
    }
    for (const i of under) {
      out[i] = least[i];
      frozen[i] = true;
      left -= least[i];
    }
  }
  return out;
}

/**
 * `tree` with its stacks' sizes bent so that, at `heightPx`, every tile keeps
 * its floor: the sizes of each column split become the shares
 * `shareWithFloors` gives. Rows (widths) are never touched. A stack whose floors
 * do not fit is left in proportion. Every split keeps the total it had, and the
 * parts of a split across a stack are rescaled to the room the stack gave them,
 * so the tree still describes one rectangle.
 */
export function floorTree(
  tree: SplitTree,
  heightPx: number,
  floorOf: FloorOf = uniformFloor,
  gutterPx: number = LINKED_VIEW_GUTTER_PX,
): SplitTree {
  if (!(heightPx > 0) || !(tree.h > 0)) return tree;
  const walk = (node: SplitNode, units: number, px: number): SplitNode => {
    if (node.kind === 'leaf') return node;
    if (node.dir === 'row') {
      return { ...node, children: node.children.map((c) => walk(c, units, px)) };
    }
    const room = px - (node.children.length - 1) * gutterPx;
    if (!(room > 0) || !(units > 0)) return node;
    const unitPx = room / units;
    const floors = node.children.map((c) => paneNeedPx(c, floorOf, gutterPx) / unitPx);
    const sizes = shareWithFloors(node.sizes, floors, units) ?? scaleSizes(node.sizes, units);
    return {
      ...node,
      sizes,
      children: node.children.map((c, i) => walk(c, sizes[i], sizes[i] * unitPx)),
    };
  };
  return { ...tree, root: walk(tree.root, tree.h, heightPx) };
}

/** The height, in px, each tile has when `tree` is laid out `heightPx` tall. */
export function leafHeights(
  tree: SplitTree,
  heightPx: number,
  gutterPx: number = LINKED_VIEW_GUTTER_PX,
): Map<string, number> {
  const out = new Map<string, number>();
  const walk = (node: SplitNode, px: number) => {
    if (node.kind === 'leaf') {
      out.set(node.key, px);
      return;
    }
    if (node.dir === 'row') {
      for (const c of node.children) walk(c, px);
      return;
    }
    const room = px - (node.children.length - 1) * gutterPx;
    const sum = sumOf(node.sizes);
    node.children.forEach((c, i) => walk(c, sum > 0 ? (room * node.sizes[i]) / sum : 0));
  };
  walk(tree.root, heightPx);
  return out;
}

/** How many px short of their floors the tiles of `tree` are in all, at
 *  `heightPx`. 0 for a tree that honours every floor. */
export function floorDeficit(
  tree: SplitTree,
  heightPx: number,
  floorOf: FloorOf = uniformFloor,
  gutterPx: number = LINKED_VIEW_GUTTER_PX,
): number {
  let short = 0;
  for (const [key, px] of leafHeights(tree, heightPx, gutterPx)) {
    const floor = floorOf(key);
    if (positive(floor) && px < floor) short += floor - px;
  }
  return short;
}

/** `delta` units applied to a gutter as far as `keeps` allows: when the full
 *  move leaves `keeps` false, it is shortened one unit at a time towards zero.
 *  The editor keeps a drag from taking a tile under its floor with this. */
export function moveGutterWithin(
  tree: SplitTree,
  path: readonly number[],
  gutter: number,
  delta: number,
  unit: SplitUnit,
  keeps: (next: SplitTree) => boolean,
): { tree: SplitTree; delta: number } {
  const first = moveGutterTree(tree, path, gutter, delta, unit);
  if (first.delta === 0 || keeps(first.tree)) return first;
  const sign = Math.sign(first.delta);
  for (let k = Math.ceil(Math.abs(first.delta)) - 1; k >= 1; k -= 1) {
    const shorter = moveGutterTree(tree, path, gutter, sign * k, unit);
    if (shorter.delta !== 0 && keeps(shorter.tree)) return shorter;
  }
  return { tree, delta: 0 };
}

// ---- Autofit: sizes from what the tiles ask for ---------------------------------
//
// Several renderers report the height their content reads best at (a content
// demand, `autofit.ts`), in px, keyed by the tile's component index: the layout
// key. Autofit gives each stack what its tiles ask for and lets the others
// share what is left.

/**
 * `tree` with each stack sized from the heights its tiles ask for, at
 * `heightPx`. In one column split, a tile with a known demand gets it and the
 * tiles without one share what is left in proportion to their stored sizes; if
 * every tile asks, the room is shared in proportion to what they ask for, so a
 * stack always fills its pane. Where the asks do not fit, they are scaled down
 * together; no tile goes under its floor. A tile stacked with nested tiles asks
 * for the sum of theirs (every one must know) or, beside others, the tallest.
 * Stacks where nothing is known, and all widths, keep their sizes.
 */
export function autofitTree(
  tree: SplitTree,
  heightPx: number,
  demandOf: (key: string) => number | null | undefined,
  floorOf: FloorOf = uniformFloor,
  gutterPx: number = LINKED_VIEW_GUTTER_PX,
): SplitTree {
  if (!(heightPx > 0) || !(tree.h > 0)) return tree;
  const demand = (node: SplitNode): number | null => {
    if (node.kind === 'leaf') {
      const d = demandOf(node.key);
      return positive(d) ? d : null;
    }
    const asks = node.children.map(demand);
    if (node.dir === 'row') {
      const known = asks.filter((d): d is number => d !== null);
      return known.length ? Math.max(...known) : null;
    }
    return asks.every((d) => d !== null)
      ? sumOf(asks as number[]) + (asks.length - 1) * gutterPx
      : null;
  };
  const walk = (node: SplitNode, units: number, px: number): SplitNode => {
    if (node.kind === 'leaf') return node;
    if (node.dir === 'row') {
      return { ...node, children: node.children.map((c) => walk(c, units, px)) };
    }
    const room = px - (node.children.length - 1) * gutterPx;
    if (!(room > 0) || !(units > 0)) return node;
    const asks = node.children.map(demand);
    const needs = node.children.map((c) => paneNeedPx(c, floorOf, gutterPx));
    const sum = sumOf(node.sizes);
    let shares: number[];
    if (asks.every((d) => d === null)) {
      shares = node.sizes.map((s) => (room * s) / sum);
    } else {
      const asked = sumOf(asks.filter((d): d is number => d !== null));
      const unaskedSize = sumOf(node.sizes.filter((_, i) => asks[i] === null));
      const left = room - asked;
      const wanted = asks.map((d, i) =>
        d !== null ? d : left > 0 && unaskedSize > 0 ? (left * node.sizes[i]) / unaskedSize : needs[i],
      );
      const wantedSum = sumOf(wanted);
      shares =
        shareWithFloors(wanted, needs, room) ?? wanted.map((w) => (room * w) / wantedSum);
    }
    const sizes = shares.map((p) => (p / room) * units);
    return { ...node, sizes, children: node.children.map((c, i) => walk(c, sizes[i], shares[i])) };
  };
  return { ...tree, root: walk(tree.root, tree.h, heightPx) };
}

// ---- Whole units, for the editor ------------------------------------------------

/**
 * `weights` as whole numbers that add up to `sum`, none under `least`, the
 * largest remainders rounded up first. For a stack that would not fit `least`
 * each (`sum` under `least * n`), the weights rounded.
 */
export function apportion(weights: readonly number[], sum: number, least = 1): number[] {
  const n = weights.length;
  const target = Math.round(sum);
  const weightSum = sumOf(weights);
  if (n === 0) return [];
  if (!(weightSum > 0) || target < n * least) return weights.map((w) => Math.max(0, Math.round(w)));
  const exact = weights.map((w) => (w / weightSum) * target);
  const out = exact.map((e) => Math.max(least, Math.floor(e + EPS)));
  let diff = target - sumOf(out);
  for (let guard = 0; diff !== 0 && guard < 4 * n + Math.abs(diff); guard += 1) {
    let pick = -1;
    let best = -Infinity;
    for (let i = 0; i < n; i += 1) {
      if (diff < 0 && out[i] <= least) continue;
      const remainder = diff > 0 ? exact[i] - out[i] : out[i] - exact[i];
      if (remainder > best) {
        best = remainder;
        pick = i;
      }
    }
    if (pick < 0) break;
    out[pick] += diff > 0 ? 1 : -1;
    diff += diff > 0 ? -1 : 1;
  }
  return out;
}

/**
 * `tree` with every split's sizes as whole units, each split keeping its total:
 * what the editor writes into a layout (it stores whole rows and columns). A
 * tree of whole sizes comes back as it is.
 */
export function snapTree(tree: SplitTree): SplitTree {
  const walk = (node: SplitNode, units: number): SplitNode => {
    if (node.kind === 'leaf') return node;
    if (node.dir === 'row') {
      const sizes = apportion(node.sizes, sumOf(node.sizes));
      return { ...node, sizes, children: node.children.map((c) => walk(c, units)) };
    }
    const sizes = apportion(node.sizes, units);
    return { ...node, sizes, children: node.children.map((c, i) => walk(c, sizes[i])) };
  };
  return { ...tree, root: walk(tree.root, Math.round(tree.h)) };
}

/** Whether two trees are the same cut with the same sizes, give or take
 *  `tolerance` units. */
export function sameSizes(a: SplitTree, b: SplitTree, tolerance = 1e-6): boolean {
  if (splitSignature(a) !== splitSignature(b)) return false;
  const walk = (p: SplitNode, q: SplitNode): boolean => {
    if (p.kind === 'leaf' || q.kind === 'leaf') return p.kind === q.kind;
    if (p.sizes.some((s, i) => Math.abs(s - q.sizes[i]) > tolerance)) return false;
    return p.children.every((c, i) => walk(c, q.children[i]));
  };
  return walk(a.root, b.root);
}
