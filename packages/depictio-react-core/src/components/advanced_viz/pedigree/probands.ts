/**
 * Which individual of a family the proband arrow points at, and the generation
 * numerals down the left of a tree. Pure, so the rules are unit-tested.
 */
import type { Person } from './pedigreeLayout';

/** A proband flag: 1, true, yes, or one of the words a samplesheet uses. */
export function parseProbandFlag(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  const text = String(value).trim().toLowerCase();
  return ['1', '1.0', 'true', 'yes', 'y', 'proband', 'index', 'self', 'p'].includes(text);
}

/**
 * The family's proband. The flagged individual when `probandColumn` is bound
 * and flags someone. Without a flag, an affected child (a person with a parent
 * in the table) who has no children of their own, else any affected child,
 * else the first affected person; null when nobody is affected. A guess only
 * places a marker, it never invents data.
 */
export function probandKeyOf(people: readonly Person[], probandColumn?: string | null): string | null {
  const real = people.filter((p) => !p.placeholder);
  if (probandColumn) {
    const flagged = real.find((p) => parseProbandFlag(p.row[probandColumn]));
    if (flagged) return flagged.key;
  }
  const known = new Set(real.map((p) => p.key));
  const isChild = (p: Person) =>
    (p.fatherKey !== null && known.has(p.fatherKey)) ||
    (p.motherKey !== null && known.has(p.motherKey));
  const parents = new Set<string>();
  for (const p of real) {
    if (p.fatherKey) parents.add(p.fatherKey);
    if (p.motherKey) parents.add(p.motherKey);
  }
  const affected = real.filter((p) => p.status === 'affected');
  return (
    affected.find((p) => isChild(p) && !parents.has(p.key)) ??
    affected.find(isChild) ??
    affected[0] ??
    null
  )?.key ?? null;
}

/** 1 -> "I", 4 -> "IV", 9 -> "IX": the generation numerals of a pedigree. */
export function romanNumeral(n: number): string {
  if (!Number.isFinite(n) || n < 1) return '';
  const table: Array<[number, string]> = [
    [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
    [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
  ];
  let rest = Math.floor(n);
  let out = '';
  for (const [value, glyph] of table) {
    while (rest >= value) {
      out += glyph;
      rest -= value;
    }
  }
  return out;
}

/** What a tree needs to be drawn at the tile's size. */
export interface FitInput {
  /** The drawing's own size, in its units. */
  contentW: number;
  contentH: number;
  /** The room the tile gives it, px; 0 while unmeasured. */
  availW: number;
  availH: number;
  /** Largest enlargement (symbols stop growing) and smallest reduction (below
   *  it the drawing scrolls instead of shrinking past reading). */
  maxScale?: number;
  minScale?: number;
}

export const FIT_MAX_SCALE = 2;
export const FIT_MIN_SCALE = 0.5;

/**
 * Scale that fits the drawing in the tile: as large as the room allows up to
 * `maxScale`, never below `minScale` (the tile scrolls then). 1 while the tile
 * is unmeasured.
 */
export function fitScale({
  contentW,
  contentH,
  availW,
  availH,
  maxScale = FIT_MAX_SCALE,
  minScale = FIT_MIN_SCALE,
}: FitInput): number {
  if (!(contentW > 0) || !(contentH > 0) || !(availW > 0) || !(availH > 0)) return 1;
  const fit = Math.min(availW / contentW, availH / contentH);
  return Math.min(maxScale, Math.max(minScale, fit));
}
