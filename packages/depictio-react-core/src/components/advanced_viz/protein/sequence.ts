/**
 * Pure helpers of the sequence strip: residue normalisation, the drawn span,
 * secondary-structure detection and runs, variant stacking. No DOM,
 * unit-tested in `sequence.test.ts`.
 */

import type { SecondaryStructure } from './residueColours';
import type { StripDomain, StripResidue, StripVariant } from './types';

/** Residues sorted by position, the first of any duplicated position kept. */
export function normaliseResidues(residues: readonly StripResidue[]): StripResidue[] {
  const seen = new Set<number>();
  const out: StripResidue[] = [];
  for (const r of residues) {
    const p = Number(r.position);
    if (!Number.isFinite(p) || seen.has(p)) continue;
    seen.add(p);
    out.push({ ...r, position: p });
  }
  return out.sort((a, b) => a.position - b.position);
}

/** First and last residue number any lane reaches; null when nothing is drawn. */
export function stripSpan(
  residues: readonly StripResidue[],
  domains: readonly StripDomain[] = [],
  variants: readonly StripVariant[] = [],
): { min: number; max: number } | null {
  let min = Infinity;
  let max = -Infinity;
  const take = (v: number) => {
    if (!Number.isFinite(v)) return;
    if (v < min) min = v;
    if (v > max) max = v;
  };
  for (const r of residues) take(r.position);
  for (const d of domains) {
    take(d.start);
    take(d.end);
  }
  for (const v of variants) take(v.position);
  if (min === Infinity) return null;
  // A sequence numbered from 1 starts its axis at 1 even when the first
  // drawn mark is further in, so a variant-only strip keeps its bearings.
  return { min: Math.min(min, 1), max };
}

/** DSSP and plain-word spellings of the secondary-structure classes. */
const SS_ALIASES: Readonly<Record<string, SecondaryStructure>> = {
  H: 'helix',
  G: 'helix',
  I: 'helix',
  P: 'helix',
  HELIX: 'helix',
  ALPHA: 'helix',
  E: 'strand',
  B: 'strand',
  STRAND: 'strand',
  SHEET: 'strand',
  BETA: 'strand',
  T: 'turn',
  S: 'turn',
  TURN: 'turn',
  BEND: 'turn',
  C: 'coil',
  L: 'coil',
  '-': 'coil',
  COIL: 'coil',
  LOOP: 'coil',
};

export function secondaryStructureOf(value: unknown): SecondaryStructure | null {
  if (value == null) return null;
  const key = String(value).trim().toUpperCase();
  return SS_ALIASES[key] ?? null;
}

/**
 * Whether a category lane holds secondary structure (every value a DSSP /
 * S4PRED class, at least one helix or strand), in which case it is drawn as
 * helix / strand / coil glyphs rather than as categorical blocks.
 */
export function looksLikeSecondaryStructure(values: Iterable<unknown>): boolean {
  let structured = false;
  let any = false;
  for (const v of values) {
    if (v == null || v === '') continue;
    const ss = secondaryStructureOf(v);
    if (!ss) return false;
    any = true;
    if (ss === 'helix' || ss === 'strand') structured = true;
  }
  return any && structured;
}

export interface Run<T> {
  start: number;
  end: number;
  value: T;
}

/** Consecutive residues sharing a value, as inclusive position runs. A gap in
 *  the numbering ends a run. */
export function runsOf<T>(
  residues: readonly StripResidue[],
  pick: (r: StripResidue) => T | null,
): Run<T>[] {
  const runs: Run<T>[] = [];
  let cur: Run<T> | null = null;
  for (const r of residues) {
    const v = pick(r);
    if (v == null) {
      cur = null;
      continue;
    }
    if (cur && cur.value === v && r.position === cur.end + 1) {
      cur.end = r.position;
    } else {
      cur = { start: r.position, end: r.position, value: v };
      runs.push(cur);
    }
  }
  return runs;
}

/** Variants grouped by position, the most frequent category first in each. */
export function stackVariants(
  variants: readonly StripVariant[],
): { position: number; variants: StripVariant[] }[] {
  const byPos = new Map<number, StripVariant[]>();
  for (const v of variants) {
    const p = Number(v.position);
    if (!Number.isFinite(p)) continue;
    const list = byPos.get(p);
    if (list) list.push(v);
    else byPos.set(p, [v]);
  }
  return Array.from(byPos.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([position, list]) => ({ position, variants: list }));
}

/** Finite min / max of the value lane, null when it has no value. */
export function valueExtent(residues: readonly StripResidue[]): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const r of residues) {
    const v = r.value;
    if (v == null || !Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo === Infinity ? null : [lo, hi];
}

/** Whether a lane title names AlphaFold's confidence score. */
export function isPlddtLabel(label: string | null | undefined): boolean {
  return Boolean(label && /p\s*lddt/i.test(label));
}
