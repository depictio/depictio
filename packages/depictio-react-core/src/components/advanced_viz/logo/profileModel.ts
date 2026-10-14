/**
 * The logo's data model: one profile HMM (or an alignment read as one) as
 * per-state arrays the panel draws. Built from the long profile table of
 * `depictio/recipes/lib/hmm.py::profile_frame` (`profileFromRows`) or from the
 * rows of an MSA table (`profileFromMsa`). Pure, unit-tested in
 * `profileModel.test.ts`.
 */

import {
  columnProfiles,
  normaliseRows,
  referenceColumnMap,
  referenceIndexOf,
} from '../protein/alignment';
import { frameLength, numberOrNull, rowIndicesWhere, stringOrNull } from '../protein/rendererData';
import { isGap, schemeColour, type ColumnProfile, type RGB } from '../protein/residueColours';
import type { MsaRow, ResidueRange } from '../protein/types';
import { AMINO_ORDER, backgroundFor, detectAlphabet, type LogoAlphabet } from './heights';

type Frame = Record<string, unknown[]>;

export interface LogoProfile {
  source: 'hmm' | 'msa';
  /** The model shown (an `msa_id` in msa mode). */
  model: string | null;
  /** The reference sequence's entity: what a pick on the logo names. */
  entity: string | null;
  alphabet: LogoAlphabet;
  /** Letter of each emission column, upper case, in alphabet order. */
  letters: string[];
  background: number[];
  /** Match-state number of each state index, ascending (1-based). */
  states: number[];
  /** Reference residue number per state index; null on a reference deletion. */
  positions: (number | null)[];
  /** `emissions[i * letters.length + a]`, 0 to 1. */
  emissions: Float64Array;
  /** Per-state lanes; null when the table has no such column (or it is all null). */
  insertProb: (number | null)[] | null;
  insertLength: (number | null)[] | null;
  occupancy: (number | null)[] | null;
  consensus: (string | null)[] | null;
  rf: (string | null)[] | null;
  cs: (string | null)[] | null;
  /** msa mode: sequences the profile was counted over. */
  sequences?: number;
}

/** Column names of the profile table (`HmmLogoConfig`'s `*_col` fields). */
export interface ProfileColumns {
  entity?: string | null;
  position?: string | null;
  model?: string | null;
  state: string;
  letter: string;
  emission: string;
  insertProb?: string | null;
  insertLength?: string | null;
  occupancy?: string | null;
  consensus?: string | null;
  rf?: string | null;
  cs?: string | null;
}

/** Alphabet order: HMMER's for amino acids, then any stray letter; A-Z otherwise. */
export function sortLetters(letters: Iterable<string>, alphabet: LogoAlphabet): string[] {
  const unique = Array.from(new Set(Array.from(letters, (l) => l.toUpperCase()).filter(Boolean)));
  if (alphabet === 'nucleic') return unique.sort();
  const rank = (l: string) => {
    const i = AMINO_ORDER.indexOf(l);
    return i < 0 ? AMINO_ORDER.length : i;
  };
  return unique.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

const allNull = (values: readonly unknown[]): boolean => values.every((v) => v == null);

/**
 * The profile of `model` from the long table (one row per match state and
 * letter). Rows of other models are skipped (all rows when the frame has no
 * model column: the fetch was scoped, or the table holds one model). State-
 * level values repeat on every letter row; the first non-null one is kept.
 * Null when no row has a state number and a letter.
 */
export function profileFromRows(
  frame: Frame | null | undefined,
  cols: ProfileColumns,
  model: string | null,
): LogoProfile | null {
  if (!frame || frameLength(frame) === 0) return null;
  const rows = rowIndicesWhere(frame, cols.model, model);
  const stateCol = frame[cols.state] ?? [];
  const letterCol = frame[cols.letter] ?? [];
  const emissionCol = frame[cols.emission] ?? [];
  const col = (name: string | null | undefined) => (name ? frame[name] : undefined);
  const entityCol = col(cols.entity);
  const modelCol = col(cols.model);

  const stateSet = new Set<number>();
  const letterSet = new Set<string>();
  const kept: number[] = [];
  for (const r of rows) {
    const s = numberOrNull(stateCol[r]);
    const l = stringOrNull(letterCol[r]);
    if (s == null || l == null) continue;
    stateSet.add(Math.round(s));
    letterSet.add(l.toUpperCase());
    kept.push(r);
  }
  if (!kept.length) return null;

  const alphabet = detectAlphabet(letterSet);
  const letters = sortLetters(letterSet, alphabet);
  const letterIndex = new Map(letters.map((l, i) => [l, i]));
  const states = Array.from(stateSet).sort((a, b) => a - b);
  const stateIndex = new Map(states.map((s, i) => [s, i]));
  const m = states.length;
  const k = letters.length;
  const emissions = new Float64Array(m * k);

  const perState = <T>(name: string | null | undefined, read: (v: unknown) => T | null) => {
    const source = col(name);
    if (!source) return null;
    const out: (T | null)[] = new Array(m).fill(null);
    for (const r of kept) {
      const i = stateIndex.get(Math.round(Number(stateCol[r])))!;
      if (out[i] == null) out[i] = read(source[r]);
    }
    return allNull(out) ? null : out;
  };

  for (const r of kept) {
    const i = stateIndex.get(Math.round(Number(stateCol[r])))!;
    const a = letterIndex.get(String(letterCol[r]).toUpperCase())!;
    emissions[i * k + a] = numberOrNull(emissionCol[r]) ?? 0;
  }
  const positions = perState(cols.position, numberOrNull) ?? new Array<number | null>(m).fill(null);

  let entity: string | null = null;
  let modelName: string | null = model;
  for (const r of kept) {
    if (entity == null && entityCol) entity = stringOrNull(entityCol[r]);
    if (modelName == null && modelCol) modelName = stringOrNull(modelCol[r]);
    if (entity != null && modelName != null) break;
  }

  return {
    source: 'hmm',
    model: modelName,
    entity,
    alphabet,
    letters,
    background: backgroundFor(letters, alphabet),
    states,
    positions,
    emissions,
    insertProb: perState(cols.insertProb, numberOrNull),
    insertLength: perState(cols.insertLength, numberOrNull),
    occupancy: perState(cols.occupancy, numberOrNull),
    consensus: perState(cols.consensus, stringOrNull),
    rf: perState(cols.rf, stringOrNull),
    cs: perState(cols.cs, stringOrNull),
  };
}

/** `p7_hmm_SetConsensus`: the likeliest letter, upper case from 0.5 (0.9 for DNA/RNA). */
function consensusLetter(p: Float64Array, letters: readonly string[], alphabet: LogoAlphabet): string | null {
  let best = -1;
  for (let a = 0; a < p.length; a++) if (p[a] > 0 && (best < 0 || p[a] > p[best])) best = a;
  if (best < 0) return null;
  const threshold = alphabet === 'nucleic' ? 0.9 : 0.5;
  return p[best] >= threshold ? letters[best].toUpperCase() : letters[best].toLowerCase();
}

/**
 * The profile of an alignment, read the way `hmmbuild --hand` would read its
 * reference annotation: the match states are the reference row's residue
 * columns (rank 0, else the lowest rank, else the first row), numbered
 * 1..M, and the reference residue of state k is residue k.
 *
 * What is computed, per match column (plain counts: no sequence weighting
 * and no Dirichlet prior, so a shallow alignment overstates information):
 * - emission: share of each alphabet letter among the column's residues
 *   (letters outside the alphabet, such as X, are left out of the counts);
 * - occupancy: share of all rows with a residue in the column (1 minus the
 *   delete probability);
 * - insert probability after state k: among the rows with a residue at k,
 *   the share with at least one residue in the columns between k and k+1
 *   (the reference's gap columns), an estimate of `t_k(M->I)`;
 * - expected insert length after k: the mean number of inserted residues of
 *   those rows (null when no row inserts there);
 * - both are 0 after the last state, as `hmmlogo_IndelValues` reports;
 * - consensus: the likeliest letter (upper case from 0.5); RF: the reference
 *   row's own letter.
 */
export function profileFromMsa(
  rows: readonly MsaRow[],
  opts: { entity: string | null; model?: string | null },
): LogoProfile | null {
  const norm = normaliseRows(rows);
  if (!norm.rows.length || norm.width === 0) return null;
  const sequences = norm.rows.map((r) => r.sequence);
  const ref = sequences[referenceIndexOf(norm.rows)];
  const map = referenceColumnMap(ref);
  const m = map.residueCount;
  if (m === 0) return null;
  const matchCols = Array.from(map.resToCol);
  // Residue counts per column, upper-cased, gaps left out (alignment.ts).
  const profiles = columnProfiles(sequences, norm.width);

  const seen = new Set<string>();
  for (const c of matchCols) for (const l of Object.keys(profiles[c].counts)) seen.add(l);
  const alphabet = detectAlphabet(seen);
  const letters =
    alphabet === 'amino'
      ? AMINO_ORDER.split('')
      : seen.has('U') && !seen.has('T')
        ? ['A', 'C', 'G', 'U']
        : ['A', 'C', 'G', 'T'];
  const k = letters.length;
  const n = sequences.length;
  const emissions = new Float64Array(m * k);
  const occupancy: number[] = new Array(m).fill(0);
  const insertProb: (number | null)[] = new Array(m).fill(0);
  const insertLength: (number | null)[] = new Array(m).fill(0);
  const consensus: (string | null)[] = new Array(m).fill(null);
  const rf: (string | null)[] = new Array(m).fill(null);

  for (let i = 0; i < m; i++) {
    const c = matchCols[i];
    const column = profiles[c];
    let counted = 0;
    for (const l of letters) counted += column.counts[l] ?? 0;
    const p = emissions.subarray(i * k, (i + 1) * k);
    if (counted > 0) for (let a = 0; a < k; a++) p[a] = (column.counts[letters[a]] ?? 0) / counted;
    occupancy[i] = column.nonGap / n;
    consensus[i] = consensusLetter(p, letters, alphabet);
    rf[i] = ref[c].toUpperCase();

    if (i === m - 1) continue; // nothing after the last state (hmmlogo reports 0)
    const next = matchCols[i + 1];
    let inMatch = 0;
    let inserting = 0;
    let inserted = 0;
    for (const s of sequences) {
      const ch = s[c];
      if (ch === undefined || isGap(ch)) continue;
      inMatch += 1;
      let len = 0;
      for (let j = c + 1; j < next; j++) {
        const x = s[j];
        if (x !== undefined && !isGap(x)) len += 1;
      }
      if (len > 0) {
        inserting += 1;
        inserted += len;
      }
    }
    insertProb[i] = inMatch ? inserting / inMatch : 0;
    insertLength[i] = inserting ? inserted / inserting : null;
  }

  return {
    source: 'msa',
    model: opts.model ?? opts.entity,
    entity: opts.entity,
    alphabet,
    letters,
    background: backgroundFor(letters, alphabet),
    states: matchCols.map((_, i) => i + 1),
    positions: matchCols.map((c) => map.colToRes[c]),
    emissions,
    insertProb,
    insertLength,
    occupancy,
    consensus,
    rf,
    cs: null,
    sequences: n,
  };
}

// ---------------------------------------------------------------------------
// Residue <-> state arithmetic
// ---------------------------------------------------------------------------

/**
 * The reference residues a span of state indices covers: min..max of the
 * non-null positions in `[a, b]`. Null when every state there is a deletion
 * on the reference (a brush there picks nothing).
 */
export function residueRangeOfStates(
  positions: readonly (number | null)[],
  a: number,
  b: number,
): { start: number; end: number } | null {
  const lo = Math.max(0, Math.min(a, b));
  const hi = Math.min(positions.length - 1, Math.max(a, b));
  let start = Infinity;
  let end = -Infinity;
  for (let i = lo; i <= hi; i++) {
    const p = positions[i];
    if (p == null) continue;
    if (p < start) start = p;
    if (p > end) end = p;
  }
  return Number.isFinite(start) ? { start, end } : null;
}

/** The state indices whose reference residue falls in `range`: the first and
 *  last of them (deletions between included), or null when none does. */
export function stateSpanOfRange(
  positions: readonly (number | null)[],
  range: ResidueRange | null | undefined,
): [number, number] | null {
  if (!range) return null;
  const lo = Math.min(range.start, range.end ?? range.start);
  const hi = Math.max(range.start, range.end ?? range.start);
  let first = -1;
  let last = -1;
  for (let i = 0; i < positions.length; i++) {
    const p = positions[i];
    if (p == null || p < lo || p > hi) continue;
    if (first < 0) first = i;
    last = i;
  }
  return first < 0 ? null : [first, last];
}

/**
 * Column of a match-state number: its index when the profile has it, else
 * the index of the closest state below it (a filter can leave holes), clamped
 * to the profile. Hits speak HMM coordinates; the panel draws by index.
 */
export function stateColumnLookup(states: readonly number[]): (state: number) => number {
  if (!states.length) return () => 0;
  const first = states[0];
  const last = states[states.length - 1];
  const contiguous = last - first === states.length - 1;
  if (contiguous) {
    return (s) => Math.max(0, Math.min(states.length - 1, Math.round(s) - first));
  }
  return (s) => {
    const v = Math.round(s);
    let lo = 0;
    let hi = states.length - 1;
    if (v <= states[0]) return 0;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (states[mid] <= v) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  };
}

// ---------------------------------------------------------------------------
// Colours
// ---------------------------------------------------------------------------

/** A state's emissions as the column summary the context-aware residue
 *  schemes read (Clustal X classes, percent identity), with probabilities as
 *  fractional counts, so a logo letter gets the colour an MSA cell would. */
export function emissionColumnProfile(p: ArrayLike<number>, letters: readonly string[]): ColumnProfile {
  const counts: Record<string, number> = {};
  let total = 0;
  let best = -1;
  for (let a = 0; a < letters.length; a++) {
    const v = Number.isFinite(p[a]) && p[a] > 0 ? p[a] : 0;
    if (v <= 0) continue;
    counts[letters[a]] = (counts[letters[a]] ?? 0) + v;
    total += v;
    if (best < 0 || v > p[best]) best = a;
  }
  return {
    nonGap: total,
    counts,
    consensus: best >= 0 ? letters[best] : null,
    consensusFraction: total > 0 && best >= 0 ? p[best] / total : 0,
  };
}

/** Residue colour of every (state, letter) under `scheme`, `null` for an
 *  uncoloured letter: `colours[i * K + a]`. */
export function letterColours(profile: LogoProfile, scheme: string): (RGB | null)[] {
  const k = profile.letters.length;
  const m = profile.states.length;
  const out: (RGB | null)[] = new Array(m * k).fill(null);
  if (scheme === 'none') return out;
  for (let i = 0; i < m; i++) {
    const p = profile.emissions.subarray(i * k, (i + 1) * k);
    const column = emissionColumnProfile(p, profile.letters);
    for (let a = 0; a < k; a++) out[i * k + a] = schemeColour(scheme, profile.letters[a], column);
  }
  return out;
}

/** Letters of a state sorted by probability, highest first (tooltip). */
export function topLetters(
  profile: LogoProfile,
  index: number,
  limit = 4,
): { letter: string; p: number }[] {
  const k = profile.letters.length;
  const out: { letter: string; p: number }[] = [];
  for (let a = 0; a < k; a++) {
    const p = profile.emissions[index * k + a];
    if (p > 0) out.push({ letter: profile.letters[a], p });
  }
  out.sort((x, y) => y.p - x.p || x.letter.localeCompare(y.letter));
  return out.slice(0, limit);
}
