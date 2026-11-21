import { TAB10_PALETTE } from '../../../colors';
import {
  assignColors,
  compareValues,
  reservedKind,
  semanticColor,
  type ColorScheme,
  type OverflowMode,
} from '../../../palettes';
import { pinnedColourFor } from './taxonAliases';
import { columnCategoryColors, type CategoryColorSource } from '../../../categoryColors';

/**
 * The categorical palette for tip colouring when the deployment states no
 * brand of its own: depictio's shared palette (`TAB10_PALETTE` stands for it;
 * `resolveCategoricalPalette` swaps in the scheme's variant). Shared by the
 * full tree and its summary so a value gets the same colour on both.
 */
export const PHYLO_PALETTE: readonly string[] = TAB10_PALETTE;

/**
 * The colours pinned for one column, most specific last: the dashboard's main
 * tab (`inherited_category_colors`), the dashboard (`category_colors`, what its
 * filter chips wear), then the component's own `category_palettes`.
 *
 * So a Kingdom or a site keeps its dashboard colour on the tree without the
 * component repeating it, which one made in the builder, where
 * `category_palettes` has no control, could not do. Null when nothing is
 * pinned, so the palette is handed out alphabetically as before.
 */
export function pinnedPalette(
  source: CategoryColorSource | null | undefined,
  componentPalettes: Record<string, Record<string, string>> | null | undefined,
  column: string | null | undefined,
): Record<string, string> | null {
  if (!column) return null;
  return columnCategoryColors(source, column, componentPalettes?.[column]);
}

/** Value to colour, as the tree and its summary read it. */
export interface PhyloColorScale {
  get(value: string): string;
}

/**
 * The tip colour scale for one column.
 *
 * The values are ranked by tip count (largest first, ties by name) and handed
 * out in that order, so the biggest lineages get the palette's slots and the
 * tail takes the "Other" grey instead of repeating a hue. A value pinned under
 * an alias (SILVA `Proteobacteria` for a GTDB `Pseudomonadota` pin) wears the
 * pinned colour, which free values then skip; labels are never renamed.
 *
 * `tipValues` holds one entry per tip. `universe`, when given (the server's
 * distinct values), also fixes which values exist; those with no tip rank last.
 */
export function phyloColorScale(
  tipValues: Iterable<string | null | undefined>,
  universe: readonly string[] | null | undefined,
  palette: readonly string[],
  pins: Record<string, string> | null | undefined,
  scheme: ColorScheme,
  overflow?: OverflowMode | null,
): PhyloColorScale {
  const counts = new Map<string, number>();
  for (const v of tipValues) {
    if (v == null || v === '') continue;
    counts.set(String(v), (counts.get(String(v)) ?? 0) + 1);
  }
  const values = new Set<string>(counts.keys());
  for (const v of universe ?? []) if (v != null && v !== '') values.add(String(v));
  const ranked = Array.from(values).sort(
    (a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0) || compareValues(a, b),
  );

  // Each value's pin, found under its own name or an alias; the pins the
  // column already holds stay in, so their colours stay reserved.
  const effective: Record<string, string> = { ...(pins ?? {}) };
  for (const v of ranked) {
    const c = pinnedColourFor(v, pins);
    if (c) effective[v] = c;
  }
  const lookup = assignColors(ranked, { pinned: effective, palette, scheme, ranked: true, overflow });
  return {
    get(value: string): string {
      const key = String(value);
      const hit = lookup.get(key) ?? pinnedColourFor(key, pins);
      if (hit) return hit;
      const kind = key === '' ? null : reservedKind(key);
      return semanticColor(kind ?? 'other', scheme);
    },
  };
}
