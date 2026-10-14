/**
 * From a parsed backbone to the points of a Ramachandran plot.
 *
 * `molecule/backbone.ts` gives each chain's residues and the torsions they
 * define; this module keeps the residues with both phi and psi, classes them
 * (general, glycine, proline, pre-proline), filters them by class and joins the
 * bound residue table's value and category on. Pure: no React, no Plotly.
 */

import {
  isPeptideBonded,
  phiPsi,
  residueClass,
  type BackboneChains,
  type ResidueClass,
} from '../molecule/backbone';

export type { ResidueClass };

/** The four classes, in the order they are drawn and listed. */
export const RESIDUE_CLASSES: readonly ResidueClass[] = [
  'general',
  'glycine',
  'proline',
  'pre_proline',
];

export const CLASS_LABELS: Readonly<Record<ResidueClass, string>> = {
  general: 'General',
  glycine: 'Glycine',
  proline: 'Proline',
  pre_proline: 'Pre-proline',
};

/** One residue with both torsions defined. */
export interface TorsionPoint {
  chain: string;
  /** Author residue number. */
  position: number;
  /** Insertion code, '' when none. */
  insertionCode: string;
  /** Residue name as written in the file. */
  resName: string;
  oneLetter: string;
  /** Degrees, in (-180, 180]. */
  phi: number;
  psi: number;
  /** B-factor of the alpha carbon (pLDDT in a predicted model), null when absent. */
  bfactor: number | null;
  cls: ResidueClass;
}

/** What a backbone yields: the plottable residues and how many were not. */
export interface TorsionSet {
  points: TorsionPoint[];
  /** Residues the backbone listed, plottable or not. */
  residues: number;
  /** Residues left out for a missing phi or psi (chain ends, gaps, absent atoms). */
  withoutTorsions: number;
  /** Chains the backbone has, in file order. */
  chains: string[];
}

/**
 * The points of every chain of a backbone.
 *
 * A residue is plotted when it has both phi and psi, which drops each chain's
 * first and last residue and the neighbours of a chain break or a missing
 * atom. A residue's class looks at the next residue only through a peptide
 * bond, so a proline after a gap does not make its predecessor a pre-proline.
 */
export function torsionPoints(chains: BackboneChains): TorsionSet {
  const points: TorsionPoint[] = [];
  let residues = 0;
  for (const list of chains.values()) {
    const torsions = phiPsi(list);
    list.forEach((res, i) => {
      residues += 1;
      const { phi, psi } = torsions[i];
      if (phi === null || psi === null) return;
      const following = i + 1 < list.length ? list[i + 1] : null;
      const next = following && isPeptideBonded(res, following) ? following : null;
      points.push({
        chain: res.chain,
        position: res.position,
        insertionCode: res.insertionCode,
        resName: res.resName,
        oneLetter: res.oneLetter,
        phi,
        psi,
        bfactor: res.bfactor,
        cls: residueClass(res, next),
      });
    });
  }
  return {
    points,
    residues,
    withoutTorsions: residues - points.length,
    chains: Array.from(chains.keys()),
  };
}

/**
 * The points of the selected classes. `null`, `undefined`, an empty list or all
 * four classes keep everything (the same list is returned).
 */
export function filterByClass<T extends { cls: ResidueClass }>(
  points: readonly T[],
  classes: readonly ResidueClass[] | null | undefined,
): readonly T[] {
  if (!classes || classes.length === 0) return points;
  const wanted = new Set(classes);
  if (RESIDUE_CLASSES.every((c) => wanted.has(c))) return points;
  return points.filter((p) => wanted.has(p.cls));
}

/** A residue's number as the reader writes it: `45`, or `45A` with an insertion code. */
export function positionLabel(p: Pick<TorsionPoint, 'position' | 'insertionCode'>): string {
  return `${p.position}${p.insertionCode}`;
}

// ---------------------------------------------------------------------------
// The bound residue table
// ---------------------------------------------------------------------------

/** The columns of a bound residue row this module reads. */
export interface ResidueRowLike {
  chain: string | null;
  position: number | null;
  value: number | null;
  category: string | null;
}

/** A plot point with the bound table's value and category for its residue. */
export interface AnnotatedPoint extends TorsionPoint {
  value: number | null;
  category: string | null;
}

const rowKey = (chain: string | null | undefined, position: number): string =>
  `${chain ?? ''}:${position}`;

/**
 * Join the table's `value` and `category` onto the points.
 *
 * A row naming a chain matches that chain's residue; a row without one matches
 * the residue of that number on any chain. Where several rows share a residue
 * the largest value and the first category win (a variant table has several
 * rows per position). Points no row covers get nulls.
 */
export function annotatePoints(
  points: readonly TorsionPoint[],
  rows: readonly ResidueRowLike[],
): AnnotatedPoint[] {
  const values = new Map<string, number>();
  const categories = new Map<string, string>();
  for (const r of rows) {
    if (r.position === null) continue;
    const k = rowKey(r.chain, r.position);
    if (r.value !== null) values.set(k, Math.max(values.get(k) ?? -Infinity, r.value));
    if (r.category !== null && !categories.has(k)) categories.set(k, r.category);
  }
  const pick = <T>(map: Map<string, T>, p: TorsionPoint): T | null =>
    map.get(rowKey(p.chain, p.position)) ?? map.get(rowKey(null, p.position)) ?? null;
  return points.map((p) => ({ ...p, value: pick(values, p), category: pick(categories, p) }));
}

/** Column-oriented frame of the plotted residues, for the tile's data popover. */
export function pointsFrame(points: readonly TorsionPoint[]): Record<string, unknown[]> {
  return {
    chain: points.map((p) => p.chain),
    position: points.map((p) => p.position),
    residue: points.map((p) => p.resName),
    phi: points.map((p) => Math.round(p.phi * 10) / 10),
    psi: points.map((p) => Math.round(p.psi * 10) / 10),
    class: points.map((p) => CLASS_LABELS[p.cls]),
    bfactor: points.map((p) => p.bfactor),
  };
}
