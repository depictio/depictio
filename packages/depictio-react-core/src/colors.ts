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

// matplotlib tab10 (also scanpy's default categorical palette). Kept here in
// addition to per-renderer copies so callers can opt into the shared mapping
// without changing their inline palette as well — but importing the same
// constant from this module keeps cross-viz colours consistent.
export const TAB10_PALETTE: readonly string[] = [
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

/**
 * Hue order for `mantineCategoricalPalette`, chosen so the first two are as far
 * apart as the wheel allows: a two-class viz (known vs novel, pass vs fail) is
 * the common case and its two colours have to survive being drawn crossing each
 * other. Deliberately not tab10's blue-then-orange, which every matplotlib and
 * seaborn figure already opens with.
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
 * A categorical palette taken from the theme's own colour scales rather than
 * from a table of hex literals, so it follows a customised Mantine theme and
 * shifts with the colour scheme: shade 6 reads on white, shade 4 on the dark
 * background, where 6 goes muddy.
 *
 * Pass it as the `fallback` of `resolveCategoricalPalette` — a branded
 * deployment's own colorway still wins over it.
 */
export function mantineCategoricalPalette(
  theme?: ScaleCarryingTheme | null,
  isDark = false,
  hues: readonly string[] = MANTINE_COLORWAY_HUES,
): readonly string[] {
  const scales = theme?.colors;
  if (!scales) return TAB10_PALETTE;
  const shade = isDark ? 4 : 6;
  const out = hues.map((hue) => scales[hue]?.[shade]).filter((c): c is string => !!c);
  return out.length ? out : TAB10_PALETTE;
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
export function brandColorway(theme?: BrandCarryingTheme | null): string[] | null {
  const brand = theme?.other?.brand as { plots?: { colorway?: string[] | null } } | null | undefined;
  const colorway = brand?.plots?.colorway;
  return colorway && colorway.length ? colorway : null;
}

/**
 * The categorical palette a renderer should map values through: the brand's
 * when there is one, so a client-rendered viz uses the same hues as the
 * server-rendered figures beside it, and otherwise the palette the renderer
 * has always used.
 */
export function resolveCategoricalPalette(
  theme?: BrandCarryingTheme | null,
  fallback: readonly string[] = TAB10_PALETTE,
): readonly string[] {
  return brandColorway(theme) ?? fallback;
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
 * Sort is locale-aware case-insensitive so capitalisation differences don't
 * flip ordering. Empty / nullish entries are skipped.
 */
export function stableColorMap(
  allValues: readonly (string | null | undefined)[],
  palette: readonly string[] = TAB10_PALETTE,
  overrides?: Record<string, string> | null,
): StableColorMap {
  const cleaned = Array.from(
    new Set(
      allValues
        .filter((v): v is string => v != null && v !== '')
        .map((v) => String(v)),
    ),
  );
  const sorted = [...cleaned].sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' }),
  );
  const lookup = new Map<string, string>();
  sorted.forEach((v, i) => lookup.set(v, palette[i % palette.length]));
  // Apply explicit overrides last so they win over palette-index assignments.
  // This is the channel through which dashboards pin domain-specific colours
  // (habitat → Set1 mapping, lineage → Pango palette, etc.) without forking
  // the renderer per project.
  if (overrides) {
    for (const [key, colour] of Object.entries(overrides)) {
      if (key && colour) lookup.set(key, colour);
    }
  }

  return {
    get(value: string): string {
      const key = String(value);
      const hit = lookup.get(key);
      if (hit) return hit;
      // Fallback for values not in the supplied universe: deterministic hash
      // so a "leaked" value still gets a stable colour across re-renders.
      return palette[hashString(key) % palette.length];
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
