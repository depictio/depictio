/**
 * Shared categorical colour palette + stable colour-mapping utility.
 *
 * Multiple advanced_viz renderers map categorical values (clusters, habitats,
 * tip categories, etc.) to palette indices. Doing this off the *filtered* set
 * means a colour shifts whenever the user filters — e.g. selecting only
 * "treatment" out of {control, treatment, recovery} would re-map treatment from
 * the 3rd palette colour to the 1st.
 *
 * ``stableColorMap`` keys colours by the full distinct-value set (typically
 * the polars-unique-values endpoint), sorts deterministically, and returns a
 * frozen ``Map<value, colour>`` that downstream code can read without worrying
 * about the current filter state. Pass the universe of values as ``allValues``;
 * any value not in that universe falls back to a deterministic hash-derived
 * palette index so a stale ``allValues`` doesn't crash colouring.
 */

import {
  assignColors,
  categoricalPalette,
  compareValues,
  overflowMode,
  reservedKind,
  semanticColor,
} from './palettes';
import type { ColorScheme, OverflowMode } from './palettes';

/**
 * @deprecated The light-mode default palette, kept as a name for callers that
 * have not learned the colour scheme yet. It is no longer matplotlib's tab10:
 * it IS depictio's shared categorical palette (`categoricalPalette(null)`).
 * Prefer `defaultCategorical(isDark)`, which follows the scheme.
 */
export const TAB10_PALETTE: readonly string[] = categoricalPalette(null, 'light');

/**
 * matplotlib tab10, for the viz controls that offer it BY NAME ("tab10"). A
 * viewer's explicit choice, never a default: defaults come from
 * `defaultCategorical`.
 */
export const TAB10_CLASSIC: readonly string[] = [
  '#1f77b4',
  '#ff7f0e',
  '#2ca02c',
  '#d62728',
  '#9467bd',
  '#8c564b',
  '#e377c2',
  '#7f7f7f',
  '#bcbd22',
  '#17becf',
];

/** depictio's default categorical palette for the colour scheme. */
export function defaultCategorical(isDark = false): readonly string[] {
  return categoricalPalette(null, isDark ? 'dark' : 'light');
}

/**
 * @deprecated Mantine hue names, no longer a palette source: the default
 * categorical colours come from the shared palette. Still exported for the
 * allele grid, which keys its hue tints by Mantine colour name.
 */
export const MANTINE_COLORWAY_HUES: readonly string[] = [
  'teal',
  'pink',
  'violet',
  'lime',
  'cyan',
  'grape',
  'indigo',
  'red',
  'yellow',
  'blue',
];

/** A theme carrying Mantine's colour scales — `MantineTheme`, structurally. */
interface ScaleCarryingTheme {
  colors?: Record<string, readonly string[]>;
}

/**
 * The default categorical palette for the scheme: depictio's shared palette.
 * Pass it as the `fallback` of `resolveCategoricalPalette` — a branded
 * deployment's own colorway still wins over it.
 *
 * Only when a caller names `hues` explicitly does it read the theme's own
 * Mantine colour scales (shade 6 on light, 4 on dark) for those hues.
 */
export function mantineCategoricalPalette(
  theme?: ScaleCarryingTheme | null,
  isDark = false,
  hues?: readonly string[],
): readonly string[] {
  const shared = defaultCategorical(isDark);
  const scales = theme?.colors;
  if (!hues || !scales) return shared;
  const shade = isDark ? 4 : 6;
  const out = hues.map((hue) => scales[hue]?.[shade]).filter((c): c is string => !!c);
  return out.length ? out : shared;
}

/** A theme carrying the resolved brand — `MantineTheme`, structurally. */
interface BrandCarryingTheme {
  other?: Record<string, unknown>;
}

/**
 * The brand's categorical hues, or null when the deployment states no brand.
 *
 * The colorway is derived server-side and travels on the Mantine theme
 * (`buildDepictioTheme` stashes the resolved brand in `theme.other`), so a
 * nested provider — a dashboard overriding the instance — is picked up for
 * free, and the client never re-derives what the server already computed.
 */
export function brandColorway(theme?: BrandCarryingTheme | null, isDark = false): string[] | null {
  const brand = theme?.other?.brand as
    | { plots?: { colorway?: string[] | null; colorway_dark?: string[] | null } }
    | null
    | undefined;
  const dark = isDark ? brand?.plots?.colorway_dark : null;
  const colorway = dark && dark.length ? dark : brand?.plots?.colorway;
  return colorway && colorway.length ? colorway : null;
}

/** The brand's overflow mode (`plots.overflow`), else the shared default. */
export function plotOverflow(theme?: BrandCarryingTheme | null): OverflowMode {
  const brand = theme?.other?.brand as { plots?: { overflow?: string | null } } | null | undefined;
  return overflowMode(brand?.plots?.overflow);
}

/**
 * The categorical palette a renderer should map values through, by precedence:
 * the brand's colorway (the scheme's own when it states a dark one), then the
 * renderer's `fallback`, then depictio's shared palette for the scheme. The
 * deprecated `TAB10_PALETTE` as a fallback means "no palette of my own" and is
 * read as the shared palette, so it follows `isDark`.
 */
export function resolveCategoricalPalette(
  theme?: BrandCarryingTheme | null,
  fallback?: readonly string[] | null,
  isDark = false,
): readonly string[] {
  const brand = brandColorway(theme, isDark);
  if (brand) return brand;
  if (!fallback || fallback === TAB10_PALETTE) return defaultCategorical(isDark);
  return fallback;
}

function hashString(s: string): number {
  // Stable, cheap hash — same value always yields the same colour even when
  // it's not in the supplied ``allValues``.
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

export interface StableColorMap {
  /** Returns the palette colour for ``value`` (deterministic regardless of filter). */
  get(value: string): string;
  /** Underlying sorted universe of values that drives the palette index. */
  readonly universe: readonly string[];
}

/**
 * Build a stable value→colour map from the universe of distinct values.
 *
 * Colours follow the shared rule (`assignColors`): an override wins, a reserved
 * remainder value (Other, Unclassified, NA...) takes its semantic grey, and the
 * rest are ranked case-insensitively over the universe onto the palette slots
 * no override uses. Empty / nullish entries are skipped. `scheme` picks the
 * greys and the default palette; `overflow` (`plotOverflow(theme)`) what the
 * values past the last slot get.
 */
export function stableColorMap(
  allValues: readonly (string | null | undefined)[],
  palette?: readonly string[] | null,
  overrides?: Record<string, string> | null,
  scheme: ColorScheme = 'light',
  overflow?: OverflowMode | null,
): StableColorMap {
  const colours = palette && palette.length ? palette : categoricalPalette(null, scheme);
  const cleaned = Array.from(
    new Set(
      allValues
        .filter((v): v is string => v != null && v !== '')
        .map((v) => String(v)),
    ),
  );
  const sorted = [...cleaned].sort(compareValues);
  // Dashboards pin domain-specific colours (habitat → Set1 mapping, lineage →
  // Pango palette, etc.) through `overrides` without forking the renderer.
  const lookup = assignColors(sorted, { pinned: overrides, palette: colours, scheme, overflow });

  return {
    get(value: string): string {
      const key = String(value);
      const hit = lookup.get(key);
      if (hit) return hit;
      // Values outside the supplied universe: reserved values keep their grey,
      // the rest a deterministic hash, so a "leaked" value still gets a stable
      // colour across re-renders.
      const kind = reservedKind(key);
      if (kind && key !== '') return semanticColor(kind, scheme);
      return colours[hashString(key) % colours.length];
    },
    universe: sorted,
  };
}

/** Set1-derived habitat palette used by nf-core/ampliseq dashboards. Mirrors
 *  the inline ``color_discrete_map`` in the alpha-diversity boxplot so the
 *  PCoA, boxplot, UpSet set bars and any other habitat-coloured tile share
 *  one mapping. Keys MUST match the canonical habitat values emitted by the
 *  recipes (no whitespace tolerance, case sensitive). */
export const AMPLISEQ_HABITAT_COLORS: Record<string, string> = {
  Riverwater: '#377EB8',
  Groundwater: '#4DAF4A',
  Sediment: '#E41A1C',
  Soil: '#FF7F00',
};
