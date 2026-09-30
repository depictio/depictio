/**
 * Residue colour schemes: scientific palettes, kept as DATA in this one module.
 *
 * These are not UI colours. Each table below is the published palette of a
 * named scheme (the ones Jalview, Clustal X and the AlphaFold database use), so
 * a reader who knows the scheme recognises it. Everything else the protein
 * panels paint (text, grid, selection, highlight) comes from the Mantine theme.
 *
 * - Clustal X: residue classes (Jalview's Clustal X table). Coloured only where
 *   the residue's class holds at least half of the column's residues, a
 *   simplified form of the Clustal X conservation thresholds; glycine and
 *   proline are always coloured, as in Clustal X.
 * - Zappo: physico-chemical classes (Jalview's Zappo table), per residue.
 * - Hydrophobicity: the Kyte-Doolittle scale (J Mol Biol 1982) on a linear
 *   blue (hydrophilic) to red (hydrophobic) ramp, Jalview's rendering.
 * - Percentage identity: Jalview's three blue shades for residues agreeing with
 *   the column consensus above 80, 60 and 40 percent.
 * - pLDDT: the AlphaFold database confidence bands.
 * - Secondary structure: RasMol's `structure` scheme (helix, strand, turn).
 */

export type RGB = [number, number, number];

/** A column summary the context-aware schemes read (built in `alignment.ts`). */
export interface ColumnProfile {
  /** Non-gap residues in the column. */
  nonGap: number;
  /** Count per upper-case residue letter. */
  counts: Record<string, number>;
  /** Most frequent residue, null for an all-gap column. */
  consensus: string | null;
  /** Share of the non-gap residues that are the consensus, 0 to 1. */
  consensusFraction: number;
}

export type ClustalClass =
  | 'hydrophobic'
  | 'positive'
  | 'negative'
  | 'polar'
  | 'cysteine'
  | 'glycine'
  | 'proline'
  | 'aromatic';

/** Jalview's Clustal X colours per residue class. */
export const CLUSTAL_COLOURS: Readonly<Record<ClustalClass, RGB>> = {
  hydrophobic: [128, 160, 240],
  positive: [240, 21, 5],
  negative: [192, 72, 192],
  polar: [21, 192, 21],
  cysteine: [240, 128, 128],
  glycine: [240, 144, 72],
  proline: [192, 192, 0],
  aromatic: [21, 164, 164],
};

const CLUSTAL_CLASS: Readonly<Record<string, ClustalClass>> = {
  A: 'hydrophobic',
  I: 'hydrophobic',
  L: 'hydrophobic',
  M: 'hydrophobic',
  F: 'hydrophobic',
  W: 'hydrophobic',
  V: 'hydrophobic',
  K: 'positive',
  R: 'positive',
  E: 'negative',
  D: 'negative',
  N: 'polar',
  Q: 'polar',
  S: 'polar',
  T: 'polar',
  C: 'cysteine',
  G: 'glycine',
  P: 'proline',
  H: 'aromatic',
  Y: 'aromatic',
};

export function clustalClass(letter: string): ClustalClass | null {
  return CLUSTAL_CLASS[letter.toUpperCase()] ?? null;
}

/** Share of a column's residues needed for a class to be coloured. */
export const CLUSTAL_THRESHOLD = 0.5;

/** Jalview's Zappo colours per residue. */
const ZAPPO_GROUPS: ReadonlyArray<[string, RGB]> = [
  ['ILVAM', [255, 175, 175]],
  ['FWY', [255, 200, 0]],
  ['KRH', [100, 100, 255]],
  ['DE', [255, 0, 0]],
  ['STNQ', [0, 255, 0]],
  ['PG', [255, 0, 255]],
  ['C', [255, 255, 0]],
];
const ZAPPO: Readonly<Record<string, RGB>> = Object.fromEntries(
  ZAPPO_GROUPS.flatMap(([letters, rgb]) => letters.split('').map((l) => [l, rgb] as const)),
);

/** Kyte-Doolittle hydropathy index per residue. */
export const KYTE_DOOLITTLE: Readonly<Record<string, number>> = {
  I: 4.5,
  V: 4.2,
  L: 3.8,
  F: 2.8,
  C: 2.5,
  M: 1.9,
  A: 1.8,
  G: -0.4,
  T: -0.7,
  S: -0.8,
  W: -0.9,
  Y: -1.3,
  P: -1.6,
  H: -3.2,
  E: -3.5,
  Q: -3.5,
  D: -3.5,
  N: -3.5,
  K: -3.9,
  R: -4.5,
};
const HYDROPHILIC_END: RGB = [0, 0, 255];
const HYDROPHOBIC_END: RGB = [255, 0, 0];

/** Jalview's percentage-identity shades, strongest first. */
export const IDENTITY_SHADES: ReadonlyArray<[number, RGB]> = [
  [0.8, [100, 100, 255]],
  [0.6, [153, 153, 255]],
  [0.4, [204, 204, 255]],
];

export function isGap(letter: string): boolean {
  return letter === '-' || letter === '.' || letter === ' ' || letter === '';
}

export function zappoColour(letter: string): RGB | null {
  return ZAPPO[letter.toUpperCase()] ?? null;
}

export function hydrophobicityColour(letter: string): RGB | null {
  const kd = KYTE_DOOLITTLE[letter.toUpperCase()];
  if (kd === undefined) return null;
  const t = (kd + 4.5) / 9;
  return [
    Math.round(HYDROPHILIC_END[0] + t * (HYDROPHOBIC_END[0] - HYDROPHILIC_END[0])),
    Math.round(HYDROPHILIC_END[1] + t * (HYDROPHOBIC_END[1] - HYDROPHILIC_END[1])),
    Math.round(HYDROPHILIC_END[2] + t * (HYDROPHOBIC_END[2] - HYDROPHILIC_END[2])),
  ];
}

/** Clustal X colour of `letter` in a column, or null when its class is too rare there. */
export function clustalColour(letter: string, column?: ColumnProfile | null): RGB | null {
  const cls = clustalClass(letter);
  if (!cls) return null;
  if (cls === 'glycine' || cls === 'proline' || !column || column.nonGap === 0) {
    return CLUSTAL_COLOURS[cls];
  }
  let inClass = 0;
  for (const [l, n] of Object.entries(column.counts)) {
    if (CLUSTAL_CLASS[l] === cls) inClass += n;
  }
  return inClass / column.nonGap >= CLUSTAL_THRESHOLD ? CLUSTAL_COLOURS[cls] : null;
}

/** Percentage-identity shade: only residues equal to the column consensus. */
export function identityColour(letter: string, column?: ColumnProfile | null): RGB | null {
  if (!column || !column.consensus || letter.toUpperCase() !== column.consensus) return null;
  for (const [min, rgb] of IDENTITY_SHADES) {
    if (column.consensusFraction > min) return rgb;
  }
  return null;
}

/** Cell colour of `letter` under `scheme`, null for an uncoloured cell (gaps included). */
export function schemeColour(
  scheme: string,
  letter: string,
  column?: ColumnProfile | null,
): RGB | null {
  if (isGap(letter)) return null;
  switch (scheme) {
    case 'clustal':
      return clustalColour(letter, column);
    case 'zappo':
      return zappoColour(letter);
    case 'hydrophobicity':
      return hydrophobicityColour(letter);
    case 'identity':
      return identityColour(letter, column);
    default:
      return null;
  }
}

export function rgbCss([r, g, b]: RGB, alpha = 1): string {
  return alpha >= 1 ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${alpha})`;
}

/** One AlphaFold confidence band. */
export interface PlddtBand {
  key: 'very_high' | 'confident' | 'low' | 'very_low';
  label: string;
  /** Lower bound, inclusive (pLDDT 0 to 100). */
  min: number;
  rgb: RGB;
}

/** The AlphaFold database pLDDT bands, highest first. */
export const PLDDT_BANDS: readonly PlddtBand[] = [
  { key: 'very_high', label: 'Very high (pLDDT > 90)', min: 90, rgb: [0, 83, 214] },
  { key: 'confident', label: 'Confident (90 > pLDDT > 70)', min: 70, rgb: [101, 203, 243] },
  { key: 'low', label: 'Low (70 > pLDDT > 50)', min: 50, rgb: [255, 219, 19] },
  { key: 'very_low', label: 'Very low (pLDDT < 50)', min: -Infinity, rgb: [255, 125, 69] },
];

/**
 * Whether a set of pLDDT values is on the 0-1 scale (some ESMFold outputs)
 * rather than 0-100. Decided once per protein, never per value: 0.9 means
 * "very high" in one file and "very low" in the other.
 */
export function plddtIsFractional(values: Iterable<number | null | undefined>): boolean {
  let seen = false;
  for (const v of values) {
    if (v == null || !Number.isFinite(v)) continue;
    seen = true;
    if (v > 1) return false;
  }
  return seen;
}

/** The band a pLDDT value falls in (strictly above the band's lower bound). */
export function plddtBand(value: number, fractional = false): PlddtBand {
  const v = fractional ? value * 100 : value;
  for (const band of PLDDT_BANDS) if (v > band.min) return band;
  return PLDDT_BANDS[PLDDT_BANDS.length - 1];
}

export function plddtColour(value: number, fractional = false): string {
  return rgbCss(plddtBand(value, fractional).rgb);
}

/** Secondary-structure classes and RasMol's `structure` colours. */
export type SecondaryStructure = 'helix' | 'strand' | 'turn' | 'coil';

export const SECONDARY_STRUCTURE_COLOURS: Readonly<Record<Exclude<SecondaryStructure, 'coil'>, RGB>> = {
  helix: [255, 0, 128],
  strand: [255, 200, 0],
  turn: [96, 128, 255],
};
