import { describe, expect, it } from 'vitest';

import {
  buildSplitTree,
  gutterRange,
  minSpan,
  moveGutter,
  moveGutterTree,
  nodeAt,
  parseStoredSplit,
  resetGutter,
  sameFractions,
  serializeStoredSplit,
  splitSignature,
  treeFractions,
  treeLayouts,
  treeRects,
  withFractions,
  workbenchSplitStorageKey,
} from './workbenchSplit';
import type { SplitNode } from './workbenchSplit';

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
const familyWorkbench = [
  tile('families', 3, 0, 5, 4),
  tile('structure', 0, 0, 3, 9),
  tile('track', 3, 4, 5, 2),
  tile('msa', 3, 6, 5, 3),
];

// proteinfold (Structure): a table over the structure and a stack of three.
const foldWorkbench = [
  tile('table', 0, 0, 8, 2),
  tile('structure', 0, 2, 3, 7),
  tile('sequence', 3, 2, 5, 2),
  tile('profile', 3, 4, 5, 2),
  tile('rama', 3, 6, 5, 3),
];

// proteinannotator (Structure): a table over two side-by-side tiles.
const annotatorWorkbench = [
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
    const tree = buildSplitTree(familyWorkbench);
    expect(tree).not.toBeNull();
    expect([tree!.w, tree!.h]).toEqual([8, 9]);
    expect(shape(tree!.root)).toEqual({
      row: ['structure', { column: ['families', 'track', 'msa'], sizes: [4, 2, 3] }],
      sizes: [3, 5],
    });
  });

  it('puts a full-width table above the split it sits over', () => {
    const tree = buildSplitTree(foldWorkbench);
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
    const tree = buildSplitTree(annotatorWorkbench);
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
    const forward = buildSplitTree(familyWorkbench);
    const reversed = buildSplitTree([...familyWorkbench].reverse());
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
    const half = familyWorkbench.map((t) => ({ ...t, y: t.y * 2, h: t.h * 2 }));
    const tree = buildSplitTree(half);
    expect([tree!.w, tree!.h]).toEqual([8, 18]);
    expect(shape(tree!.root)).toEqual({
      row: ['structure', { column: ['families', 'track', 'msa'], sizes: [8, 4, 6] }],
      sizes: [3, 5],
    });
  });

  it('does not modify what it is given', () => {
    const input = familyWorkbench.map((t) => ({ ...t }));
    buildSplitTree(input);
    expect(input).toEqual(familyWorkbench);
  });
});

describe('treeRects / treeLayouts', () => {
  it('puts every tile back where the layout had it', () => {
    for (const layout of [familyWorkbench, foldWorkbench, annotatorWorkbench, grid2x2]) {
      const tree = buildSplitTree(layout)!;
      expect(geometry(treeLayouts(tree, layout))).toEqual(geometry(layout));
      expect(treeRects(tree).size).toBe(layout.length);
    }
  });

  it('keeps every other property of a tile', () => {
    const layout = familyWorkbench.map((t) => ({ ...t, static: false, moved: true }));
    const out = treeLayouts(buildSplitTree(layout)!, layout);
    expect(out.every((t) => t.static === false && t.moved === true)).toBe(true);
  });
});

describe('minSpan', () => {
  it('adds along the split axis and takes the larger across it', () => {
    const tree = buildSplitTree(familyWorkbench)!;
    // Structure (1) beside the stack (1 across): 2 columns; the stack is three tiles tall.
    expect(minSpan(tree.root, 'x')).toBe(2);
    expect(minSpan(tree.root, 'y')).toBe(3);
    expect(minSpan(tree.root, 'y', { x: 1, y: 2 })).toBe(6);
  });
});

describe('moveGutter', () => {
  it('moves the gutter between a tall tile and a stack of three: the whole stack follows', () => {
    const out = moveGutter(familyWorkbench, [], 0, 1);
    expect(geometry(out)).toEqual({
      structure: [0, 0, 4, 9],
      families: [4, 0, 4, 4],
      track: [4, 4, 4, 2],
      msa: [4, 6, 4, 3],
    });
  });

  it('moves it back the other way', () => {
    const out = moveGutter(familyWorkbench, [], 0, -2);
    expect(geometry(out)).toEqual({
      structure: [0, 0, 1, 9],
      families: [1, 0, 7, 4],
      track: [1, 4, 7, 2],
      msa: [1, 6, 7, 3],
    });
  });

  it('moves a gutter inside the stack: the tile above grows, the one below shrinks and shifts', () => {
    const out = moveGutter(familyWorkbench, [1], 0, 1);
    expect(geometry(out)).toEqual({
      structure: [0, 0, 3, 9],
      families: [3, 0, 5, 5],
      track: [3, 5, 5, 1],
      msa: [3, 6, 5, 3],
    });
  });

  it('moves the second gutter of the stack without touching the first', () => {
    const out = moveGutter(familyWorkbench, [1], 1, -1);
    expect(geometry(out)).toEqual({
      structure: [0, 0, 3, 9],
      families: [3, 0, 5, 4],
      track: [3, 4, 5, 1],
      msa: [3, 5, 5, 4],
    });
  });

  it('moves the gutter between a table and the split under it: both sides of the split follow', () => {
    const out = moveGutter(foldWorkbench, [], 0, 1);
    expect(geometry(out)).toEqual({
      table: [0, 0, 8, 3],
      structure: [0, 3, 3, 6],
      sequence: [3, 3, 5, 1],
      profile: [3, 4, 5, 2],
      rama: [3, 6, 5, 3],
    });
  });

  it('moves the vertical gutter under a table', () => {
    const out = moveGutter(annotatorWorkbench, [1], 0, 2);
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
    const wide = moveGutter(familyWorkbench, [], 0, -10);
    expect(wide.find((t) => t.i === 'structure')!.w).toBe(1);
    const far = moveGutter(familyWorkbench, [], 0, 10);
    // The stack keeps one column.
    expect(far.find((t) => t.i === 'structure')!.w).toBe(7);
    expect(far.find((t) => t.i === 'msa')!.w).toBe(1);

    const down = moveGutter(familyWorkbench, [1], 0, 10);
    // The track below the gutter keeps one row; the tile above takes the rest.
    expect(geometry(down)).toEqual({
      structure: [0, 0, 3, 9],
      families: [3, 0, 5, 5],
      track: [3, 5, 5, 1],
      msa: [3, 6, 5, 3],
    });
    const up = moveGutter(familyWorkbench, [1], 0, -10);
    expect(up.find((t) => t.i === 'families')!.h).toBe(1);
    expect(up.find((t) => t.i === 'track')!.h).toBe(5);
  });

  it('honours a larger unit: a stored row is two half rows on a read-only grid', () => {
    const half = familyWorkbench.map((t) => ({ ...t, y: t.y * 2, h: t.h * 2 }));
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
    expect(geometry(moveGutter(familyWorkbench, [], 0, 1.4)).structure).toEqual([0, 0, 4, 9]);
    expect(geometry(moveGutter(familyWorkbench, [], 0, 0.4)).structure).toEqual([0, 0, 3, 9]);
  });

  it('leaves every tile whole: the tiles still tile the same box', () => {
    for (const [layout, path, g, delta] of [
      [familyWorkbench, [1], 0, 1],
      [foldWorkbench, [], 0, -1],
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
    const layout = familyWorkbench.map((t) => ({ ...t, static: false }));
    const before = layout.map((t) => ({ ...t }));
    const out = moveGutter(layout, [], 0, 1);
    expect(layout).toEqual(before);
    expect(out.every((t) => t.static === false)).toBe(true);
    expect(out).not.toBe(layout);
  });

  it('returns the layout unchanged for a path or gutter that names nothing', () => {
    expect(moveGutter(familyWorkbench, [0], 0, 1)).toEqual(familyWorkbench); // a leaf
    expect(moveGutter(familyWorkbench, [5], 0, 1)).toEqual(familyWorkbench);
    expect(moveGutter(familyWorkbench, [], 4, 1)).toEqual(familyWorkbench);
    expect(moveGutter(familyWorkbench, [], -1, 1)).toEqual(familyWorkbench);
    expect(moveGutter(familyWorkbench, [], 0, 0)).toEqual(familyWorkbench);
    expect(moveGutter(familyWorkbench, [], 0, Number.NaN)).toEqual(familyWorkbench);
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
    const tree = buildSplitTree(familyWorkbench)!;
    // Structure (3 wide) may lose 2; the stack (5 wide, each tile 5) may lose 4.
    expect(gutterRange(tree, [], 0)).toEqual({ min: -2, max: 4 });
    // Families (4 tall) may lose 3; track (2 tall) may lose 1.
    expect(gutterRange(tree, [1], 0)).toEqual({ min: -3, max: 1 });
    expect(gutterRange(tree, [1], 1)).toEqual({ min: -1, max: 2 });
  });

  it('is nothing for a gutter that is not there', () => {
    const tree = buildSplitTree(familyWorkbench)!;
    expect(gutterRange(tree, [], 3)).toEqual({ min: 0, max: 0 });
    expect(gutterRange(tree, [0], 0)).toEqual({ min: 0, max: 0 });
  });
});

describe('moveGutterTree', () => {
  it('reports what it applied after clamping, and fractions are allowed', () => {
    const tree = buildSplitTree(familyWorkbench)!;
    const moved = moveGutterTree(tree, [], 0, 9);
    expect(moved.delta).toBe(4);
    const half = moveGutterTree(tree, [], 0, 0.5);
    expect(half.delta).toBe(0.5);
    const rect = treeRects(half.tree).get('structure')!;
    expect(rect.w).toBe(3.5);
  });

  it('returns the very same tree when nothing moves', () => {
    const tree = buildSplitTree(familyWorkbench)!;
    expect(moveGutterTree(tree, [], 0, 0).tree).toBe(tree);
    expect(moveGutterTree(tree, [3], 0, 1).tree).toBe(tree);
  });

  it('does not mutate the tree it is given', () => {
    const tree = buildSplitTree(familyWorkbench)!;
    const before = JSON.stringify(tree);
    moveGutterTree(tree, [1], 0, 1);
    expect(JSON.stringify(tree)).toBe(before);
  });
});

describe('personal positions', () => {
  const tree = buildSplitTree(familyWorkbench)!;

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
    expect(geometry(treeLayouts(odd, familyWorkbench))).toEqual(geometry(familyWorkbench));
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
    expect(workbenchSplitStorageKey('d1', 'Family workbench')).toBe(
      'depictio:workbench-split:d1:Family workbench',
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
    const tree = buildSplitTree(familyWorkbench)!;
    expect(nodeAt(tree.root, [])).toBe(tree.root);
    expect(nodeAt(tree.root, [0])).toEqual({ kind: 'leaf', key: 'structure' });
    expect((nodeAt(tree.root, [1]) as { dir: string }).dir).toBe('column');
    expect(nodeAt(tree.root, [1, 2])).toEqual({ kind: 'leaf', key: 'msa' });
    expect(nodeAt(tree.root, [0, 0])).toBeNull();
    expect(nodeAt(tree.root, [7])).toBeNull();
  });
});
