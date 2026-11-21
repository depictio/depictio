/**
 * depictio's plot palettes, TypeScript side. Mirrors `depictio/models/palettes/__init__.py`;
 * the colours themselves come from `palettes.generated.ts`, written from the shared
 * JSON, so the two languages can never disagree on a hex.
 *
 * Assignment rule (`assignColors`), identical to Python's `assign_colors`:
 *   1. a pinned colour wins;
 *   2. a reserved value (Other, Unclassified, NA, ...) takes its semantic grey;
 *   3. the remaining values, case-insensitively ordered over the whole universe
 *      (or in the caller's order with `ranked`), take the slots no pin already uses;
 *   4. past the last slot a value never repeats a hue: the Other grey, or first a
 *      lightness-shifted twin of each slot with `overflow: 'shade'` (default
 *      `OVERFLOW_MODE`; a brand sets it with `plots.overflow`). Shades exist only
 *      for a named palette, or a list holding exactly one palette's colours.
 */
import {
  ANNOTATION_INK,
  BAR_CORNER_RADIUS,
  DEFAULT_PALETTE_ID,
  OVERFLOW_MODE,
  OVERFLOW_SHADES,
  OVERVIEW_TOP_N,
  PALETTE_IDS,
  PALETTES,
  PLOT_CHROME,
  RESERVED_VALUES,
  SCATTER_MARKERS,
  SEMANTIC_COLORS,
} from './palettes.generated';
import type { ChromeTokens, PaletteId, ReservedKind, ScatterMarkerBucket } from './palettes.generated';

export type ColorScheme = 'light' | 'dark';

export function isPaletteId(value: unknown): value is PaletteId {
  return typeof value === 'string' && (PALETTE_IDS as readonly string[]).includes(value);
}

function spec(id?: string | null) {
  return isPaletteId(id) ? PALETTES[id] : PALETTES[DEFAULT_PALETTE_ID];
}

export type OverflowMode = 'other' | 'shade';

/** `other` / `shade` from any input; the JSON default for anything else. */
export function overflowMode(value?: unknown): OverflowMode {
  return value === 'shade' || value === 'other' ? value : OVERFLOW_MODE;
}

/** The palette id a palette argument stands for: an id, nothing (the default), or
 *  a list equal to one palette's colours in `scheme`; null for a free colour list. */
export function namedPaletteOf(
  palette: string | readonly string[] | null | undefined,
  scheme: ColorScheme = 'light',
): PaletteId | null {
  if (palette == null || palette.length === 0) return DEFAULT_PALETTE_ID;
  if (typeof palette === 'string') return isPaletteId(palette) ? palette : DEFAULT_PALETTE_ID;
  const key = palette.map((c) => c.toLowerCase()).join(',');
  return (
    PALETTE_IDS.find(
      (id) => PALETTES[id].categorical[scheme].map((c) => c.toLowerCase()).join(',') === key,
    ) ?? null
  );
}

export function categoricalPalette(id?: string | null, scheme: ColorScheme = 'light'): readonly string[] {
  return spec(id).categorical[scheme];
}

export function sequentialPalette(id?: string | null, scheme: ColorScheme = 'light'): readonly string[] {
  return spec(id).sequential[scheme];
}

export function divergingPalette(id?: string | null, scheme: ColorScheme = 'light'): readonly string[] {
  return spec(id).diverging[scheme];
}

/** Plotly colorscale from evenly spaced stops. */
export function toColorscale(colors: readonly string[]): [number, string][] {
  const last = colors.length - 1;
  return colors.map((c, i) => [i / last, c]);
}

export function semanticColor(kind: ReservedKind, scheme: ColorScheme = 'light'): string {
  return SEMANTIC_COLORS[kind][scheme];
}

export function annotationInk(scheme: ColorScheme = 'light'): string {
  return ANNOTATION_INK[scheme];
}

export function plotChrome(scheme: ColorScheme = 'light'): ChromeTokens {
  return PLOT_CHROME[scheme];
}

const RESERVED_LOOKUP: Map<string, ReservedKind> = new Map(
  (Object.entries(RESERVED_VALUES) as [ReservedKind, readonly string[]][]).flatMap(([kind, names]) =>
    names.map((n) => [n, kind] as [string, ReservedKind]),
  ),
);

/** `other` / `unclassified` / `na` when `value` is a reserved remainder value. */
export function reservedKind(value: unknown): ReservedKind | null {
  if (value == null) return 'na';
  return RESERVED_LOOKUP.get(String(value).trim().toLowerCase()) ?? null;
}

/** Python's `(s.casefold(), s)` sort key: case-insensitive, raw value breaks ties. */
export function compareValues(a: string, b: string): number {
  const la = a.toLowerCase();
  const lb = b.toLowerCase();
  if (la !== lb) return la < lb ? -1 : 1;
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

export interface AssignOptions {
  pinned?: Record<string, string> | null;
  /** A palette id, an explicit colour list (brand colorway), or nothing for the default. */
  palette?: string | readonly string[] | null;
  scheme?: ColorScheme;
  /** Keep the order of `values` (most important first) instead of sorting them. */
  ranked?: boolean;
  /** Past the last slot: the Other grey, or first shade twins (named palettes only). */
  overflow?: OverflowMode | null;
}

export function assignColors(
  values: Iterable<unknown>,
  { pinned, palette, scheme = 'light', ranked = false, overflow }: AssignOptions = {},
): Map<string, string> {
  const pins = new Map(
    Object.entries(pinned ?? {}).filter(([, c]) => !!c) as [string, string][],
  );
  const colours =
    palette == null || typeof palette === 'string'
      ? categoricalPalette(palette as string | null, scheme)
      : palette.length
        ? palette
        : categoricalPalette(null, scheme);

  const distinct = Array.from(new Set(Array.from(values, (v) => (v == null ? '' : String(v)))));
  if (!ranked) distinct.sort(compareValues);

  const result = new Map<string, string>();
  const free: string[] = [];
  for (const value of distinct) {
    const pin = pins.get(value);
    if (pin) {
      result.set(value, pin);
      continue;
    }
    const kind = reservedKind(value);
    if (kind) result.set(value, semanticColor(kind, scheme));
    else free.push(value);
  }
  const used = new Set(Array.from(pins.values(), (c) => c.toLowerCase()));
  const slots = colours.filter((c) => !used.has(c.toLowerCase()));
  const shadeId = overflowMode(overflow) === 'shade' ? namedPaletteOf(palette, scheme) : null;
  if (shadeId) {
    slots.push(...OVERFLOW_SHADES[shadeId][scheme].filter((c) => !used.has(c.toLowerCase())));
  }
  const remainder = semanticColor('other', scheme);
  free.forEach((value, i) => result.set(value, i < slots.length ? slots[i] : remainder));
  for (const [value, colour] of pins) if (!result.has(value)) result.set(value, colour);
  return result;
}

/** Keep order, move Other, then Unclassified, then NA to the end. */
export function orderWithRemainderLast<T>(values: readonly T[]): T[] {
  const rank: Record<ReservedKind, number> = { other: 1, unclassified: 2, na: 3 };
  return values
    .map((v, i) => ({ v, i, r: rank[reservedKind(v) as ReservedKind] ?? 0 }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((x) => x.v);
}

/** Marker size / opacity / outline for a scatter of `n` points (mirrors Python's
 *  `scatter_marker`): more points, smaller and fainter. */
export function scatterMarker(n: number): ScatterMarkerBucket {
  return SCATTER_MARKERS.find((b) => b.max_n === null || n <= b.max_n) ?? SCATTER_MARKERS[SCATTER_MARKERS.length - 1];
}

export { BAR_CORNER_RADIUS, DEFAULT_PALETTE_ID, OVERVIEW_TOP_N, PALETTE_IDS, PALETTES };
export type { PaletteId, ReservedKind, ChromeTokens, ScatterMarkerBucket };
