import { columnCategoryColors, type CategoryColorSource } from '../../../categoryColors';

/**
 * Muted publication-friendly palette for categorical tip colouring, used when
 * the deployment states no brand of its own. Shared by the full tree and its
 * summary so a value gets the same colour on both.
 */
export const PHYLO_PALETTE: readonly string[] = [
  '#4C72B0',
  '#DD8452',
  '#55A868',
  '#C44E52',
  '#8172B3',
  '#937860',
  '#DA8BC3',
  '#8C8C8C',
];

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
