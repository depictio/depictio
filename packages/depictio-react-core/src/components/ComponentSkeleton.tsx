import React from 'react';
import { Skeleton, Stack, SimpleGrid, Box } from '@mantine/core';

export type SkeletonVariant = 'block' | 'table' | 'image' | 'card' | 'control';

interface ComponentSkeletonProps {
  /**
   * Shape of the placeholder, chosen to echo the component it stands in for so
   * the first-paint layout matches what lands. ``block`` = one full-area panel
   * (figure / map / advanced-viz), ``table`` = a header bar + rows, ``image`` =
   * a tile grid, ``card`` = a title + hero-value stub, ``control`` = an
   * interactive filter widget (title line + input/track bar).
   */
  variant?: SkeletonVariant;
  /** Rows (table) / tiles (image) to draw. Sensible defaults per variant. */
  count?: number;
  /**
   * ``control`` only: draw the title-line stub above the bar. Set false when
   * the surrounding frame already renders the title (e.g. SegmentedControl).
   */
  withTitle?: boolean;
}

/**
 * Shaped loading placeholder shown on a component's *first* paint, in place of
 * the old centred spinner. The grid cell already has fixed dimensions, so the
 * skeleton fills it without shifting layout — the panel keeps its footprint
 * from mount through to data arrival (no CLS, no spinner-then-content jump).
 *
 * Refetches (filter changes, realtime ticks) keep the previous content mounted
 * and use ``RefetchOverlay`` instead — this is only for the empty first load.
 */
const ComponentSkeleton: React.FC<ComponentSkeletonProps> = ({
  variant = 'block',
  count,
  withTitle = true,
}) => {
  if (variant === 'control') {
    return (
      <Stack gap={8} aria-busy style={{ minHeight: 80, justifyContent: 'center' }}>
        {withTitle && <Skeleton height={10} width="45%" radius="sm" />}
        <Skeleton height={28} radius="sm" />
      </Stack>
    );
  }
  if (variant === 'table') {
    const rows = count ?? 7;
    return (
      <Stack gap={8} style={{ flex: 1, minHeight: 0 }} aria-busy>
        <Skeleton height={26} radius="sm" />
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} height={18} radius="sm" />
        ))}
      </Stack>
    );
  }
  if (variant === 'image') {
    const tiles = count ?? 6;
    return (
      <SimpleGrid cols={3} spacing="xs" verticalSpacing="xs" style={{ flex: 1 }} aria-busy>
        {Array.from({ length: tiles }).map((_, i) => (
          <Skeleton key={i} height={90} radius="sm" />
        ))}
      </SimpleGrid>
    );
  }
  if (variant === 'card') {
    return (
      <Stack gap={8} style={{ flex: 1, justifyContent: 'center' }} aria-busy>
        <Skeleton height={12} width="55%" radius="sm" />
        <Skeleton height={28} width="40%" radius="sm" />
      </Stack>
    );
  }
  // block: figure / map / advanced-viz — a single full-area shimmer.
  return (
    <Box style={{ flex: 1, minHeight: 0, display: 'flex' }} aria-busy>
      <Skeleton radius="sm" style={{ flex: 1, minHeight: 0, height: '100%' }} />
    </Box>
  );
};

export default ComponentSkeleton;
