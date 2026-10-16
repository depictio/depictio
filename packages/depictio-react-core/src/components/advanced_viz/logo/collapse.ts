/**
 * Which columns of the logo are drawn and where: a window over the profile,
 * runs of low-information states folded into narrow stubs, and ranges the
 * user hid by hand. Pure, unit-tested in `collapse.test.ts`.
 *
 * Everything here speaks column indices (the index into `profile.states`,
 * 0-based), never pixels of the screen and never residues. A stub stands for
 * the columns it covers, so a selection, a hover or a hit span keeps its
 * original coordinates: the panel maps them to pixels with the functions
 * below and back. `x` is relative to the first drawn column (the panel adds
 * its gutter and the scroll offset).
 */

/** Width of a collapsed run, CSS px, whatever the state width. */
export const STUB_PX = 14;

export interface StatesSegment {
  kind: 'states';
  /** First and last column index, inclusive. */
  start: number;
  end: number;
  x: number;
  w: number;
}

export interface StubSegment {
  kind: 'stub';
  start: number;
  end: number;
  x: number;
  w: number;
  /** `auto`: a low-information run; `manual`: a range hidden by the user. */
  source: 'auto' | 'manual';
  /** Stable name of an auto run (its first and last column). */
  key: string;
  /** How many columns it folds. */
  count: number;
}

export type ColumnSegment = StatesSegment | StubSegment;

/** Column index ranges hidden by hand, inclusive. */
export type HiddenRange = readonly [number, number];

export interface CollapseSpec {
  /** Match-state number of each column, ascending (`profile.states`). */
  states: readonly number[];
  /** 1-based state numbers; null is open on that side (the whole profile). */
  windowStart?: number | null;
  windowEnd?: number | null;
  /** Information per column, bits. Needed with `belowIc`. */
  information?: ArrayLike<number> | null;
  /** Fold runs whose every column is under this many bits; null folds nothing. */
  belowIc?: number | null;
  /** Shortest run that folds. */
  minRun?: number;
  hidden?: readonly HiddenRange[];
  /** Keys of auto runs the user opened. */
  expanded?: readonly string[];
}

/** The columns in order, before any pixel is known. */
export interface ColumnPlan {
  segments: Array<Omit<StatesSegment, 'x' | 'w'> | Omit<StubSegment, 'x' | 'w'>>;
  /** First and last column of the window, or -1 and -1 when it holds none. */
  first: number;
  last: number;
  /** Columns drawn as letters and stubs standing in for the rest. */
  shown: number;
  stubs: number;
}

export interface ColumnLayout {
  segments: ColumnSegment[];
  first: number;
  last: number;
  cw: number;
  /** Total width of the drawn columns, px. */
  width: number;
}

export const autoRunKey = (start: number, end: number): string => `${start}-${end}`;

/** Column index range of the window: the first column whose state is at least
 *  `windowStart` to the last whose state is at most `windowEnd`. */
export function windowIndices(
  states: readonly number[],
  windowStart: number | null | undefined,
  windowEnd: number | null | undefined,
): [number, number] | null {
  const m = states.length;
  let lo = 0;
  let hi = m - 1;
  if (windowStart != null) while (lo < m && states[lo] < windowStart) lo++;
  if (windowEnd != null) while (hi >= 0 && states[hi] > windowEnd) hi--;
  return lo <= hi ? [lo, hi] : null;
}

/** The segments (stubs and runs of letters) of the logo, independent of the
 *  state width, so the caller can fit the width to what remains. */
export function planColumns(spec: CollapseSpec): ColumnPlan {
  const m = spec.states.length;
  const win = windowIndices(spec.states, spec.windowStart, spec.windowEnd);
  const empty: ColumnPlan = { segments: [], first: -1, last: -1, shown: 0, stubs: 0 };
  if (!m || !win) return empty;
  const [lo, hi] = win;

  const manual = new Uint8Array(m);
  for (const [a, b] of spec.hidden ?? []) {
    const from = Math.max(lo, Math.min(a, b));
    const to = Math.min(hi, Math.max(a, b));
    for (let i = from; i <= to; i++) manual[i] = 1;
  }

  // Auto runs: maximal stretches under the threshold, not already hidden.
  // `autoKey[i]` names the run a column belongs to while it is folded.
  const autoKey: Array<string | null> = new Array(m).fill(null);
  const threshold = spec.belowIc;
  const info = spec.information;
  if (threshold != null && info) {
    const minRun = Math.max(1, Math.floor(spec.minRun ?? 4));
    const open = new Set(spec.expanded ?? []);
    let i = lo;
    while (i <= hi) {
      if (manual[i] || !(info[i] < threshold)) {
        i++;
        continue;
      }
      let j = i;
      while (j + 1 <= hi && !manual[j + 1] && info[j + 1] < threshold) j++;
      const key = autoRunKey(i, j);
      if (j - i + 1 >= minRun && !open.has(key)) for (let c = i; c <= j; c++) autoKey[c] = key;
      i = j + 1;
    }
  }

  const segments: ColumnPlan['segments'] = [];
  let shown = 0;
  let stubs = 0;
  let i = lo;
  while (i <= hi) {
    const key = manual[i] ? 'manual' : autoKey[i];
    let j = i;
    while (j + 1 <= hi && (manual[j + 1] ? 'manual' : autoKey[j + 1]) === key) j++;
    if (key == null) {
      segments.push({ kind: 'states', start: i, end: j });
      shown += j - i + 1;
    } else {
      segments.push({
        kind: 'stub',
        start: i,
        end: j,
        source: key === 'manual' ? 'manual' : 'auto',
        key: key === 'manual' ? `manual:${i}-${j}` : key,
        count: j - i + 1,
      });
      stubs++;
    }
    i = j + 1;
  }
  return { segments, first: lo, last: hi, shown, stubs };
}

/** Place a plan on the x axis at `cw` px per column; stubs keep `stubPx`. */
export function placeColumns(plan: ColumnPlan, cw: number, stubPx = STUB_PX): ColumnLayout {
  let x = 0;
  const segments: ColumnSegment[] = plan.segments.map((s) => {
    const w = s.kind === 'states' ? (s.end - s.start + 1) * cw : stubPx;
    const placed = { ...s, x, w } as ColumnSegment;
    x += w;
    return placed;
  });
  return { segments, first: plan.first, last: plan.last, cw, width: x };
}

/** The segment holding column `i`, or null outside the window. */
export function segmentOfIndex(layout: ColumnLayout, i: number): ColumnSegment | null {
  const segs = layout.segments;
  let lo = 0;
  let hi = segs.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const s = segs[mid];
    if (i < s.start) hi = mid - 1;
    else if (i > s.end) lo = mid + 1;
    else return s;
  }
  return null;
}

/** Left edge of column `i`; a column inside a stub shares the stub's left
 *  edge. Null outside the window. */
export function xOfIndex(layout: ColumnLayout, i: number): number | null {
  const s = segmentOfIndex(layout, i);
  if (!s) return null;
  return s.kind === 'states' ? s.x + (i - s.start) * layout.cw : s.x;
}

export interface IndexSpan {
  x0: number;
  x1: number;
  /** The span began before the window / ended after it (and was cut there). */
  clippedStart: boolean;
  clippedEnd: boolean;
}

/**
 * Pixel span of the columns `a..b` (any order). A stub at either end counts
 * whole, and stubs between are inside the span. Cut to the window; null when
 * none of the columns is in it.
 */
export function spanOfIndices(layout: ColumnLayout, a: number, b: number): IndexSpan | null {
  if (!layout.segments.length) return null;
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  if (hi < layout.first || lo > layout.last) return null;
  const from = Math.max(lo, layout.first);
  const to = Math.min(hi, layout.last);
  const sa = segmentOfIndex(layout, from)!;
  const sb = segmentOfIndex(layout, to)!;
  const x0 = sa.kind === 'states' ? sa.x + (from - sa.start) * layout.cw : sa.x;
  const x1 = sb.kind === 'states' ? sb.x + (to - sb.start + 1) * layout.cw : sb.x + sb.w;
  return { x0, x1, clippedStart: lo < layout.first, clippedEnd: hi > layout.last };
}

export interface ColumnHit {
  /** The column under the point (a stub's first column over a stub). */
  index: number;
  segment: ColumnSegment;
}

/** The inverse of `xOfIndex`: the column (or stub) under `x`, null outside. */
export function indexAtX(layout: ColumnLayout, x: number): ColumnHit | null {
  const segs = layout.segments;
  if (!segs.length || !(x >= 0) || x >= layout.width) return null;
  let lo = 0;
  let hi = segs.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (segs[mid].x <= x) lo = mid;
    else hi = mid - 1;
  }
  const s = segs[lo];
  if (s.kind === 'stub') return { index: s.start, segment: s };
  const index = Math.min(s.end, s.start + Math.max(0, Math.floor((x - s.x) / layout.cw)));
  return { index, segment: s };
}

/**
 * Left edge of the continuous column coordinate `u` (column `i` spans
 * `[i, i + 1)`): inside a stub the columns it folds share its width evenly,
 * and past either end of the window one column is `cw` wide. Unlike
 * `xOfIndex` it never returns null and is affine in the layout's `cw`, which
 * is what zoom sync solves a width from.
 */
export function xOfColumn(layout: ColumnLayout, u: number): number {
  const segs = layout.segments;
  if (!segs.length) return u * layout.cw;
  if (u <= layout.first) return (u - layout.first) * layout.cw;
  if (u >= layout.last + 1) return layout.width + (u - layout.last - 1) * layout.cw;
  const s = segmentOfIndex(layout, Math.floor(u));
  if (!s) return 0;
  if (s.kind === 'states') return s.x + (u - s.start) * layout.cw;
  return s.x + ((u - s.start) / (s.end - s.start + 1)) * s.w;
}

/** The inverse of `xOfColumn`: the continuous column coordinate at `x`. */
export function columnAtX(layout: ColumnLayout, x: number): number {
  const segs = layout.segments;
  const cw = layout.cw > 0 ? layout.cw : 1;
  if (!segs.length) return x / cw;
  if (x <= 0) return layout.first + x / cw;
  if (x >= layout.width) return layout.last + 1 + (x - layout.width) / cw;
  const hit = indexAtX(layout, x);
  if (!hit) return layout.first;
  const s = hit.segment;
  if (s.kind === 'states') return s.start + (x - s.x) / cw;
  return s.start + ((x - s.x) / s.w) * (s.end - s.start + 1);
}

/**
 * Columns a brush from `xA` to `xB` (any order, pixels from the first drawn
 * column; outside the grid clamps to its ends) covers: both ends are widened to
 * whole stubs, so the hidden columns under a stub are brushed too.
 */
export function extentAtX(layout: ColumnLayout, xA: number, xB: number): [number, number] | null {
  if (!layout.segments.length) return null;
  const clampX = (x: number) => Math.max(0, Math.min(layout.width - 1e-6, x));
  const lo = indexAtX(layout, clampX(Math.min(xA, xB)));
  const hi = indexAtX(layout, clampX(Math.max(xA, xB)));
  if (!lo || !hi) return null;
  return [lo.segment.kind === 'stub' ? lo.segment.start : lo.index, hi.segment.kind === 'stub' ? hi.segment.end : hi.index];
}

/** Segments that intersect the viewport `[scroll, scroll + viewport]`. */
export function visibleSegments(layout: ColumnLayout, scroll: number, viewport: number): ColumnSegment[] {
  return layout.segments.filter((s) => s.x + s.w >= scroll && s.x <= scroll + viewport);
}

/** Columns of a letters segment inside the viewport, plus `overscan` each side:
 *  `[first, last]` inclusive. */
export function columnsInView(
  layout: ColumnLayout,
  seg: StatesSegment,
  scroll: number,
  viewport: number,
  overscan = 1,
): [number, number] {
  const cw = layout.cw;
  const a = seg.start + Math.floor((scroll - seg.x) / cw) - overscan;
  const b = seg.start + Math.ceil((scroll + viewport - seg.x) / cw) + overscan - 1;
  return [Math.max(seg.start, a), Math.min(seg.end, b)];
}

/** Add a range to the hand-hidden ones, merging whatever it overlaps or touches. */
export function addHidden(hidden: readonly HiddenRange[], range: HiddenRange): HiddenRange[] {
  let lo = Math.min(range[0], range[1]);
  let hi = Math.max(range[0], range[1]);
  const kept: HiddenRange[] = [];
  for (const [a, b] of hidden) {
    if (b < lo - 1 || a > hi + 1) kept.push([a, b]);
    else {
      lo = Math.min(lo, a);
      hi = Math.max(hi, b);
    }
  }
  return [...kept, [lo, hi] as const].sort((p, q) => p[0] - q[0]);
}

export interface FoldState {
  hidden: readonly HiddenRange[];
  expanded: readonly string[];
}

/** The fold state after the user opens `stub`: a hand-hidden range is dropped,
 *  an auto run is remembered as opened. */
export function expandStub(state: FoldState, stub: StubSegment): FoldState {
  if (stub.source === 'manual') {
    return {
      hidden: state.hidden.filter(([a, b]) => Math.max(a, b) < stub.start || Math.min(a, b) > stub.end),
      expanded: state.expanded,
    };
  }
  return state.expanded.includes(stub.key)
    ? state
    : { hidden: state.hidden, expanded: [...state.expanded, stub.key] };
}
