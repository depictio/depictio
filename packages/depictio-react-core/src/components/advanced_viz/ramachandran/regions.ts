/**
 * Schematic favoured regions of the Ramachandran plot, and the point-in-polygon
 * test that counts residues against them.
 *
 * These are hand-drawn approximations from the textbook boundaries (the right
 * handed helix, the beta strand including the polyproline II band, the left
 * handed helix), NOT the MolProbity / Top8000 contours: those are probability
 * densities fitted to a curated data set, and none of that data is copied here.
 * Every label that shows them says so (`REGION_NOTE`). A residue inside one of
 * these polygons is "inside the approximate favoured regions", nothing more:
 * it is a reading aid for a structure-quality glance, not a validation.
 *
 * Coordinates are (phi, psi) in degrees, both inside [-180, 180]. A region
 * that wraps across the +-180 edge is drawn as two polygons (the beta strand's
 * lower fringe sits at psi near -180). Pure: no React, no Plotly, so vitest
 * covers it in node.
 */

import type { ResidueClass } from '../molecule/backbone';

/** A (phi, psi) vertex, in degrees. */
export type Vertex = readonly [number, number];

/** The three conformations the schematic names. */
export type RegionName = 'alpha_r' | 'beta' | 'alpha_l';

/** Which family of polygons applies: MolProbity's four residue classes share
 *  three distributions, and pre-proline residues use the general one here. */
export type RegionSetName = 'general' | 'glycine' | 'proline';

export interface Region {
  name: RegionName;
  polygon: readonly Vertex[];
  /** Drawn with a text label (a wrapped or mirrored twin is not). */
  labelled: boolean;
}

/** What every legend entry and caption of these regions must say. */
export const REGION_NOTE = 'approximate regions, not MolProbity contours';

export const REGION_LABELS: Readonly<Record<RegionName, string>> = {
  alpha_r: 'αR',
  beta: 'β',
  alpha_l: 'αL',
};

export const REGION_DESCRIPTIONS: Readonly<Record<RegionName, string>> = {
  alpha_r: 'right-handed helix',
  beta: 'strand, including polyproline II',
  alpha_l: 'left-handed helix',
};

export const REGION_SET_LABELS: Readonly<Record<RegionSetName, string>> = {
  general: 'general case',
  glycine: 'glycine',
  proline: 'proline',
};

// ---------------------------------------------------------------------------
// The polygons
// ---------------------------------------------------------------------------

/** Right-handed helix and its bridge towards the strand: phi about -160 to -30,
 *  psi about -80 to +55. The canonical helix (-57, -47) sits well inside. */
const ALPHA_R: readonly Vertex[] = [
  [-160, -20],
  [-145, 10],
  [-110, 40],
  [-75, 55],
  [-45, 35],
  [-30, -10],
  [-35, -55],
  [-55, -80],
  [-95, -80],
  [-130, -60],
];

/** Strand and polyproline II: phi below -45, psi above about 100. */
const BETA: readonly Vertex[] = [
  [-180, 100],
  [-155, 92],
  [-125, 95],
  [-90, 100],
  [-60, 115],
  [-45, 140],
  [-45, 180],
  [-180, 180],
];

/** The strand region continues across the psi = +-180 edge. */
const BETA_WRAP: readonly Vertex[] = [
  [-180, -180],
  [-65, -180],
  [-85, -165],
  [-130, -160],
  [-180, -165],
];

/** Left-handed helix: a small region around (57, 40). */
const ALPHA_L: readonly Vertex[] = [
  [35, 15],
  [55, -5],
  [85, 10],
  [95, 45],
  [75, 80],
  [45, 75],
];

const reflect = (polygon: readonly Vertex[]): Vertex[] =>
  polygon.map(([phi, psi]) => [-phi, -psi] as const);

/** Glycine has no side chain to clash with, so its map is point symmetric:
 *  every general region has a mirror image through the origin. */
const GLYCINE_REGIONS: readonly Region[] = [
  { name: 'alpha_r', polygon: ALPHA_R, labelled: true },
  { name: 'beta', polygon: BETA, labelled: true },
  { name: 'beta', polygon: BETA_WRAP, labelled: false },
  { name: 'alpha_l', polygon: reflect(ALPHA_R), labelled: true },
  { name: 'beta', polygon: reflect(BETA), labelled: true },
  { name: 'beta', polygon: reflect(BETA_WRAP), labelled: false },
];

/** Proline's ring pins phi near -65: only a narrow band of phi is open. */
const PROLINE_REGIONS: readonly Region[] = [
  {
    name: 'alpha_r',
    polygon: [
      [-95, -65],
      [-95, -15],
      [-80, 5],
      [-55, 5],
      [-45, -20],
      [-50, -55],
      [-65, -70],
    ],
    labelled: true,
  },
  {
    name: 'beta',
    polygon: [
      [-95, 105],
      [-70, 100],
      [-48, 115],
      [-45, 180],
      [-95, 180],
    ],
    labelled: true,
  },
  {
    name: 'beta',
    polygon: [
      [-95, -180],
      [-55, -180],
      [-60, -170],
      [-95, -165],
    ],
    labelled: false,
  },
];

const GENERAL_REGIONS: readonly Region[] = [
  { name: 'alpha_r', polygon: ALPHA_R, labelled: true },
  { name: 'beta', polygon: BETA, labelled: true },
  { name: 'beta', polygon: BETA_WRAP, labelled: false },
  { name: 'alpha_l', polygon: ALPHA_L, labelled: true },
];

const SETS: Readonly<Record<RegionSetName, readonly Region[]>> = {
  general: GENERAL_REGIONS,
  glycine: GLYCINE_REGIONS,
  proline: PROLINE_REGIONS,
};

/** The polygons of one set. */
export function regionSet(name: RegionSetName): readonly Region[] {
  return SETS[name];
}

/** The set that applies to a residue class. Pre-proline residues have their own
 *  MolProbity distribution; this schematic does not, so they share the
 *  general polygons. */
export function regionSetOfClass(cls: ResidueClass): RegionSetName {
  if (cls === 'glycine') return 'glycine';
  if (cls === 'proline') return 'proline';
  return 'general';
}

/**
 * The set to draw for a plot showing `classes` (null or empty: every class).
 *
 * The glycine and proline sets are drawn only when the plot is filtered to
 * that class alone; any mixture draws the general case, which is the one the
 * bulk of a structure follows.
 */
export function regionSetFor(classes: readonly ResidueClass[] | null | undefined): RegionSetName {
  if (!classes || classes.length !== 1) return 'general';
  return regionSetOfClass(classes[0]);
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

/** Even-odd ray casting: whether (phi, psi) lies inside the polygon. A point on
 *  an edge counts as inside or outside depending on the edge, which is
 *  immaterial for a schematic. */
export function pointInPolygon(phi: number, psi: number, polygon: readonly Vertex[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if (yi > psi !== yj > psi && phi < ((xj - xi) * (psi - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/** The region of `set` containing (phi, psi), null when it is in none. */
export function regionAt(phi: number, psi: number, set: RegionSetName): RegionName | null {
  for (const region of SETS[set]) {
    if (pointInPolygon(phi, psi, region.polygon)) return region.name;
  }
  return null;
}

/** Whether (phi, psi) is inside any favoured region of `set`. */
export function isFavoured(phi: number, psi: number, set: RegionSetName): boolean {
  return regionAt(phi, psi, set) !== null;
}

/** Residues inside and outside the approximate favoured regions, each judged
 *  against the regions of its own class (glycine against the glycine set, and
 *  so on). */
export function countFavoured(
  points: readonly { phi: number; psi: number; cls: ResidueClass }[],
): { inside: number; outside: number } {
  let inside = 0;
  for (const p of points) {
    if (isFavoured(p.phi, p.psi, regionSetOfClass(p.cls))) inside += 1;
  }
  return { inside, outside: points.length - inside };
}

/** The polygon as an SVG path (`M x,y L ... Z`), the form a Plotly `path`
 *  shape takes. */
export function polygonPath(polygon: readonly Vertex[]): string {
  return `${polygon.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join('')}Z`;
}

/** Where to write a region's label: the mean of its vertices. */
export function labelAnchor(polygon: readonly Vertex[]): Vertex {
  let x = 0;
  let y = 0;
  for (const [vx, vy] of polygon) {
    x += vx;
    y += vy;
  }
  const n = Math.max(1, polygon.length);
  return [x / n, y / n];
}
