/**
 * Geometry and gestures of the PAE panel: where the square plot, the pLDDT
 * strips and the colour bar sit in the canvas, which cell a pointer is over,
 * and what a drag or a click selects. All in matrix indices (0-based, i = row
 * = aligned residue, j = column = scored residue); `axis.ts` turns them into
 * residue numbers. Pure, unit-tested in `brush.test.ts`.
 */

export type BrushMode = 'diagonal' | 'rectangle';

/** A matrix cell: row i (aligned residue), column j (scored residue). */
export interface Cell {
  i: number;
  j: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Fixed furniture around the square, in CSS pixels. */
export const PAE_GEOMETRY = {
  /** Rotated "Aligned residue" title. */
  yTitle: 14,
  /** Y tick labels. */
  yTicks: 34,
  /** pLDDT strip thickness and its gap to the matrix. */
  strip: 8,
  stripGap: 3,
  /** Above everything: chain labels and the colour bar's title. */
  topPad: 18,
  /** X tick labels and the "Scored residue" title. */
  xTicks: 16,
  xTitle: 16,
  /** Colour bar: gap to the matrix, bar width, tick labels. */
  barGap: 10,
  barWidth: 10,
  barLabels: 32,
} as const;

export interface PaeLayout {
  width: number;
  height: number;
  /** The square matrix plot. */
  plot: Rect;
  /** CSS pixels per residue along either axis. */
  cell: number;
  /** pLDDT strip above the plot (scored residues), null when hidden. */
  topStrip: Rect | null;
  /** pLDDT strip left of the plot (aligned residues), null when hidden. */
  leftStrip: Rect | null;
  /** The colour bar, right of the plot. */
  bar: Rect;
}

/**
 * The largest square that fits the canvas once the axes, the strips and the
 * colour bar have their room, centred in what is left.
 */
export function paeLayout(width: number, height: number, n: number, withStrips: boolean): PaeLayout {
  const g = PAE_GEOMETRY;
  const strip = withStrips ? g.strip + g.stripGap : 0;
  const left = g.yTitle + g.yTicks + strip;
  const top = g.topPad + strip;
  const bottom = g.xTicks + g.xTitle;
  const right = g.barGap + g.barWidth + g.barLabels;
  const room = Math.min(width - left - right, height - top - bottom);
  const size = Math.max(0, Math.floor(room));
  const x = left + Math.max(0, Math.floor((width - left - right - size) / 2));
  const y = top + Math.max(0, Math.floor((height - top - bottom - size) / 2));
  const plot = { x, y, w: size, h: size };
  return {
    width,
    height,
    plot,
    cell: n > 0 ? size / n : 0,
    topStrip: withStrips ? { x, y: y - strip, w: size, h: g.strip } : null,
    leftStrip: withStrips ? { x: x - strip, y, w: g.strip, h: size } : null,
    bar: { x: x + size + g.barGap, y, w: g.barWidth, h: size },
  };
}

function inside(r: Rect | null, x: number, y: number): boolean {
  return r !== null && x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;
}

function indexAt(offset: number, cell: number, n: number): number {
  return Math.max(0, Math.min(n - 1, Math.floor(offset / cell)));
}

/** What the pointer is over. */
export type PaeHit =
  | { region: 'matrix'; i: number; j: number }
  | { region: 'top'; j: number }
  | { region: 'left'; i: number }
  | { region: 'none' };

export function hitTest(layout: PaeLayout, n: number, x: number, y: number): PaeHit {
  const { plot, cell } = layout;
  if (n <= 0 || cell <= 0) return { region: 'none' };
  if (inside(plot, x, y)) {
    return { region: 'matrix', i: indexAt(y - plot.y, cell, n), j: indexAt(x - plot.x, cell, n) };
  }
  if (inside(layout.topStrip, x, y)) return { region: 'top', j: indexAt(x - plot.x, cell, n) };
  if (inside(layout.leftStrip, x, y)) return { region: 'left', i: indexAt(y - plot.y, cell, n) };
  return { region: 'none' };
}

/** The cell under a point, clamped to the matrix: a drag that leaves the
 *  square keeps extending along its edge. */
export function cellAt(layout: PaeLayout, n: number, x: number, y: number): Cell {
  const { plot, cell } = layout;
  if (n <= 0 || cell <= 0) return { i: 0, j: 0 };
  return { i: indexAt(y - plot.y, cell, n), j: indexAt(x - plot.x, cell, n) };
}

/** What a gesture selects, in matrix indices. */
export type PaeGesture =
  /** A click on a cell or a strip: one residue (the scored one on a cell). */
  | { kind: 'residue'; index: number }
  /**
   * A drag. `x` is the scored range, the one emitted; `y` the aligned range,
   * kept as a local outline. Diagonal: both equal, the square [a, b]^2.
   */
  | { kind: 'range'; mode: BrushMode; x: [number, number]; y: [number, number] };

/** What a drag selects. */
export type PaeRangeGesture = Extract<PaeGesture, { kind: 'range' }>;

/** The brush mode a drag uses: shift turns a diagonal brush into a rectangle. */
export function effectiveMode(mode: BrushMode, shiftKey: boolean): BrushMode {
  return shiftKey ? 'rectangle' : mode;
}

/**
 * A drag from cell `a` to cell `b`.
 *
 * Diagonal: the smallest square on the diagonal holding the dragged rectangle,
 * [a, b] with a and b the lowest and highest index the drag touched on either
 * axis. A drag along a block on the diagonal, or across it, selects that
 * block: "select a domain". Rectangle: the scored (x) and aligned (y) extents
 * as they are.
 */
export function dragGesture(
  a: Cell,
  b: Cell,
  mode: BrushMode,
  shiftKey = false,
): PaeRangeGesture {
  const m = effectiveMode(mode, shiftKey);
  const x: [number, number] = [Math.min(a.j, b.j), Math.max(a.j, b.j)];
  const y: [number, number] = [Math.min(a.i, b.i), Math.max(a.i, b.i)];
  if (m === 'diagonal') {
    const lo = Math.min(x[0], y[0]);
    const hi = Math.max(x[1], y[1]);
    return { kind: 'range', mode: m, x: [lo, hi], y: [lo, hi] };
  }
  return { kind: 'range', mode: m, x, y };
}

/** A click: the scored residue j on a cell, that strip's residue on a pLDDT
 *  strip, nothing (null) elsewhere. */
export function clickGesture(hit: PaeHit): PaeGesture | null {
  switch (hit.region) {
    case 'matrix':
      return { kind: 'residue', index: hit.j };
    case 'top':
      return { kind: 'residue', index: hit.j };
    case 'left':
      return { kind: 'residue', index: hit.i };
    default:
      return null;
  }
}

/** The residue a hover publishes: the scored residue on a cell, the strip's
 *  residue on a strip. */
export function hoverIndex(hit: PaeHit): number | null {
  if (hit.region === 'matrix' || hit.region === 'top') return hit.j;
  if (hit.region === 'left') return hit.i;
  return null;
}

/** Two inclusive index ranges are the same (either may be null). */
export function sameRange(
  a: readonly [number, number] | null | undefined,
  b: readonly [number, number] | null | undefined,
): boolean {
  if (!a || !b) return !a && !b;
  return a[0] === b[0] && a[1] === b[1];
}
