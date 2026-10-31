/**
 * The chromosome palette a Manhattan paints its blocks with, shared so another
 * genome-wide tile (a sashimi's arcs) gives a chromosome the same colour.
 */
export const CHROMOSOME_PALETTE = [
  '#1c7ed6',
  '#e64980',
  '#fab005',
  '#37b24d',
  '#7048e8',
  '#f76707',
  '#0ca678',
  '#d6336c',
];

// Natural chromosome order: chr1..chr22, chrX, chrY, chrMT, then anything else
// alphabetically. Returns 100 for unrecognised labels so they sort last.
export function chromosomeSortKey(label: string): number {
  const stripped = label.replace(/^chr/i, '').toUpperCase();
  if (stripped === 'X') return 23;
  if (stripped === 'Y') return 24;
  if (stripped === 'MT' || stripped === 'M') return 25;
  const n = Number.parseInt(stripped, 10);
  return Number.isFinite(n) ? n : 100;
}

/** `chroms` in natural order, each with its palette colour. A named chromosome
 *  takes the colour of its place in the genome (chr1 the first, chrX the 23rd),
 *  not its rank among `chroms`: a sashimi keeps its busiest loci only, and a
 *  rank among what it kept gave chr17 another colour than the Manhattan above
 *  it. Unrecognised contigs follow, by rank. */
export function chromosomeColourMap(chroms: Iterable<string>): Map<string, string> {
  const sorted = Array.from(new Set(chroms)).sort(
    (a, b) => chromosomeSortKey(a) - chromosomeSortKey(b),
  );
  let extra = 0;
  return new Map(
    sorted.map((c) => {
      const key = chromosomeSortKey(c);
      const slot = key < 100 ? key - 1 : 25 + extra++;
      return [c, CHROMOSOME_PALETTE[slot % CHROMOSOME_PALETTE.length]];
    }),
  );
}
