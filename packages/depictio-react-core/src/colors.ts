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
