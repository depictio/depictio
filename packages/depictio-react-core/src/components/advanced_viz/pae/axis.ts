/**
 * The residue axis of a PAE matrix: which residue each matrix index is.
 *
 * A PAE file is a bare N x N matrix, indices 0..N-1, with no residue numbers
 * in it. The numbers come from the bound residue table: the rows of the entity
 * on screen, positions ascending, and on a complex (`chain_col` set) the
 * chains concatenated in the order the table first names them, which is the
 * order a predictor writes a multimer's chains in. Index k is the k-th residue
 * of that list. When the table has no rows for the entity, or its residue
 * count differs from N (a construct, a table narrowed by a dashboard filter,
 * a complex without its chain column), the axis falls back to 1..N, the
 * numbering of a single-chain prediction, and the tile says so.
 *
 * Every residue pick in and out goes through here: an index range becomes one
 * position range on one chain (the `residue_selection` contract), and an
 * incoming range or hover becomes the indices to shade. Pure, unit-tested in
 * `brush.test.ts`.
 */

import { rulerStep } from '../protein/canvas';

/** One residue table row of the entity on screen. */
export interface AxisRow {
  position: number;
  chain: string | null;
  /** pLDDT (or any per-residue score) for the strips. */
  value: number | null;
}

export type AxisResidue = AxisRow;

export type AxisFallback = 'no_rows' | 'length_mismatch';

export interface ResidueAxis {
  /** One residue per matrix index, length N. */
  residues: AxisResidue[];
  /** Numbered from the residue table (true) or 1..N (false). */
  fromTable: boolean;
  /** Distinct chains in axis order (empty without a chain column). */
  chains: string[];
  /** Why the axis fell back to 1..N; null when it did not. */
  fallback: AxisFallback | null;
  /** Residues the table gave for the entity (after de-duplication). */
  tableLength: number;
}

/**
 * The table rows in matrix order: grouped by chain in first-appearance order
 * when `byChain`, positions ascending within each group, a repeated
 * (chain, position) kept once.
 */
export function orderAxisRows(rows: readonly AxisRow[], byChain: boolean): AxisRow[] {
  const groups = new Map<string, AxisRow[]>();
  const seen = new Set<string>();
  for (const r of rows) {
    if (!Number.isFinite(r.position)) continue;
    const chain = byChain ? r.chain : null;
    const key = `${chain ?? ''}\u0000${r.position}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const g = chain ?? '';
    let list = groups.get(g);
    if (!list) {
      list = [];
      groups.set(g, list);
    }
    list.push({ position: r.position, chain, value: r.value });
  }
  const out: AxisRow[] = [];
  for (const list of groups.values()) {
    list.sort((a, b) => a.position - b.position);
    out.push(...list);
  }
  return out;
}

/** The axis of an `n`-residue matrix from the entity's table rows (null or
 *  empty when there are none). */
export function buildResidueAxis(
  n: number,
  rows: readonly AxisRow[] | null | undefined,
  opts: { byChain: boolean },
): ResidueAxis {
  const ordered = rows && rows.length ? orderAxisRows(rows, opts.byChain) : [];
  if (ordered.length === n && n > 0) {
    const chains: string[] = [];
    for (const r of ordered) if (r.chain != null && !chains.includes(r.chain)) chains.push(r.chain);
    return { residues: ordered, fromTable: true, chains, fallback: null, tableLength: n };
  }
  const residues: AxisResidue[] = Array.from({ length: Math.max(0, n) }, (_, k) => ({
    position: k + 1,
    chain: null,
    value: null,
  }));
  return {
    residues,
    fromTable: false,
    chains: [],
    fallback: ordered.length ? 'length_mismatch' : 'no_rows',
    tableLength: ordered.length,
  };
}

/** More than one chain on the axis. */
export function isMultiChain(axis: ResidueAxis): boolean {
  return axis.chains.length > 1;
}

/** `45`, or `A 45` on a complex. */
export function residueLabel(axis: ResidueAxis, k: number): string {
  const r = axis.residues[k];
  if (!r) return '';
  return isMultiChain(axis) && r.chain != null ? `${r.chain} ${r.position}` : String(r.position);
}

/** A residue pick in the `residue_selection` contract's terms, with the
 *  matrix indices it covers once clamped to one chain. */
export interface AxisSelection {
  chain: string | null;
  start: number;
  end: number;
  /** First and last matrix index of the pick. */
  indices: [number, number];
}

/**
 * An inclusive index range as one position range: on a complex, the chain
 * holding most of the range (the first on a tie), the range clamped to it,
 * because a filter pairs one position range with one chain.
 */
export function indexRangeToSelection(
  axis: ResidueAxis,
  k0: number,
  k1: number,
): AxisSelection | null {
  const n = axis.residues.length;
  if (n === 0) return null;
  const lo = Math.max(0, Math.min(n - 1, Math.min(k0, k1)));
  const hi = Math.max(0, Math.min(n - 1, Math.max(k0, k1)));
  let first = lo;
  let last = hi;
  if (isMultiChain(axis)) {
    const counts = new Map<string, number>();
    const order: string[] = [];
    for (let k = lo; k <= hi; k++) {
      const c = axis.residues[k].chain ?? '';
      if (!counts.has(c)) order.push(c);
      counts.set(c, (counts.get(c) ?? 0) + 1);
    }
    let best = order[0];
    for (const c of order) if ((counts.get(c) ?? 0) > (counts.get(best) ?? 0)) best = c;
    first = -1;
    for (let k = lo; k <= hi; k++) {
      if ((axis.residues[k].chain ?? '') !== best) continue;
      if (first < 0) first = k;
      last = k;
    }
  }
  const a = axis.residues[first];
  const b = axis.residues[last];
  return {
    chain: a.chain,
    start: Math.min(a.position, b.position),
    end: Math.max(a.position, b.position),
    indices: [first, last],
  };
}

/**
 * The matrix indices of a residue range (a pick or a hover from anywhere),
 * or null when the axis holds none of it. A named chain restricts to that
 * chain; with none named on a complex, the first chain holding a residue of
 * the range is the one meant (as `chainToConcat` reads an MSA). Without a
 * chain column a chain name is ignored.
 */
export function selectionToIndexRange(
  axis: ResidueAxis,
  sel: { start: number; end?: number | null; chain?: string | null },
): [number, number] | null {
  const lo = Math.min(sel.start, sel.end ?? sel.start);
  const hi = Math.max(sel.start, sel.end ?? sel.start);
  const named = sel.chain != null && sel.chain !== '' && axis.chains.length > 0 ? sel.chain : null;
  let chain: string | null | undefined = named ?? undefined;
  let first = -1;
  let last = -1;
  for (let k = 0; k < axis.residues.length; k++) {
    const r = axis.residues[k];
    if (r.position < lo || r.position > hi) continue;
    if (chain === undefined) chain = r.chain;
    else if (axis.chains.length > 0 && r.chain !== chain) continue;
    if (first < 0) first = k;
    last = k;
  }
  return first < 0 ? null : [first, last];
}

/** A tick on a residue axis: the matrix index it sits on and its label. */
export interface AxisTick {
  index: number;
  label: string;
}

/**
 * Residue ticks at a 1-2-5 step (`rulerStep`) of residue numbers, at least
 * `minGapPx` apart on screen. The positions come from the axis, so a complex
 * restarting at 1 on its second chain ticks both chains in their own numbers.
 */
export function axisTicks(axis: ResidueAxis, pxPerIndex: number, minGapPx = 40): AxisTick[] {
  const step = rulerStep(pxPerIndex, minGapPx);
  const ticks: AxisTick[] = [];
  let lastIndex = -Infinity;
  for (let k = 0; k < axis.residues.length; k++) {
    const pos = axis.residues[k].position;
    if (pos % step !== 0) continue;
    if ((k - lastIndex) * pxPerIndex < minGapPx * 0.75) continue;
    ticks.push({ index: k, label: String(pos) });
    lastIndex = k;
  }
  return ticks;
}

/** First index of every chain after the first (where the boundary lines go),
 *  with every chain's span for its label. Empty for one chain. */
export function chainSpans(axis: ResidueAxis): { chain: string; start: number; end: number }[] {
  if (!isMultiChain(axis)) return [];
  const spans: { chain: string; start: number; end: number }[] = [];
  for (let k = 0; k < axis.residues.length; k++) {
    const c = axis.residues[k].chain ?? '';
    const lastSpan = spans[spans.length - 1];
    if (lastSpan && lastSpan.chain === c) lastSpan.end = k;
    else spans.push({ chain: c, start: k, end: k });
  }
  return spans;
}
