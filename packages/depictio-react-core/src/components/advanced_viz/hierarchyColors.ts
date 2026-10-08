/**
 * Colour for hierarchies drawn as one figure: a sunburst's rings, a sankey's
 * columns.
 *
 * A hue per node made these read as confetti: forty colours, none of which
 * said which kingdom a phylum belongs to. Here a lineage keeps one hue, the
 * one its top value wears everywhere else on the dashboard (a Kingdom's pinned
 * colour, say), and its descendants are shades of it, lighter the deeper they
 * sit; every other sibling is a touch lighter again, so neighbours part
 * without a new hue. Values that name no taxon ("Unclassified", "Other") are
 * grey, so they read as a remainder rather than as one more group.
 */

const HEX = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i;

function parseHex(hex: string): [number, number, number] | null {
  const m = HEX.exec(hex.trim());
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].replace(/./g, (c) => c + c) : m[1];
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

/** `a` moved a fraction `t` of the way to `b`; `a` unchanged when either is not a hex colour. */
export function mixHex(a: string, b: string, t: number): string {
  const x = parseHex(a);
  const y = parseHex(b);
  if (!x || !y) return a;
  const k = Math.max(0, Math.min(1, t));
  return `#${x
    .map((v, i) => Math.round(v + (y[i] - v) * k).toString(16).padStart(2, '0'))
    .join('')}`;
}

const UNASSIGNED = new Set(['', 'unclassified', 'unassigned', 'unknown', 'other', 'none', 'na', 'n/a', 'nan', '-', '—']);

/** Whether a value names no group: "Unclassified", "Other (12)", an empty rank. */
export function isUnassigned(label: string | null | undefined): boolean {
  const l = String(label ?? '').trim().toLowerCase();
  return UNASSIGNED.has(l) || l.startsWith('unclassified') || /^other\b/.test(l);
}

/** The grey of a remainder, on either surface. */
export function unassignedGrey(isDark: boolean): string {
  return isDark ? '#5c5f66' : '#c1c6cc';
}

/** The surface shades are mixed toward: lighter on paper, darker on a dark card. */
export function surfaceColour(isDark: boolean): string {
  return isDark ? '#25262b' : '#ffffff';
}

/**
 * A descendant's shade of its lineage colour, `depthBelow` levels under the
 * level that set the hue (0 is that level itself), `siblingIndex` its place
 * among its siblings.
 */
export function lineageShade(
  base: string,
  depthBelow: number,
  siblingIndex: number,
  isDark: boolean,
): string {
  if (depthBelow <= 0) return base;
  const t = Math.min(0.66, 0.24 * depthBelow + (siblingIndex % 2 ? 0.08 : 0));
  return mixHex(base, surfaceColour(isDark), t);
}
