import { createContext, useContext, useMemo } from 'react';
import { useMantineTheme } from '@mantine/core';

import { brandColorway } from '../colors';
import {
  categoryColorMap,
  dashboardColorway,
  pinnedCategoryDots,
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
 * `pinnedCategoryDots` for one column, bound to the provider: the colour dots
 * a filter's chips draw, or `null` when the dashboard gives the column none.
 * No palette fallback, on purpose (see `categoryColors.ts`).
 */
export function useCategoryDotColors(
  column: string | null | undefined,
  universe: readonly unknown[],
): Map<string, string> | null {
  const source = useCategoryColorSource();
  return useMemo(() => pinnedCategoryDots(source, column, universe), [source, column, universe]);
}
