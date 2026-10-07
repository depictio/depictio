import { createContext, useContext, useMemo } from 'react';
import { useMantineTheme } from '@mantine/core';

import { brandColorway } from '../colors';
import {
  categoryColorMap,
  chipCategoryDots,
  dashboardColorway,
  type CategoryColorSource,
} from '../categoryColors';

/**
 * The dashboard whose `category_colors` the components below it resolve
 * against. The apps provide the dashboard document itself (it satisfies
 * `CategoryColorSource`); without a provider every value falls through to the
 * brand colorway, then to grey — the same result as a dashboard pinning none.
 */
export const CategoryColorsContext = createContext<CategoryColorSource | null>(null);

export function useCategoryColorSource(): CategoryColorSource | null {
  return useContext(CategoryColorsContext);
}

/**
 * The colorway categories fall back to: the brand the surrounding
 * `BrandScope` resolved (the server derives one from the brand colours when
 * none was authored), else whatever the dashboard states itself.
 */
export function useCategoryPalette(): readonly string[] | null {
  const theme = useMantineTheme();
  const source = useCategoryColorSource();
  return brandColorway(theme) ?? dashboardColorway(source);
}

/** `categoryColorMap` for one column, bound to the provider and the theme. */
export function useCategoryColorMap(
  column: string | null | undefined,
  universe: readonly unknown[],
): Map<string, string> {
  const source = useCategoryColorSource();
  const palette = useCategoryPalette();
  return useMemo(
    () => categoryColorMap(source, column, universe, palette),
    [source, column, universe, palette],
  );
}

/**
 * The colour dots a filter's chips draw, or `null` for none, bound to the
 * provider and the theme: the column's own colours, or for a column without
 * any and at most `maxUnpinned` values, the colorway's (`chipCategoryDots`).
 * Leave `maxUnpinned` out for pinned colours only.
 */
export function useCategoryDotColors(
  column: string | null | undefined,
  universe: readonly unknown[],
  maxUnpinned = 0,
): Map<string, string> | null {
  const source = useCategoryColorSource();
  const palette = useCategoryPalette();
  return useMemo(
    () => chipCategoryDots(source, column, universe, palette, maxUnpinned),
    [source, column, universe, palette, maxUnpinned],
  );
}
