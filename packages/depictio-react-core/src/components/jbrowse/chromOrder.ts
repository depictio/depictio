/**
 * Chromosomes in the order the reference's own convention gives them, whatever
 * the organism. UCSC's `chrom.sizes` lists contigs by size (chrX between chr7
 * and chr8, chr21 after chr22, yeast's chrIV first), and the density strip and
 * next / previous region both read the assembly's order, so both use this one.
 *
 * The groups, in order:
 * 1. numbered chromosomes, by number, with their arms after it (fly 2L, 2R,
 *    3L, 3R); roman numerals count as numbers (yeast I to XVI, worm I to V);
 * 2. sex chromosomes: X, Y, then W, Z (birds). In a roman-numbered set X is
 *    ten (worm I to V then X) and sorts with the numbers;
 * 3. organelles: mitochondrion (M, MT, Mito, MtDNA), chloroplast (C, Pt);
 * 4. everything else (unplaced, random, alt, decoy, plasmids), in natural
 *    order: chr1_random before chr10_random, chrUn last as any other name.
 * Prefixes `chr`, `chrom`, `chromosome` and any case are read through.
 */

const SEX = ['X', 'Y', 'W', 'Z'];
const ORGANELLE = ['M', 'MT', 'MITO', 'MTDNA', 'C', 'PT', 'CHLOROPLAST'];
const ROMAN = /^(?=[IVXLC]+$)M*(C[MD]|D?C{0,3})(X[CL]|L?X{0,3})(I[XV]|V?I{0,3})$/;

const bare = (name: string) => name.replace(/^(chromosome|chrom|chr)[_-]?/i, '').toUpperCase();

function romanValue(s: string): number {
  const v: Record<string, number> = { I: 1, V: 5, X: 10, L: 50, C: 100 };
  let total = 0;
  for (let i = 0; i < s.length; i += 1) {
    const cur = v[s[i]];
    const next = v[s[i + 1]] ?? 0;
    total += cur < next ? -cur : cur;
  }
  return total;
}

/** Natural comparison: digit runs compare as numbers (`chr2_x` < `chr10_x`). */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

type Rank = [group: number, num: number, tail: string];

function rank(name: string, romanSet: boolean): Rank {
  const b = bare(name);
  const numbered = /^(\d+)([A-Z]{0,2})$/.exec(b);
  if (numbered) return [0, Number(numbered[1]), numbered[2]];
  // In a roman-numbered set every roman name is a number, X included; `C`
  // stays the chloroplast there (no genome has a hundred chromosomes).
  if (romanSet && b !== 'C' && ROMAN.test(b)) return [0, romanValue(b), ''];
  const sex = SEX.indexOf(b);
  if (sex >= 0) return [1, sex, ''];
  const organelle = ORGANELLE.indexOf(b);
  if (organelle >= 0) return [2, organelle, ''];
  return [3, 0, name];
}

/** Whether the set names its chromosomes in roman numerals: two or more names
 *  that are roman and not a lone X or C (`II`, `IV`, ...). */
function isRomanSet(names: readonly string[]): boolean {
  let n = 0;
  for (const name of names) {
    const b = bare(name);
    if (b !== 'X' && b !== 'C' && ROMAN.test(b)) n += 1;
    if (n >= 2) return true;
  }
  return false;
}

/** `regions` sorted by the convention above, by `refName`. */
export function naturalChromOrder<T extends { refName: string }>(regions: readonly T[]): T[] {
  const romanSet = isRomanSet(regions.map((r) => r.refName));
  return regions
    .map((r) => ({ r, k: rank(r.refName, romanSet) }))
    .sort(
      (a, b) =>
        a.k[0] - b.k[0] || a.k[1] - b.k[1] || naturalCompare(a.k[2], b.k[2]),
    )
    .map(({ r }) => r);
}
