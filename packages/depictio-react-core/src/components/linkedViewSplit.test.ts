import { describe, expect, it } from 'vitest';

import { LINKED_VIEW_MIN_PANE_PX, fitRowPx, rowFloorPx } from './sectionGroups';
import {
  LINKED_VIEW_GUTTER_PX,
  apportion,
  autofitTree,
  buildSplitTree,
  floorDeficit,
  floorTree,
  gutterRange,
  leafHeights,
  minSpan,
  moveGutter,
  moveGutterTree,
  moveGutterWithin,
  nodeAt,
  paneNeedPx,
  parseStoredSplit,
  resetGutter,
  sameFractions,
  sameSizes,
  serializeStoredSplit,
  shareWithFloors,
  snapTree,
  splitSignature,
  treeFractions,
  treeLayouts,
  treeMinHeightPx,
  treeRects,
  uniformFloor,
  withFractions,
  linkedViewSplitStorageKey,
} from './linkedViewSplit';
import type { SplitNode, SplitTree } from './linkedViewSplit';

const tile = (i: string, x: number, y: number, w: number, h: number) => ({ i, x, y, w, h });
const geometry = (tiles: ReturnType<typeof tile>[]) =>
  Object.fromEntries(tiles.map((t) => [t.i, [t.x, t.y, t.w, t.h]]));

/** A tree reduced to its shape, to compare without spelling out every field. */
const shape = (node: SplitNode): unknown =>
  node.kind === 'leaf'
    ? node.key
    : { [node.dir]: node.children.map(shape), sizes: node.sizes };

// proteinfamilies (Family alignment, Profile HMM): a tall structure beside a
// stack of three.
const familyLinkedView = [
  tile('families', 3, 0, 5, 4),
  tile('structure', 0, 0, 3, 9),
  tile('track', 3, 4, 5, 2),
  tile('msa', 3, 6, 5, 3),
];

// proteinfold (Structure): a table over the structure and a stack of three.
const foldLinkedView = [
  tile('table', 0, 0, 8, 2),
  tile('structure', 0, 2, 3, 7),
  tile('sequence', 3, 2, 5, 2),
  tile('profile', 3, 4, 5, 2),
  tile('rama', 3, 6, 5, 3),
];

// proteinannotator (Structure): a table over two side-by-side tiles.
const annotatorLinkedView = [
  tile('table', 0, 0, 8, 3),
  tile('structure', 0, 3, 3, 5),
  tile('sequence', 3, 3, 5, 5),
];

const grid2x2 = [
  tile('a', 0, 0, 4, 4),
  tile('b', 4, 0, 4, 4),
  tile('c', 0, 4, 4, 4),
  tile('d', 4, 4, 4, 4),
];

describe('buildSplitTree', () => {
  it('cuts a tall tile and a stack of three into one row over one column of three', () => {
    const tree = buildSplitTree(familyLinkedView);
    expect(tree).not.toBeNull();
    expect([tree!.w, tree!.h]).toEqual([8, 9]);
    expect(shape(tree!.root)).toEqual({
      row: ['structure', { column: ['families', 'track', 'msa'], sizes: [4, 2, 3] }],
      sizes: [3, 5],
    });
  });

  it('puts a full-width table above the split it sits over', () => {
    const tree = buildSplitTree(foldLinkedView);
    expect(shape(tree!.root)).toEqual({
      column: [
        'table',
        {
          row: ['structure', { column: ['sequence', 'profile', 'rama'], sizes: [2, 2, 3] }],
          sizes: [3, 5],
        },
      ],
      sizes: [2, 7],
    });
  });

  it('splits a table over two side-by-side tiles', () => {
    const tree = buildSplitTree(annotatorLinkedView);
    expect(shape(tree!.root)).toEqual({
      column: ['table', { row: ['structure', 'sequence'], sizes: [3, 5] }],
      sizes: [3, 5],
    });
  });

  it('prefers the vertical cut: a 2x2 is two columns of two', () => {
    const tree = buildSplitTree(grid2x2);
    expect(shape(tree!.root)).toEqual({
      row: [
        { column: ['a', 'c'], sizes: [4, 4] },
        { column: ['b', 'd'], sizes: [4, 4] },
      ],
      sizes: [4, 4],
    });
  });

  it('keeps several cuts at one level in one multi-way split', () => {
    const tree = buildSplitTree([tile('a', 0, 0, 2, 3), tile('b', 2, 0, 3, 3), tile('c', 5, 0, 3, 3)]);
    expect(shape(tree!.root)).toEqual({ row: ['a', 'b', 'c'], sizes: [2, 3, 3] });
  });

  it('takes the order of the tiles from their positions, not from the array', () => {
    const forward = buildSplitTree(familyLinkedView);
    const reversed = buildSplitTree([...familyLinkedView].reverse());
    expect(shape(reversed!.root)).toEqual(shape(forward!.root));
  });

  it('is a single leaf for a single tile', () => {
    const tree = buildSplitTree([tile('only', 0, 0, 8, 4)]);
    expect(tree!.root).toEqual({ kind: 'leaf', key: 'only' });
  });

  it('is null for a pinwheel, whose cuts every tile straddles', () => {
    const pinwheel = [
      tile('a', 0, 0, 5, 2),
      tile('b', 5, 0, 3, 3),
      tile('c', 3, 3, 5, 2),
      tile('d', 0, 2, 3, 3),
      tile('e', 3, 2, 2, 1),
    ];
    // It does fill the box: the only thing wrong with it is that it cannot be cut.
    expect(pinwheel.reduce((area, t) => area + t.w * t.h, 0)).toBe(8 * 5);
    expect(buildSplitTree(pinwheel)).toBeNull();
  });

  it('is null for a layout with a hole in it', () => {
    expect(buildSplitTree([tile('a', 0, 0, 4, 2), tile('b', 4, 0, 4, 4)])).toBeNull();
    expect(buildSplitTree([tile('a', 0, 0, 3, 4), tile('b', 5, 0, 3, 4)])).toBeNull();
  });

  it('is null for a layout that does not span the grid from its top left', () => {
    expect(buildSplitTree([tile('a', 0, 0, 3, 4), tile('b', 3, 0, 3, 4)])).toBeNull();
    expect(buildSplitTree([tile('a', 2, 0, 3, 4), tile('b', 5, 0, 3, 4)])).toBeNull();
    expect(buildSplitTree([tile('a', 0, 1, 8, 4)])).toBeNull();
  });

  it('is null for tiles that overlap or share a key, and for nothing at all', () => {
    expect(buildSplitTree([tile('a', 0, 0, 8, 2), tile('b', 0, 1, 8, 2)])).toBeNull();
    expect(buildSplitTree([tile('a', 0, 0, 4, 2), tile('a', 4, 0, 4, 2)])).toBeNull();
    expect(buildSplitTree([])).toBeNull();
  });

  it('is null for tiles with no extent', () => {
    expect(buildSplitTree([tile('a', 0, 0, 0, 4), tile('b', 0, 0, 8, 4)])).toBeNull();
    expect(buildSplitTree([tile('a', 0, 0, 8, Number.NaN)])).toBeNull();
  });

  it('counts in half rows the way a read-only grid does', () => {
    const half = familyLinkedView.map((t) => ({ ...t, y: t.y * 2, h: t.h * 2 }));
    const tree = buildSplitTree(half);
    expect([tree!.w, tree!.h]).toEqual([8, 18]);
    expect(shape(tree!.root)).toEqual({
      row: ['structure', { column: ['families', 'track', 'msa'], sizes: [8, 4, 6] }],
      sizes: [3, 5],
    });
  });

  it('does not modify what it is given', () => {
    const input = familyLinkedView.map((t) => ({ ...t }));
    buildSplitTree(input);
    expect(input).toEqual(familyLinkedView);
  });
});

describe('treeRects / treeLayouts', () => {
  it('puts every tile back where the layout had it', () => {
    for (const layout of [familyLinkedView, foldLinkedView, annotatorLinkedView, grid2x2]) {
      const tree = buildSplitTree(layout)!;
      expect(geometry(treeLayouts(tree, layout))).toEqual(geometry(layout));
      expect(treeRects(tree).size).toBe(layout.length);
    }
  });

  it('keeps every other property of a tile', () => {
    const layout = familyLinkedView.map((t) => ({ ...t, static: false, moved: true }));
    const out = treeLayouts(buildSplitTree(layout)!, layout);
    expect(out.every((t) => t.static === false && t.moved === true)).toBe(true);
  });
});

describe('minSpan', () => {
  it('adds along the split axis and takes the larger across it', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    // Structure (1) beside the stack (1 across): 2 columns; the stack is three tiles tall.
    expect(minSpan(tree.root, 'x')).toBe(2);
    expect(minSpan(tree.root, 'y')).toBe(3);
    expect(minSpan(tree.root, 'y', { x: 1, y: 2 })).toBe(6);
  });
});

describe('moveGutter', () => {
  it('moves the gutter between a tall tile and a stack of three: the whole stack follows', () => {
    const out = moveGutter(familyLinkedView, [], 0, 1);
    expect(geometry(out)).toEqual({
      structure: [0, 0, 4, 9],
      families: [4, 0, 4, 4],
      track: [4, 4, 4, 2],
      msa: [4, 6, 4, 3],
    });
  });

  it('moves it back the other way', () => {
    const out = moveGutter(familyLinkedView, [], 0, -2);
    expect(geometry(out)).toEqual({
      structure: [0, 0, 1, 9],
      families: [1, 0, 7, 4],
      track: [1, 4, 7, 2],
      msa: [1, 6, 7, 3],
    });
  });

  it('moves a gutter inside the stack: the tile above grows, the one below shrinks and shifts', () => {
    const out = moveGutter(familyLinkedView, [1], 0, 1);
    expect(geometry(out)).toEqual({
      structure: [0, 0, 3, 9],
      families: [3, 0, 5, 5],
      track: [3, 5, 5, 1],
      msa: [3, 6, 5, 3],
    });
  });

  it('moves the second gutter of the stack without touching the first', () => {
    const out = moveGutter(familyLinkedView, [1], 1, -1);
    expect(geometry(out)).toEqual({
      structure: [0, 0, 3, 9],
      families: [3, 0, 5, 4],
      track: [3, 4, 5, 1],
      msa: [3, 5, 5, 4],
    });
  });

  it('moves the gutter between a table and the split under it: both sides of the split follow', () => {
    const out = moveGutter(foldLinkedView, [], 0, 1);
    expect(geometry(out)).toEqual({
      table: [0, 0, 8, 3],
      structure: [0, 3, 3, 6],
      sequence: [3, 3, 5, 1],
      profile: [3, 4, 5, 2],
      rama: [3, 6, 5, 3],
    });
  });

  it('moves the vertical gutter under a table', () => {
    const out = moveGutter(annotatorLinkedView, [1], 0, 2);
    expect(geometry(out)).toEqual({
      table: [0, 0, 8, 3],
      structure: [0, 3, 5, 5],
      sequence: [5, 3, 3, 5],
    });
  });

  it('moves a 2x2 as a whole by its vertical gutter', () => {
    const out = moveGutter(grid2x2, [], 0, -1);
    expect(geometry(out)).toEqual({
      a: [0, 0, 3, 4],
      b: [3, 0, 5, 4],
      c: [0, 4, 3, 4],
      d: [3, 4, 5, 4],
    });
  });

  it('moves one column of a 2x2 by its own horizontal gutter, and only that one', () => {
    const out = moveGutter(grid2x2, [0], 0, 1);
    expect(geometry(out)).toEqual({
      a: [0, 0, 4, 5],
      b: [4, 0, 4, 4],
      c: [0, 5, 4, 3],
      d: [4, 4, 4, 4],
    });
  });

  it('moves only the tiles against the gutter when a side is itself split', () => {
    // Left: a over c, each cut at a different column. Right: e.
    const layout = [
      tile('a', 0, 0, 2, 2),
      tile('b', 2, 0, 2, 2),
      tile('c', 0, 2, 3, 2),
      tile('d', 3, 2, 1, 2),
      tile('e', 4, 0, 4, 4),
    ];
    const tree = buildSplitTree(layout)!;
    expect(shape(tree.root)).toEqual({
      row: [
        {
          column: [
            { row: ['a', 'b'], sizes: [2, 2] },
            { row: ['c', 'd'], sizes: [3, 1] },
          ],
          sizes: [2, 2],
        },
        'e',
      ],
      sizes: [4, 4],
    });
    // The far edge of the left side moves: the tiles on it (b and d) take the
    // change, a and c keep their width.
    expect(geometry(moveGutter(layout, [], 0, 1))).toEqual({
      a: [0, 0, 2, 2],
      b: [2, 0, 3, 2],
      c: [0, 2, 3, 2],
      d: [3, 2, 2, 2],
      e: [5, 0, 3, 4],
    });
  });

  it('shifts and shrinks the tiles on the near edge of the side after the gutter', () => {
    const layout = [
      tile('e', 0, 0, 4, 4),
      tile('a', 4, 0, 2, 2),
      tile('b', 6, 0, 2, 2),
      tile('c', 4, 2, 3, 2),
      tile('d', 7, 2, 1, 2),
    ];
    // Moving the gutter right: a and c (against it) shrink and shift, b and d
    // (the far side) keep their size.
    expect(geometry(moveGutter(layout, [], 0, 1))).toEqual({
      e: [0, 0, 5, 4],
      a: [5, 0, 1, 2],
      b: [6, 0, 2, 2],
      c: [5, 2, 2, 2],
      d: [7, 2, 1, 2],
    });
  });

  it('keeps every tile at least one column and one row', () => {
    const wide = moveGutter(familyLinkedView, [], 0, -10);
    expect(wide.find((t) => t.i === 'structure')!.w).toBe(1);
    const far = moveGutter(familyLinkedView, [], 0, 10);
    // The stack keeps one column.
    expect(far.find((t) => t.i === 'structure')!.w).toBe(7);
    expect(far.find((t) => t.i === 'msa')!.w).toBe(1);

    const down = moveGutter(familyLinkedView, [1], 0, 10);
    // The track below the gutter keeps one row; the tile above takes the rest.
    expect(geometry(down)).toEqual({
      structure: [0, 0, 3, 9],
      families: [3, 0, 5, 5],
      track: [3, 5, 5, 1],
      msa: [3, 6, 5, 3],
    });
    const up = moveGutter(familyLinkedView, [1], 0, -10);
    expect(up.find((t) => t.i === 'families')!.h).toBe(1);
    expect(up.find((t) => t.i === 'track')!.h).toBe(5);
  });

  it('honours a larger unit: a stored row is two half rows on a read-only grid', () => {
    const half = familyLinkedView.map((t) => ({ ...t, y: t.y * 2, h: t.h * 2 }));
    const down = moveGutter(half, [1], 0, 100, { x: 1, y: 2 });
    expect(down.find((t) => t.i === 'track')!.h).toBe(2);
    const up = moveGutter(half, [1], 0, -100, { x: 1, y: 2 });
    expect(up.find((t) => t.i === 'families')!.h).toBe(2);
  });

  it('takes no more from a neighbour in a multi-way split than leaves it one unit', () => {
    const layout = [
      tile('e', 0, 0, 4, 4),
      tile('a', 4, 0, 2, 4),
      tile('b', 6, 0, 2, 4),
    ];
    // `a` lies against the gutter and has two columns: one to give.
    const out = moveGutter(layout, [], 0, 5);
    expect(geometry(out)).toEqual({ e: [0, 0, 5, 4], a: [5, 0, 1, 4], b: [6, 0, 2, 4] });
  });

  it('rounds to whole grid units', () => {
    expect(geometry(moveGutter(familyLinkedView, [], 0, 1.4)).structure).toEqual([0, 0, 4, 9]);
    expect(geometry(moveGutter(familyLinkedView, [], 0, 0.4)).structure).toEqual([0, 0, 3, 9]);
  });

  it('leaves every tile whole: the tiles still tile the same box', () => {
    for (const [layout, path, g, delta] of [
      [familyLinkedView, [1], 0, 1],
      [foldLinkedView, [], 0, -1],
      [grid2x2, [0], 0, 2],
    ] as const) {
      const out = moveGutter(layout, path, g, delta);
      const tree = buildSplitTree(out);
      expect(tree).not.toBeNull();
      expect(out.reduce((a, t) => a + t.w * t.h, 0)).toBe(
        layout.reduce((a, t) => a + t.w * t.h, 0),
      );
    }
  });

  it('keeps every other property and does not mutate its input', () => {
    const layout = familyLinkedView.map((t) => ({ ...t, static: false }));
    const before = layout.map((t) => ({ ...t }));
    const out = moveGutter(layout, [], 0, 1);
    expect(layout).toEqual(before);
    expect(out.every((t) => t.static === false)).toBe(true);
    expect(out).not.toBe(layout);
  });

  it('returns the layout unchanged for a path or gutter that names nothing', () => {
    expect(moveGutter(familyLinkedView, [0], 0, 1)).toEqual(familyLinkedView); // a leaf
    expect(moveGutter(familyLinkedView, [5], 0, 1)).toEqual(familyLinkedView);
    expect(moveGutter(familyLinkedView, [], 4, 1)).toEqual(familyLinkedView);
    expect(moveGutter(familyLinkedView, [], -1, 1)).toEqual(familyLinkedView);
    expect(moveGutter(familyLinkedView, [], 0, 0)).toEqual(familyLinkedView);
    expect(moveGutter(familyLinkedView, [], 0, Number.NaN)).toEqual(familyLinkedView);
  });

  it('returns the layout unchanged when it has no split tree', () => {
    const pinwheel = [
      tile('a', 0, 0, 5, 2),
      tile('b', 5, 0, 3, 3),
      tile('c', 3, 3, 5, 2),
      tile('d', 0, 2, 3, 3),
      tile('e', 3, 2, 2, 1),
    ];
    expect(moveGutter(pinwheel, [], 0, 1)).toEqual(pinwheel);
  });
});

describe('gutterRange', () => {
  it('is how far a gutter may go back and forward', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    // Structure (3 wide) may lose 2; the stack (5 wide, each tile 5) may lose 4.
    expect(gutterRange(tree, [], 0)).toEqual({ min: -2, max: 4 });
    // Families (4 tall) may lose 3; track (2 tall) may lose 1.
    expect(gutterRange(tree, [1], 0)).toEqual({ min: -3, max: 1 });
    expect(gutterRange(tree, [1], 1)).toEqual({ min: -1, max: 2 });
  });

  it('is nothing for a gutter that is not there', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    expect(gutterRange(tree, [], 3)).toEqual({ min: 0, max: 0 });
    expect(gutterRange(tree, [0], 0)).toEqual({ min: 0, max: 0 });
  });
});

describe('moveGutterTree', () => {
  it('reports what it applied after clamping, and fractions are allowed', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    const moved = moveGutterTree(tree, [], 0, 9);
    expect(moved.delta).toBe(4);
    const half = moveGutterTree(tree, [], 0, 0.5);
    expect(half.delta).toBe(0.5);
    const rect = treeRects(half.tree).get('structure')!;
    expect(rect.w).toBe(3.5);
  });

  it('returns the very same tree when nothing moves', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    expect(moveGutterTree(tree, [], 0, 0).tree).toBe(tree);
    expect(moveGutterTree(tree, [3], 0, 1).tree).toBe(tree);
  });

  it('does not mutate the tree it is given', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    const before = JSON.stringify(tree);
    moveGutterTree(tree, [1], 0, 1);
    expect(JSON.stringify(tree)).toBe(before);
  });
});

describe('personal positions', () => {
  const tree = buildSplitTree(familyLinkedView)!;

  it('names a tree by its shape and keys, not by its sizes', () => {
    const moved = moveGutterTree(tree, [], 0, 1).tree;
    expect(splitSignature(moved)).toBe(splitSignature(tree));
    expect(splitSignature(tree)).not.toBe(splitSignature(buildSplitTree(grid2x2)!));
    // A re-cut with the same tiles is another structure.
    const recut = buildSplitTree([
      tile('families', 0, 0, 4, 4),
      tile('structure', 4, 0, 4, 9),
      tile('track', 0, 4, 4, 2),
      tile('msa', 0, 6, 4, 3),
    ])!;
    expect(splitSignature(recut)).not.toBe(splitSignature(tree));
  });

  it('writes every split as shares of its extent', () => {
    const fractions = treeFractions(tree);
    expect(Object.keys(fractions).sort()).toEqual(['1', 'root']);
    expect(fractions.root).toEqual([3 / 8, 5 / 8]);
    expect(fractions['1']).toEqual([4 / 9, 2 / 9, 3 / 9]);
  });

  it('rebuilds the tree from its own fractions', () => {
    const again = withFractions(tree, treeFractions(tree));
    const a = treeRects(again);
    for (const [key, rect] of treeRects(tree)) {
      const r = a.get(key)!;
      expect([r.x, r.y, r.w, r.h].map((v) => Math.round(v * 1e6) / 1e6)).toEqual([
        rect.x,
        rect.y,
        rect.w,
        rect.h,
      ]);
    }
  });

  it('carries a drag across a reload: the fractions of a moved tree restore it', () => {
    const moved = moveGutterTree(tree, [1], 0, 1).tree;
    const restored = withFractions(tree, treeFractions(moved));
    const want = treeRects(moved);
    for (const [key, rect] of treeRects(restored)) {
      expect(rect.h).toBeCloseTo(want.get(key)!.h, 9);
      expect(rect.w).toBeCloseTo(want.get(key)!.w, 9);
    }
  });

  it('applies fractions to the extent the split has now', () => {
    // The same personal split on a section twice as tall: shares, not rows.
    const moved = moveGutterTree(tree, [1], 0, 1).tree;
    const taller = { ...tree, h: tree.h * 2, root: tree.root };
    const out = treeRects(withFractions(taller, treeFractions(moved)));
    expect(out.get('families')!.h).toBeCloseTo(2 * 5, 9);
    expect(out.get('structure')!.h).toBeCloseTo(18, 9);
  });

  it('ignores fractions that do not fit the split and keeps the dashboard proportions', () => {
    expect(withFractions(tree, null)).toBe(tree);
    const odd = withFractions(tree, { root: [0.5], '1': [0.5, 0.5, Number.NaN], other: [1] });
    expect(geometry(treeLayouts(odd, familyLinkedView))).toEqual(geometry(familyLinkedView));
    const tiny = withFractions(tree, { root: [0.001, 0.999] });
    expect(treeRects(tiny).get('structure')!.w).toBe(3);
  });

  it('compares fraction sets', () => {
    expect(sameFractions(treeFractions(tree), treeFractions(tree))).toBe(true);
    const moved = moveGutterTree(tree, [], 0, 1).tree;
    expect(sameFractions(treeFractions(tree), treeFractions(moved))).toBe(false);
    expect(sameFractions({ root: [0.5, 0.5] }, { root: [0.5, 0.25, 0.25] })).toBe(false);
  });

  it('puts one gutter back where the dashboard has it and leaves the others alone', () => {
    const dragged = moveGutterTree(moveGutterTree(tree, [], 0, 2).tree, [1], 1, -1).tree;
    const reset = resetGutter(dragged, tree, [], 0);
    expect(reset.delta).toBe(-2);
    const rects = treeRects(reset.tree);
    expect(rects.get('structure')!.w).toBe(3);
    // The gutter inside the stack was not reset.
    expect(rects.get('track')!.h).toBe(1);
    expect(rects.get('msa')!.h).toBe(4);
  });

  it('resets as a share of the split, whatever its extent has become', () => {
    const half = withFractions(tree, { root: [0.5, 0.5] });
    const reset = resetGutter(half, tree, [], 0);
    expect(treeRects(reset.tree).get('structure')!.w).toBeCloseTo(3, 9);
  });

  it('has nothing to reset at a gutter that is not there', () => {
    expect(resetGutter(tree, tree, [0], 0).delta).toBe(0);
    expect(resetGutter(tree, tree, [], 0).delta).toBe(0);
  });

  it('keys storage by dashboard and section', () => {
    expect(linkedViewSplitStorageKey('d1', 'Family linked view')).toBe(
      'depictio:linked-view-split:d1:Family linked view',
    );
  });

  it('stores and reads back the fractions of the structure they were stored for', () => {
    const fractions = treeFractions(moveGutterTree(tree, [], 0, 1).tree);
    const raw = serializeStoredSplit(splitSignature(tree), fractions);
    expect(parseStoredSplit(raw, splitSignature(tree))).toEqual(fractions);
  });

  it('reads nothing back for another structure, another version or garbage', () => {
    const fractions = treeFractions(tree);
    const raw = serializeStoredSplit(splitSignature(tree), fractions);
    expect(parseStoredSplit(raw, splitSignature(buildSplitTree(grid2x2)!))).toBeNull();
    expect(parseStoredSplit(raw.replace('"v":1', '"v":2'), splitSignature(tree))).toBeNull();
    expect(parseStoredSplit('not json', splitSignature(tree))).toBeNull();
    expect(parseStoredSplit(null, splitSignature(tree))).toBeNull();
    expect(parseStoredSplit('', splitSignature(tree))).toBeNull();
    expect(parseStoredSplit('[1]', splitSignature(tree))).toBeNull();
    const bad = JSON.stringify({ v: 1, sig: splitSignature(tree), fractions: { root: ['a'] } });
    expect(parseStoredSplit(bad, splitSignature(tree))).toBeNull();
  });
});

describe('nodeAt', () => {
  it('walks child indexes from the root', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    expect(nodeAt(tree.root, [])).toBe(tree.root);
    expect(nodeAt(tree.root, [0])).toEqual({ kind: 'leaf', key: 'structure' });
    expect((nodeAt(tree.root, [1]) as { dir: string }).dir).toBe('column');
    expect(nodeAt(tree.root, [1, 2])).toEqual({ kind: 'leaf', key: 'msa' });
    expect(nodeAt(tree.root, [0, 0])).toBeNull();
    expect(nodeAt(tree.root, [7])).toBeNull();
  });
});

// ---- Floors ----------------------------------------------------------------

const G = LINKED_VIEW_GUTTER_PX;
const FLOOR = LINKED_VIEW_MIN_PANE_PX;

/** Every tile of `tree` is placed inside the box and together they fill it: the
 *  tree still describes one rectangle after its sizes were bent. */
function expectOneRectangle(tree: SplitTree) {
  const rects = [...treeRects(tree).values()];
  expect(rects.reduce((a, r) => a + r.w * r.h, 0)).toBeCloseTo(tree.w * tree.h, 6);
  for (const r of rects) {
    expect(r.x).toBeGreaterThanOrEqual(-1e-9);
    expect(r.y).toBeGreaterThanOrEqual(-1e-9);
    expect(r.x + r.w).toBeLessThanOrEqual(tree.w + 1e-9);
    expect(r.y + r.h).toBeLessThanOrEqual(tree.h + 1e-9);
  }
}

describe('paneNeedPx / treeMinHeightPx', () => {
  it('adds the tiles of a stack and the gutters between them', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    expect(treeMinHeightPx(tree)).toBe(3 * FLOOR + 2 * G);
    // The stack is the tall side of the row.
    expect(paneNeedPx((tree.root as { children: SplitNode[] }).children[0])).toBe(FLOOR);
  });

  it('stacks a full-width table on top of the tallest side', () => {
    const tree = buildSplitTree(foldLinkedView)!;
    expect(treeMinHeightPx(tree)).toBe(FLOOR + G + 3 * FLOOR + 2 * G);
  });

  it('takes a tile of one part for the whole of a lone tile, and nothing for a tile with no floor', () => {
    expect(treeMinHeightPx(buildSplitTree([tile('only', 0, 0, 8, 4)])!)).toBe(FLOOR);
    const tree = buildSplitTree(foldLinkedView)!;
    const noTable = (key: string) => (key === 'table' ? 0 : FLOOR);
    expect(treeMinHeightPx(tree, noTable)).toBe(G + 3 * FLOOR + 2 * G);
    expect(uniformFloor('anything')).toBe(FLOOR);
  });

  it('is the same in half rows: the need is in px, not in units', () => {
    const half = familyLinkedView.map((t) => ({ ...t, y: t.y * 2, h: t.h * 2 }));
    expect(treeMinHeightPx(buildSplitTree(half)!)).toBe(treeMinHeightPx(buildSplitTree(familyLinkedView)!));
  });
});

describe('shareWithFloors', () => {
  it('shares in proportion when every share clears its floor', () => {
    expect(shareWithFloors([4, 2, 3], [0, 0, 0], 9)).toEqual([4, 2, 3]);
    expect(shareWithFloors([1, 1], [1, 1], 10)).toEqual([5, 5]);
  });

  it('freezes a share that falls under its floor and re-shares the rest', () => {
    // 4:2:3 of 10 is 4.44, 2.22, 3.33: the middle one is held at 3, the others
    // split the 7 left in 4:3.
    const out = shareWithFloors([4, 2, 3], [3, 3, 3], 10)!;
    expect(out[1]).toBe(3);
    expect(out[0]).toBeCloseTo(4, 9);
    expect(out[2]).toBeCloseTo(3, 9);
    expect(out.reduce((a, b) => a + b, 0)).toBeCloseTo(10, 9);
  });

  it('re-shares more than once: a freeze can push another share under its floor', () => {
    // 1:1:8 of 30 gives 3, 3, 24; the first two are held at 5, which leaves 20.
    expect(shareWithFloors([1, 1, 8], [5, 5, 0], 30)).toEqual([5, 5, 20]);
    // Holding the first at 6 leaves 6 for the others, which takes the third
    // under its 4.5: the second round catches it, and the middle one gets
    // what is left.
    const cascade = shareWithFloors([1, 5, 5], [6, 0, 4.5], 12)!;
    expect(cascade[0]).toBe(6);
    expect(cascade[1]).toBeCloseTo(1.5, 9);
    expect(cascade[2]).toBeCloseTo(4.5, 9);
  });

  it('is null when the floors alone do not fit', () => {
    expect(shareWithFloors([4, 2, 3], [4, 4, 4], 9)).toBeNull();
    expect(shareWithFloors([], [], 9)).toBeNull();
    expect(shareWithFloors([1], [0], 0)).toBeNull();
  });

  it('shares equally among tiles with no weight, and ignores garbage floors', () => {
    expect(shareWithFloors([0, 0], [0, 0], 8)).toEqual([4, 4]);
    expect(shareWithFloors([1, 1], [Number.NaN, -3], 8)).toEqual([4, 4]);
  });
});

describe('floorTree', () => {
  const family = buildSplitTree(familyLinkedView)!;
  const stack = (tree: SplitTree) => (tree.root as { children: SplitNode[] }).children[1] as {
    sizes: number[];
  };

  it('gives a stack of three its floors at exactly the height they need', () => {
    const need = treeMinHeightPx(family);
    const floored = floorTree(family, need);
    // 840 px over 9 units: 93.3 px a unit, so a floor is three units.
    for (const s of stack(floored).sizes) expect(s).toBeCloseTo(3, 9);
    expect(floorDeficit(floored, need)).toBe(0);
    // The stored proportions would have left the track a sliver.
    expect(floorDeficit(family, need)).toBeGreaterThan(90);
  });

  it('keeps the stored proportions where they already clear the floors', () => {
    const tall = floorTree(family, 4000);
    expect(stack(tall).sizes.map((s) => Math.round(s * 1000) / 1000)).toEqual([4, 2, 3]);
    expect(sameSizes(tall, family, 1e-9)).toBe(true);
  });

  it('holds only the tiles that fall short at their floor and shares the rest by proportion', () => {
    const floored = floorTree(family, 1000);
    const heights = leafHeights(floored, 1000);
    for (const key of ['families', 'track', 'msa']) {
      expect(heights.get(key)!).toBeGreaterThanOrEqual(FLOOR - 1e-6);
    }
    // The track is the one that was short: it sits on its floor.
    expect(heights.get('track')!).toBeCloseTo(FLOOR, 6);
    // The two others are still in their stored proportion, 4 to 3.
    expect(heights.get('families')! / heights.get('msa')!).toBeCloseTo(4 / 3, 6);
    expect(floorDeficit(floored, 1000)).toBeLessThan(1e-6);
  });

  it('leaves the widths and the total of every split alone', () => {
    const floored = floorTree(family, 1000);
    expect((floored.root as { sizes: number[] }).sizes).toEqual([3, 5]);
    expect(stack(floored).sizes.reduce((a, b) => a + b, 0)).toBeCloseTo(9, 9);
    expect([floored.w, floored.h]).toEqual([8, 9]);
    expectOneRectangle(floored);
  });

  it('leaves a stack in proportion when its floors cannot fit', () => {
    const short = floorTree(family, 600);
    expect(sameSizes(short, family, 1e-9)).toBe(true);
    expect(floorDeficit(short, 600)).toBeGreaterThan(0);
  });

  it('keeps nested stacks consistent: a part of a column is rescaled to the room it was given', () => {
    const fold = buildSplitTree(foldLinkedView)!;
    for (const height of [1132, 1300, 2000]) {
      const floored = floorTree(fold, height);
      expectOneRectangle(floored);
      expect(floorDeficit(floored, height)).toBeLessThan(1e-6);
    }
    // At the need, the table and each of the three tiles sit on their floors.
    const heights = leafHeights(floorTree(fold, 1132), 1132);
    for (const key of ['table', 'sequence', 'profile', 'rama']) {
      expect(heights.get(key)!).toBeCloseTo(FLOOR, 6);
    }
  });

  it('is the identity for a tree with no height to go by, and a lone tile', () => {
    expect(floorTree(family, 0)).toBe(family);
    const lone = buildSplitTree([tile('only', 0, 0, 8, 4)])!;
    expect(floorTree(lone, 500).root).toEqual(lone.root);
  });

  it('does not touch what it is given', () => {
    const before = JSON.stringify(family);
    floorTree(family, 1000);
    expect(JSON.stringify(family)).toBe(before);
  });

  it('honours a floor per tile', () => {
    const tree = buildSplitTree(foldLinkedView)!;
    const table = (key: string) => (key === 'table' ? 120 : FLOOR);
    const need = treeMinHeightPx(tree, table);
    expect(need).toBe(120 + G + 3 * FLOOR + 2 * G);
    const heights = leafHeights(floorTree(tree, need, table), need);
    expect(heights.get('table')!).toBeCloseTo(120, 6);
    expect(heights.get('rama')!).toBeCloseTo(FLOOR, 6);
  });
});

const ONE = { x: 1, y: 1 };

describe('the shipped linked views on a laptop', () => {
  // The rows the grid would pick: `fitRowPx` with the floor the tree asks for,
  // in whole rows (the editor, 100 px) and in half rows (a reader, 48 px).
  const cases: [string, ReturnType<typeof tile>[], number][] = [
    ['family', familyLinkedView, 9],
    ['fold', foldLinkedView, 9],
    ['annotator', annotatorLinkedView, 8],
  ];
  for (const [name, layout, rows] of cases) {
    for (const [mode, rowPx, scale] of [
      ['edit', 100, 1],
      ['view', 48, 2],
    ] as const) {
      it(`${name} (${mode}): every tile keeps its floor on a 640 px screen`, () => {
        const tiles = layout.map((t) => ({ ...t, y: t.y * scale, h: t.h * scale }));
        const tree = buildSplitTree(tiles)!;
        const need = treeMinHeightPx(tree);
        const row = fitRowPx(rows * scale, 640, 4, rowPx, 1, rowFloorPx(need, rows * scale, 4));
        const height = rows * scale * row + (rows * scale - 1) * 4;
        expect(height).toBeGreaterThanOrEqual(need);
        const floored = floorTree(tree, height);
        expect(floorDeficit(floored, height)).toBeLessThan(1e-6);
        for (const px of leafHeights(floored, height).values()) {
          expect(px).toBeGreaterThanOrEqual(FLOOR - 1e-6);
        }
      });
    }
  }

  it('needs more than the old fit gave a three-stack: three floors and two gutters', () => {
    const tree = buildSplitTree(familyLinkedView)!;
    const need = treeMinHeightPx(tree);
    const old = 9 * 67 + 8 * 4;
    expect(need).toBeGreaterThan(old);
    expect(need).toBe(3 * FLOOR + 2 * G);
  });
});

describe('moveGutterWithin', () => {
  const family = buildSplitTree(familyLinkedView)!;
  const height = 1000;
  const floored = floorTree(family, height);
  const keeps = (next: SplitTree) => floorDeficit(next, height) <= floorDeficit(floored, height) + 1e-6;

  it('stops a drag at the floor: the track is already on it, so it cannot give', () => {
    // Gutter 0 of the stack, between the plot and the track: growing the plot
    // would take from the track, which sits on its floor.
    const grown = moveGutterWithin(floored, [1], 0, 1, ONE, keeps);
    expect(grown.delta).toBe(0);
    expect(grown.tree).toBe(floored);
  });

  it('lets a drag go the other way, as far as the plot has room above its floor', () => {
    const shrunk = moveGutterWithin(floored, [1], 0, -1, ONE, keeps);
    expect(shrunk.delta).toBe(-1);
    expect(keeps(shrunk.tree)).toBe(true);
  });

  it('shortens a long drag one unit at a time instead of refusing it', () => {
    const far = moveGutterWithin(floored, [1], 0, -5, ONE, keeps);
    expect(far.delta).toBeLessThan(0);
    expect(far.delta).toBeGreaterThan(-5);
    expect(keeps(far.tree)).toBe(true);
    // One unit further would not have been kept.
    expect(keeps(moveGutterTree(floored, [1], 0, far.delta - 1).tree)).toBe(false);
  });

  it('is moveGutterTree when nothing is in the way', () => {
    const free = moveGutterWithin(family, [], 0, 1, ONE, () => true);
    expect(free).toEqual(moveGutterTree(family, [], 0, 1));
  });
});

describe('autofitTree', () => {
  const family = buildSplitTree(familyLinkedView)!;
  const demandOf = (map: Record<string, number>) => (key: string) => map[key];

  it('gives the tiles that ask what they ask for and the others what is left', () => {
    // 1100 px: 1092 for the stack. The plot and the track ask for 700; the
    // alignment has no ask and takes the 392 left.
    const out = autofitTree(family, 1100, demandOf({ families: 300, track: 400 }));
    const heights = leafHeights(out, 1100);
    expect(heights.get('families')).toBeCloseTo(300, 6);
    expect(heights.get('track')).toBeCloseTo(400, 6);
    expect(heights.get('msa')).toBeCloseTo(1092 - 700, 6);
    expectOneRectangle(out);
  });

  it('scales the asks to the room when every tile asks and they do not fit or leave a gap', () => {
    const asks = { families: 500, track: 300, msa: 200 };
    const heights = leafHeights(autofitTree(family, 1100, demandOf(asks)), 1100);
    const room = 1100 - 2 * G;
    // Room for 1000 asked: the stack still fills its pane, in the proportion asked.
    expect(heights.get('families')! + heights.get('track')! + heights.get('msa')!).toBeCloseTo(room, 6);
    expect(heights.get('families')! / heights.get('track')!).toBeCloseTo(500 / 300, 6);
  });

  it('keeps every tile on its floor when the asks would take it lower', () => {
    const asks = { families: 900, track: 100, msa: 100 };
    const out = autofitTree(family, 1100, demandOf(asks));
    expect(floorDeficit(out, 1100)).toBeLessThan(1e-6);
    const heights = leafHeights(out, 1100);
    expect(heights.get('track')!).toBeCloseTo(FLOOR, 6);
    expect(heights.get('families')! + heights.get('track')! + heights.get('msa')!).toBeCloseTo(
      1100 - 2 * G,
      6,
    );
  });

  it('leaves a stack alone when nothing in it asks, and never touches a width', () => {
    const out = autofitTree(family, 1100, () => undefined);
    expect(sameSizes(out, family, 1e-9)).toBe(true);
    const asked = autofitTree(family, 1100, demandOf({ families: 300 }));
    expect((asked.root as { sizes: number[] }).sizes).toEqual([3, 5]);
  });

  it('counts a nested stack as the sum of its tiles, and a side-by-side part as its tallest', () => {
    const fold = buildSplitTree(foldLinkedView)!;
    // The structure is not asked; the stack beside it asks for 3 x 320 + 2
    // gutters (968), the table 300, so the root stack asks for 1268 and the
    // 1272 px linked view has exactly that, less its one gutter.
    const out = autofitTree(
      fold,
      1272,
      demandOf({ table: 300, sequence: 320, profile: 320, rama: 320 }),
    );
    const heights = leafHeights(out, 1272);
    expect(heights.get('table')).toBeCloseTo(300, 6);
    expect(heights.get('sequence')).toBeCloseTo(320, 6);
    expect(heights.get('profile')).toBeCloseTo(320, 6);
    expectOneRectangle(out);
  });

  it('is the identity for a tree with no height to go by', () => {
    expect(autofitTree(family, 0, () => 300)).toBe(family);
  });
});

describe('apportion / snapTree', () => {
  it('rounds to whole numbers that keep the total', () => {
    expect(apportion([3.69, 2.54, 2.77], 9)).toEqual([4, 2, 3]);
    expect(apportion([1.5, 1.5, 1.5, 1.5], 6)).toHaveLength(4);
    expect(apportion([1.5, 1.5, 1.5, 1.5], 6).reduce((a, b) => a + b, 0)).toBe(6);
    expect(apportion([4, 2, 3], 9)).toEqual([4, 2, 3]);
  });

  it('never drops a part below one unit', () => {
    const out = apportion([0.1, 10], 8);
    expect(out.every((n) => n >= 1)).toBe(true);
    expect(out.reduce((a, b) => a + b, 0)).toBe(8);
  });

  it('rounds the weights when there is no room for one unit each', () => {
    expect(apportion([1, 1, 1], 2)).toEqual([1, 1, 1]);
    expect(apportion([], 5)).toEqual([]);
  });

  it('snaps a bent tree to whole units, each split keeping its total, and a whole tree to itself', () => {
    const family = buildSplitTree(familyLinkedView)!;
    const bent = floorTree(family, 1000);
    const snapped = snapTree(bent);
    const stack = (snapped.root as { children: SplitNode[] }).children[1] as { sizes: number[] };
    expect(stack.sizes.every(Number.isInteger)).toBe(true);
    expect(stack.sizes.reduce((a, b) => a + b, 0)).toBe(9);
    expect(sameSizes(snapTree(family), family)).toBe(true);
    const fold = snapTree(floorTree(buildSplitTree(foldLinkedView)!, 1300));
    expectOneRectangle(fold);
    for (const r of treeRects(fold).values()) {
      for (const v of [r.x, r.y, r.w, r.h]) expect(Number.isInteger(v)).toBe(true);
    }
  });

  it('writes back to a layout the editor can store', () => {
    const family = buildSplitTree(familyLinkedView)!;
    const out = treeLayouts(snapTree(floorTree(family, 1000)), familyLinkedView);
    for (const t of out) {
      for (const v of [t.x, t.y, t.w, t.h]) expect(Number.isInteger(v)).toBe(true);
    }
  });
});

describe('sameSizes', () => {
  const family = buildSplitTree(familyLinkedView)!;

  it('is true for the same cut and sizes, give or take a tolerance', () => {
    expect(sameSizes(family, family)).toBe(true);
    expect(sameSizes(family, moveGutterTree(family, [1], 0, 0.0000001).tree)).toBe(true);
    expect(sameSizes(family, moveGutterTree(family, [1], 0, 1).tree)).toBe(false);
    expect(sameSizes(family, moveGutterTree(family, [1], 0, 0.3).tree, 0.5)).toBe(true);
  });

  it('is false for another cut', () => {
    expect(sameSizes(family, buildSplitTree(grid2x2)!)).toBe(false);
  });
});
