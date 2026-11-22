/**
 * Colour for hierarchies drawn as one figure: a sunburst's rings, a sankey's
 * columns.
 *
 * A hue per node made these read as confetti: forty colours, none of which
 * said which kingdom a phylum belongs to. Here a lineage keeps one hue, the
 * one its top value wears everywhere else on the dashboard (a Kingdom's pinned
 * colour, say), and its descendants are shades of it, lighter the deeper they
 * sit; every other sibling is a touch lighter again, so neighbours part
 * without a new hue. Values that name no taxon ("Unclassified", "Other") take
 * the shared palette's semantic greys, so they read as a remainder rather than
 * as one more group.
 */
import { compareValues, plotChrome, reservedKind, semanticColor } from '../../palettes';

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

/** Whether a value names no group: a reserved value of the shared palette ("Others",
 *  "Undetermined", an empty rank), "Unclassified Bacteria", "Other (12)", or a dash. */
export function isUnassigned(label: string | null | undefined): boolean {
  const l = String(label ?? '').trim().toLowerCase();
  return (
    reservedKind(l) !== null ||
    l === '-' ||
    l === '—' ||
    l.startsWith('unclassified') ||
    /^others?\b/.test(l)
  );
}

/** The grey of a remainder, on either surface (the palette's `unclassified` grey). */
export function unassignedGrey(isDark: boolean): string {
  return semanticColor('unclassified', isDark ? 'dark' : 'light');
}

/**
 * The grey of one remainder value: "Other" and "NA" keep their own semantic
 * grey, anything else that names no group (an empty rank, "unknown") is
 * `unclassified`.
 */
export function remainderColour(label: string | null | undefined, isDark: boolean): string {
  const l = String(label ?? '').trim();
  const kind = /^other\b/i.test(l)
    ? 'other'
    : (reservedKind(label == null ? null : l) ?? 'unclassified');
  return semanticColor(kind, isDark ? 'dark' : 'light');
}

/** The surface shades are mixed toward: lighter on paper, darker on a dark card. */
export function surfaceColour(isDark: boolean): string {
  return plotChrome(isDark ? 'dark' : 'light').surface;
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

/**
 * The values of one rank in colouring order: those with a weight, heaviest
 * first (ties alphabetical), then the rest of `universe` alphabetically, so a
 * value a filter hides still has a colour when it comes back. Hand it to
 * `assignColors` with `ranked: true`: the top values get the palette's slots
 * and the tail falls to the grey.
 */
export function abundanceRanked(
  weight: ReadonlyMap<string, number>,
  universe: readonly unknown[] | null | undefined,
): string[] {
  const top = [...weight.keys()].sort((a, b) => (weight.get(b) ?? 0) - (weight.get(a) ?? 0) || compareValues(a, b));
  const rest = Array.from(new Set((universe ?? []).filter((v) => v != null && v !== '').map(String)))
    .filter((v) => !weight.has(v))
    .sort(compareValues);
  return [...top, ...rest];
}

/** What `ringColour` needs to know about one arc. */
export interface RingNode {
  label: string;
  /** Ring index within the visible slice (0 is the innermost). */
  depth: number;
  /** The colour-by rank's value on this arc's path; null above that rank. */
  colourKey: string | null;
  /** Names no group, or sits under one that does. */
  unassigned: boolean;
}

/**
 * One arc's colour. A remainder is grey. An arc above the colour-by ring wears
 * its own column's pinned colour (`ringPins[depth][label]`, a Kingdom keeps its
 * Kingdom colour) and `context` when nothing is pinned for it. The colour-by
 * ring takes `colourMap` (pins first, then the palette) and each ring below is
 * a lineage shade of its colour-by ancestor.
 */
export function ringColour(
  node: RingNode,
  siblingIndex: number,
  opts: {
    localColourIdx: number;
    colourMap: ReadonlyMap<string, string>;
    ringPins: ReadonlyArray<Readonly<Record<string, string>> | null>;
    grey: string;
    context: string;
    isDark: boolean;
  },
): string {
  if (node.unassigned) return opts.grey;
  if (node.colourKey == null) return opts.ringPins[node.depth]?.[node.label] ?? opts.context;
  return lineageShade(
    opts.colourMap.get(node.colourKey) ?? opts.context,
    node.depth - opts.localColourIdx,
    siblingIndex,
    opts.isDark,
  );
}
