import { describe, expect, it } from 'vitest';

import {
  axisTicks,
  buildResidueAxis,
  chainSpans,
  indexRangeToSelection,
  isMultiChain,
  orderAxisRows,
  residueLabel,
  selectionToIndexRange,
  type AxisRow,
} from './axis';
import {
  cellAt,
  clickGesture,
  dragGesture,
  effectiveMode,
  hitTest,
  hoverIndex,
  paeLayout,
  PAE_GEOMETRY,
  sameRange,
} from './brush';

const row = (position: number, chain: string | null = null, value: number | null = null): AxisRow => ({
  position,
  chain,
  value,
});

describe('dragGesture', () => {
  it('snaps a diagonal drag to the smallest square on the diagonal holding it', () => {
    // Along the diagonal, either direction.
    expect(dragGesture({ i: 10, j: 10 }, { i: 50, j: 50 }, 'diagonal')).toEqual({
      kind: 'range',
      mode: 'diagonal',
      x: [10, 50],
      y: [10, 50],
    });
    expect(dragGesture({ i: 50, j: 50 }, { i: 10, j: 10 }, 'diagonal').x).toEqual([10, 50]);
    // Along a block's top edge: the block.
    expect(dragGesture({ i: 10, j: 10 }, { i: 12, j: 40 }, 'diagonal').x).toEqual([10, 40]);
    // Across the diagonal (anti-diagonal drag).
    expect(dragGesture({ i: 40, j: 5 }, { i: 5, j: 40 }, 'diagonal').y).toEqual([5, 40]);
    // Off the diagonal: the square spans both extents.
    expect(dragGesture({ i: 80, j: 10 }, { i: 90, j: 20 }, 'diagonal').x).toEqual([10, 90]);
  });

  it('keeps a rectangle drag as its scored (x) and aligned (y) extents', () => {
    expect(dragGesture({ i: 40, j: 120 }, { i: 12, j: 80 }, 'rectangle')).toEqual({
      kind: 'range',
      mode: 'rectangle',
      x: [80, 120],
      y: [12, 40],
    });
  });

  it('turns a shift-drag in diagonal mode into a rectangle', () => {
    expect(effectiveMode('diagonal', true)).toBe('rectangle');
    expect(effectiveMode('diagonal', false)).toBe('diagonal');
    expect(effectiveMode('rectangle', false)).toBe('rectangle');
    const g = dragGesture({ i: 40, j: 120 }, { i: 12, j: 80 }, 'diagonal', true);
    expect(g).toEqual({ kind: 'range', mode: 'rectangle', x: [80, 120], y: [12, 40] });
  });
});

describe('clicks and hovers', () => {
  it('picks the scored residue on a cell and the strip residue on a strip', () => {
    expect(clickGesture({ region: 'matrix', i: 3, j: 7 })).toEqual({ kind: 'residue', index: 7 });
    expect(clickGesture({ region: 'top', j: 4 })).toEqual({ kind: 'residue', index: 4 });
    expect(clickGesture({ region: 'left', i: 9 })).toEqual({ kind: 'residue', index: 9 });
    expect(clickGesture({ region: 'none' })).toBeNull();
  });

  it('publishes the scored residue on hover', () => {
    expect(hoverIndex({ region: 'matrix', i: 3, j: 7 })).toBe(7);
    expect(hoverIndex({ region: 'left', i: 9 })).toBe(9);
    expect(hoverIndex({ region: 'none' })).toBeNull();
  });

  it('compares ranges', () => {
    expect(sameRange([1, 2], [1, 2])).toBe(true);
    expect(sameRange([1, 2], [1, 3])).toBe(false);
    expect(sameRange(null, null)).toBe(true);
    expect(sameRange([1, 2], null)).toBe(false);
  });
});

describe('paeLayout and hitTest', () => {
  const g = PAE_GEOMETRY;
  it('fits a square beside the axes, strips and colour bar', () => {
    const l = paeLayout(500, 400, 100, true);
    const strip = g.strip + g.stripGap;
    const side = 400 - g.topPad - strip - g.xTicks - g.xTitle;
    expect(l.plot.w).toBe(side);
    expect(l.plot.h).toBe(side);
    expect(l.cell).toBeCloseTo(side / 100);
    expect(l.topStrip?.y).toBe(l.plot.y - strip);
    expect(l.leftStrip?.x).toBe(l.plot.x - strip);
    expect(l.bar.x).toBe(l.plot.x + side + g.barGap);
    expect(l.plot.x + side + g.barGap + g.barWidth + g.barLabels).toBeLessThanOrEqual(500);
    expect(paeLayout(500, 400, 100, false).topStrip).toBeNull();
  });

  it('finds the cell, the strips, or nothing under a point', () => {
    const l = paeLayout(500, 400, 100, true);
    const { x, y } = l.plot;
    const c = l.cell;
    expect(hitTest(l, 100, x + 7.5 * c, y + 2.5 * c)).toEqual({ region: 'matrix', i: 2, j: 7 });
    expect(hitTest(l, 100, x + 7.5 * c, l.topStrip!.y + 2)).toEqual({ region: 'top', j: 7 });
    expect(hitTest(l, 100, l.leftStrip!.x + 2, y + 3.5 * c)).toEqual({ region: 'left', i: 3 });
    expect(hitTest(l, 100, 1, 1)).toEqual({ region: 'none' });
  });

  it('clamps a drag that leaves the matrix to its edge', () => {
    const l = paeLayout(500, 400, 100, false);
    expect(cellAt(l, 100, l.plot.x + l.plot.w + 50, l.plot.y - 20)).toEqual({ i: 0, j: 99 });
  });
});

describe('residue axis: index to residue', () => {
  it('numbers the matrix from the residue table, positions ascending', () => {
    const rows = [row(3, null, 70), row(1, null, 95), row(2, null, 85)];
    const axis = buildResidueAxis(3, rows, { byChain: false });
    expect(axis.fromTable).toBe(true);
    expect(axis.residues.map((r) => r.position)).toEqual([1, 2, 3]);
    expect(axis.residues.map((r) => r.value)).toEqual([95, 85, 70]);
    expect(residueLabel(axis, 0)).toBe('1');
  });

  it('concatenates chains in table order, each in its own numbering', () => {
    const rows = [row(2, 'B'), row(1, 'B'), row(11, 'A'), row(10, 'A'), row(12, 'A')];
    const axis = buildResidueAxis(5, rows, { byChain: true });
    expect(axis.fromTable).toBe(true);
    expect(axis.chains).toEqual(['B', 'A']);
    expect(isMultiChain(axis)).toBe(true);
    expect(axis.residues.map((r) => `${r.chain}${r.position}`)).toEqual(['B1', 'B2', 'A10', 'A11', 'A12']);
    expect(residueLabel(axis, 2)).toBe('A 10');
    expect(chainSpans(axis)).toEqual([
      { chain: 'B', start: 0, end: 1 },
      { chain: 'A', start: 2, end: 4 },
    ]);
  });

  it('keeps a repeated residue once', () => {
    expect(orderAxisRows([row(1), row(1), row(2)], false)).toHaveLength(2);
  });

  it('falls back to 1..N without rows, or when the counts differ', () => {
    const none = buildResidueAxis(4, [], { byChain: false });
    expect(none.fromTable).toBe(false);
    expect(none.fallback).toBe('no_rows');
    expect(none.residues.map((r) => r.position)).toEqual([1, 2, 3, 4]);
    expect(none.residues.every((r) => r.value === null && r.chain === null)).toBe(true);
    const short = buildResidueAxis(4, [row(5, null, 90), row(6, null, 90)], { byChain: false });
    expect(short.fallback).toBe('length_mismatch');
    expect(short.tableLength).toBe(2);
    expect(short.residues.map((r) => r.position)).toEqual([1, 2, 3, 4]);
    // A complex without its chain column repeats positions: no match.
    const complex = [row(1, 'A'), row(2, 'A'), row(1, 'B'), row(2, 'B')];
    expect(buildResidueAxis(4, complex, { byChain: false }).fromTable).toBe(false);
    expect(buildResidueAxis(4, complex, { byChain: true }).fromTable).toBe(true);
  });
});

describe('residue axis: picks in and out', () => {
  const single = buildResidueAxis(5, [row(10), row(11), row(12), row(14), row(15)], { byChain: false });
  const complex = buildResidueAxis(
    6,
    [row(1, 'A'), row(2, 'A'), row(3, 'A'), row(1, 'B'), row(2, 'B'), row(3, 'B')],
    { byChain: true },
  );

  it('turns a diagonal range or a click into one position range', () => {
    expect(indexRangeToSelection(single, 1, 3)).toEqual({ chain: null, start: 11, end: 14, indices: [1, 3] });
    expect(indexRangeToSelection(single, 2, 2)).toEqual({ chain: null, start: 12, end: 12, indices: [2, 2] });
    // Without a table: index + 1.
    const plain = buildResidueAxis(10, null, { byChain: false });
    expect(indexRangeToSelection(plain, 4, 6)).toMatchObject({ start: 5, end: 7 });
  });

  it('clamps a range across chains to the chain holding most of it', () => {
    expect(indexRangeToSelection(complex, 1, 3)).toEqual({ chain: 'A', start: 2, end: 3, indices: [1, 2] });
    expect(indexRangeToSelection(complex, 2, 5)).toEqual({ chain: 'B', start: 1, end: 3, indices: [3, 5] });
    // A tie goes to the first chain.
    expect(indexRangeToSelection(complex, 2, 3)?.chain).toBe('A');
  });

  it('maps an incoming range back to indices', () => {
    expect(selectionToIndexRange(single, { start: 11, end: 14 })).toEqual([1, 3]);
    expect(selectionToIndexRange(single, { start: 13 })).toBeNull();
    expect(selectionToIndexRange(single, { start: 1, end: 100 })).toEqual([0, 4]);
    // A chain name means nothing without a chain column.
    expect(selectionToIndexRange(single, { start: 12, chain: 'Z' })).toEqual([2, 2]);
  });

  it('honours the chain of an incoming pick on a complex', () => {
    expect(selectionToIndexRange(complex, { start: 2, end: 3, chain: 'B' })).toEqual([4, 5]);
    expect(selectionToIndexRange(complex, { start: 2, end: 3, chain: 'A' })).toEqual([1, 2]);
    // No chain named: the first chain holding the residue.
    expect(selectionToIndexRange(complex, { start: 2 })).toEqual([1, 1]);
    expect(selectionToIndexRange(complex, { start: 2, chain: 'C' })).toBeNull();
  });

  it('round-trips a pick through the filters', () => {
    const sel = indexRangeToSelection(complex, 3, 5)!;
    expect(selectionToIndexRange(complex, sel)).toEqual(sel.indices);
  });
});

describe('axisTicks', () => {
  it('ticks residue numbers at a 1-2-5 step, far enough apart', () => {
    const axis = buildResidueAxis(100, null, { byChain: false });
    const ticks = axisTicks(axis, 4, 40);
    expect(ticks.map((t) => t.label)).toEqual(['10', '20', '30', '40', '50', '60', '70', '80', '90', '100']);
    expect(ticks[0].index).toBe(9);
  });

  it('ticks each chain in its own numbering', () => {
    const rows = [...Array.from({ length: 20 }, (_, k) => row(k + 1, 'A')), ...Array.from({ length: 20 }, (_, k) => row(k + 1, 'B'))];
    const axis = buildResidueAxis(40, rows, { byChain: true });
    const labels = axisTicks(axis, 10, 40).map((t) => t.label);
    expect(labels).toEqual(['5', '10', '15', '20', '5', '10', '15', '20']);
  });
});
