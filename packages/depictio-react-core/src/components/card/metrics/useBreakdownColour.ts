import { useMemo } from 'react';
import { useMantineColorScheme } from '@mantine/core';

import { columnCategoryColors } from '../../../categoryColors';
import { useCategoryColorSource } from '../../../hooks/useCategoryColors';
import { breakdownSegmentColor } from './format';
import type { BreakdownPayload } from './types';

/**
 * The colour of each value of a breakdown, the same on every layout that draws
 * one (bars, donut, composition, tooltip swatches): the dashboard's pin for that
 * value of the breakdown column, the semantic grey of a reserved remainder
 * (Other, Unclassified, NA), else `fallback` (a layout's own flat fill) or the
 * accent's rank tint.
 */
export function useBreakdownColour(
  payload: Pick<BreakdownPayload, 'column'>,
  accent: string | null | undefined,
): (name: unknown, rank: number, fallback?: string) => string {
  const source = useCategoryColorSource();
  const { colorScheme } = useMantineColorScheme();
  const pins = useMemo(() => columnCategoryColors(source, payload.column), [source, payload.column]);
  const scheme = colorScheme === 'dark' ? 'dark' : 'light';
  return (name, rank, fallback) => breakdownSegmentColor(name, rank, accent, pins, scheme, fallback);
}
