/**
 * Pure alignment arithmetic for the MSA panel: column to reference-residue
 * mapping, per-column profiles (consensus, Shannon conservation), identity per
 * row and the row order. No DOM, unit-tested in `alignment.test.ts`.
 */

import { isGap, type ColumnProfile } from './residueColours';
import type { ChainSegment, MsaRow, ResidueRange } from './types';

/** Alignment columns against the reference row's own residue numbering. */
export interface ReferenceMap {
  /** Per column: the reference residue number there, or -1 on a reference gap. */
  colToRes: Int32Array;
  /** Per residue number (index `res - firstResidue`): its column. */
  resToCol: Int32Array;
  firstResidue: number;
  /** Residues in the reference (its non-gap letters). */
  residueCount: number;
}

/**
 * Number the reference row's residues, skipping its gaps, so a column brush
 * can be reported in the coordinates of the residue and structure tables.
 * `firstResidue` is the number of the reference's first residue (1 unless the
 * alignment covers a fragment).
 */
export function referenceColumnMap(reference: string, firstResidue = 1): ReferenceMap {
  const colToRes = new Int32Array(reference.length).fill(-1);
  const resToCol: number[] = [];
  for (let c = 0; c < reference.length; c++) {
    if (isGap(reference[c])) continue;
    colToRes[c] = firstResidue + resToCol.length;
    resToCol.push(c);
  }
  return {
    colToRes,
    resToCol: Int32Array.from(resToCol),
    firstResidue,
    residueCount: resToCol.length,
  };
}

/**
 * The reference residues a column range covers: the first and last non-gap
 * reference column inside it. Null when the range holds reference gaps only.
 */
export function columnRangeToResidueRange(
  map: ReferenceMap,
  colA: number,
  colB: number,
): { start: number; end: number } | null {
  const lo = Math.max(0, Math.min(colA, colB));
  const hi = Math.min(map.colToRes.length - 1, Math.max(colA, colB));
  let start = -1;
  let end = -1;
  for (let c = lo; c <= hi; c++) {
    const r = map.colToRes[c];
    if (r < 0) continue;
    if (start < 0) start = r;
    end = r;
  }
  return start < 0 ? null : { start, end };
}

/** The column span of a residue range (clamped to the reference), or null when
 *  the range misses the reference entirely. */
export function residueRangeToColumnRange(
  map: ReferenceMap,
  range: ResidueRange,
): [number, number] | null {
  const n = map.residueCount;
  if (n === 0) return null;
  const a = Math.min(range.start, range.end ?? range.start);
  const b = Math.max(range.start, range.end ?? range.start);
  const lo = Math.max(a, map.firstResidue);
  const hi = Math.min(b, map.firstResidue + n - 1);
  if (lo > hi) return null;
  return [map.resToCol[lo - map.firstResidue], map.resToCol[hi - map.firstResidue]];
}

/** Per-column residue counts, consensus and consensus share. */
export function columnProfiles(sequences: readonly string[], width?: number): ColumnProfile[] {
  const w = width ?? sequences.reduce((m, s) => Math.max(m, s.length), 0);
  const out: ColumnProfile[] = [];
  for (let c = 0; c < w; c++) {
    const counts: Record<string, number> = {};
    let nonGap = 0;
    for (const s of sequences) {
      const ch = s[c];
      if (ch === undefined || isGap(ch)) continue;
      const up = ch.toUpperCase();
      counts[up] = (counts[up] ?? 0) + 1;
      nonGap += 1;
    }
    let consensus: string | null = null;
    let best = 0;
    for (const [letter, n] of Object.entries(counts)) {
      if (n > best || (n === best && consensus !== null && letter < consensus)) {
        consensus = letter;
        best = n;
      }
    }
    out.push({ nonGap, counts, consensus, consensusFraction: nonGap ? best / nonGap : 0 });
  }
  return out;
}

const LOG2_20 = Math.log2(20);

/**
 * Conservation of one column, 0 to 1: one minus the Shannon entropy of its
 * residues over log2(20), weighted by the share of rows that are not gaps
 * there, so a column that is one residue in two rows and gaps elsewhere does
 * not read as conserved.
 */
export function columnConservation(profile: ColumnProfile, rowCount: number): number {
  if (profile.nonGap === 0 || rowCount === 0) return 0;
  let h = 0;
  for (const n of Object.values(profile.counts)) {
    const p = n / profile.nonGap;
    h -= p * Math.log2(p);
  }
  const conserved = Math.max(0, 1 - h / LOG2_20);
  return conserved * (profile.nonGap / rowCount);
}

/**
 * Identity of `seq` to `reference`, 0 to 1: identical residues over the
 * columns where both have one. Null when they share no residue column.
 */
export function percentIdentity(seq: string, reference: string): number | null {
  const n = Math.min(seq.length, reference.length);
  let both = 0;
  let same = 0;
  for (let c = 0; c < n; c++) {
    const a = seq[c];
    const b = reference[c];
    if (isGap(a) || isGap(b)) continue;
    both += 1;
    if (a.toUpperCase() === b.toUpperCase()) same += 1;
  }
  return both ? same / both : null;
}

/** The reference row: rank 0 when a row has it, else the lowest rank, else the first row. */
export function referenceIndexOf(rows: readonly MsaRow[]): number {
  let best = -1;
  let bestRank = Infinity;
  rows.forEach((r, i) => {
    const rank = r.rank;
    if (rank != null && Number.isFinite(rank) && rank < bestRank) {
      best = i;
      bestRank = rank;
    }
  });
  return best >= 0 ? best : 0;
}

/**
 * Rows padded with gaps to the alignment width. A well-formed alignment has
 * rows of equal length; `ragged` says when it did not, so the renderer can
 * say so instead of drawing shifted columns silently.
 */
export function normaliseRows(rows: readonly MsaRow[]): {
  rows: MsaRow[];
  width: number;
  ragged: boolean;
} {
  const width = rows.reduce((m, r) => Math.max(m, r.sequence.length), 0);
  let ragged = false;
  const out = rows.map((r) => {
    if (r.sequence.length === width) return r;
    ragged = true;
    return { ...r, sequence: r.sequence.padEnd(width, '-') };
  });
  return { rows: out, width, ragged };
}

export type MsaSort = 'rank' | 'identity' | 'input';

/**
 * Display order: the reference first, then the others by rank, by identity to
 * the reference (highest first, computed where the table has none) or in input
 * order, capped at `maxRows` (the reference always kept). Returns the new
 * reference index, which is 0.
 */
export function orderMsaRows(
  rows: readonly MsaRow[],
  sortBy: MsaSort,
  maxRows: number,
): { rows: MsaRow[]; referenceIndex: number; total: number } {
  if (rows.length === 0) return { rows: [], referenceIndex: 0, total: 0 };
  const refIdx = referenceIndexOf(rows);
  const ref = rows[refIdx];
  const withIdentity = rows.map((r, i) => ({
    row: {
      ...r,
      identity:
        r.identity != null && Number.isFinite(r.identity)
          ? r.identity
          : i === refIdx
            ? 1
            : percentIdentity(r.sequence, ref.sequence),
    },
    input: i,
  }));
  const others = withIdentity.filter((e) => e.input !== refIdx);
  if (sortBy === 'rank') {
    others.sort((a, b) => {
      const ra = a.row.rank ?? Infinity;
      const rb = b.row.rank ?? Infinity;
      return ra === rb ? a.input - b.input : ra - rb;
    });
  } else if (sortBy === 'identity') {
    others.sort((a, b) => {
      const ia = a.row.identity ?? -1;
      const ib = b.row.identity ?? -1;
      return ia === ib ? a.input - b.input : ib - ia;
    });
  }
  const cap = Math.max(1, Math.floor(maxRows));
  const ordered = [withIdentity[refIdx].row, ...others.slice(0, cap - 1).map((e) => e.row)];
  return { rows: ordered, referenceIndex: 0, total: rows.length };
}

// ---------------------------------------------------------------------------
// Multi-chain references
// ---------------------------------------------------------------------------
//
// The reference row of a complex's alignment is its chains concatenated,
// while the residue and structure tables number each chain on its own (and
// not always from 1: ESMFold numbers the second chain on from the first). A
// chain layout lists the chains in concatenation order with their own first
// and last residue numbers, and the helpers below translate between the
// concatenated reference numbering (what the panel draws) and per-chain
// numbering (what the filters carry).

/** A chain segment placed on the concatenated reference (1-based). */
interface PlacedChain extends ChainSegment {
  /** Concatenated number of the chain's first residue. */
  offset: number;
}

/**
 * Parse a chain layout string: comma- or semicolon-separated
 * `<chain>:<first>-<last>` (own numbering) or `<chain>:<length>` (numbered
 * from 1), in concatenation order, e.g. `A:1-664,B:665-1004` or `A:664,B:340`.
 * Null for an empty or malformed layout.
 */
export function parseChainLayout(layout: string | null | undefined): ChainSegment[] | null {
  if (!layout || !layout.trim()) return null;
  const out: ChainSegment[] = [];
  for (const part of layout.split(/[,;]/)) {
    const m = part.trim().match(/^([^:\s]+)\s*:\s*(-?\d+)(?:\s*-\s*(-?\d+))?$/);
    if (!m) return null;
    const a = Number(m[2]);
    const seg =
      m[3] === undefined ? { chain: m[1], first: 1, last: a } : { chain: m[1], first: a, last: Number(m[3]) };
    if (!(seg.last >= seg.first)) return null;
    out.push(seg);
  }
  return out.length ? out : null;
}

function place(chains: readonly ChainSegment[]): PlacedChain[] {
  let offset = 1;
  return chains.map((c) => {
    const placed = { ...c, offset };
    offset += c.last - c.first + 1;
    return placed;
  });
}

/** Residues a layout covers, to check it against the reference row. */
export function chainLayoutLength(chains: readonly ChainSegment[]): number {
  return chains.reduce((s, c) => s + (c.last - c.first + 1), 0);
}

/** The chain and own number of a concatenated reference residue. */
export function concatToChain(
  position: number,
  chains: readonly ChainSegment[],
): { chain: string; position: number } | null {
  for (const c of place(chains)) {
    const local = c.first + (position - c.offset);
    if (local >= c.first && local <= c.last) return { chain: c.chain, position: local };
  }
  return null;
}

/**
 * The concatenated number of residue `position` of `chain`. With no chain
 * named, the first chain whose own numbering holds the position.
 */
export function chainToConcat(
  chain: string | null | undefined,
  position: number,
  chains: readonly ChainSegment[],
): number | null {
  for (const c of place(chains)) {
    if (chain != null && c.chain !== chain) continue;
    if (position >= c.first && position <= c.last) return c.offset + (position - c.first);
  }
  return null;
}

/**
 * A concatenated reference range as one chain's own range. A filter pairs one
 * position range with one chain, so a brush across a chain boundary is clamped
 * to the chain holding most of it (the first on a tie).
 */
export function concatRangeToChain(
  range: ResidueRange,
  chains: readonly ChainSegment[],
): { chain: string; start: number; end: number } | null {
  const lo = Math.min(range.start, range.end ?? range.start);
  const hi = Math.max(range.start, range.end ?? range.start);
  let best: { chain: string; start: number; end: number; n: number } | null = null;
  for (const c of place(chains)) {
    const cLo = c.offset;
    const cHi = c.offset + (c.last - c.first);
    const a = Math.max(lo, cLo);
    const b = Math.min(hi, cHi);
    if (a > b) continue;
    const n = b - a + 1;
    if (!best || n > best.n) {
      best = { chain: c.chain, start: c.first + (a - c.offset), end: c.first + (b - c.offset), n };
    }
  }
  return best ? { chain: best.chain, start: best.start, end: best.end } : null;
}

/** One chain's own range on the concatenated reference, clamped to the chain. */
export function chainRangeToConcat(
  chain: string | null | undefined,
  range: ResidueRange,
  chains: readonly ChainSegment[],
): ResidueRange | null {
  const lo = Math.min(range.start, range.end ?? range.start);
  const hi = Math.max(range.start, range.end ?? range.start);
  for (const c of place(chains)) {
    if (chain != null && c.chain !== chain) continue;
    const a = Math.max(lo, c.first);
    const b = Math.min(hi, c.last);
    if (a > b) continue;
    return { start: c.offset + (a - c.first), end: c.offset + (b - c.first) };
  }
  return null;
}

/** Chain boundaries on the concatenated reference, for the ruler. */
export function chainStarts(chains: readonly ChainSegment[]): { chain: string; offset: number }[] {
  return place(chains).map((c) => ({ chain: c.chain, offset: c.offset }));
}
