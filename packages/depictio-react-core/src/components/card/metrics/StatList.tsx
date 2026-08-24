import React from 'react';
import { Group, SimpleGrid, Stack, Text } from '@mantine/core';

import { formatSecondary } from './format';
import { MetricCaption, MetricStrip } from './tokens';
import type { MetricRow } from './types';

/** Aggregation names are stored as snake_case keys ("box_plot_stats",
 *  "nunique"); the strip is the only place a user reads them. */
const humanise = (name: string) => name.replace(/_/g, ' ');

/**
 * The three layouts that just print the card's secondary aggregations.
 *
 * `vertical`  label left, value right, one per line — best for two or three.
 * `compact`   one row, values centred under their labels — best for three.
 * `grid`      two columns of label+value pairs — best for four to six, where
 *             `compact` squeezes each column below a readable width and
 *             `vertical` grows a list taller than the card.
 *
 * `grid` exists because the card builder happily offers six aggregations while
 * both older layouts stop being legible at four.
 */
const StatList: React.FC<{
  rows: MetricRow[];
  variant: 'vertical' | 'compact' | 'grid';
}> = ({ rows, variant }) => {
  if (!rows.length) return null;

  if (variant === 'compact') {
    return (
      <MetricStrip>
        <Group gap="xs" wrap="nowrap" justify="space-between">
          {rows.map((row) => (
            <Stack key={row.name} gap={0} align="center" style={{ flex: 1, minWidth: 0 }}>
              <MetricCaption>{humanise(row.name)}</MetricCaption>
              <Text size="sm" fw={600} lh={1.2} ta="center" truncate style={{ minWidth: 0 }}>
                {formatSecondary(row.value)}
              </Text>
            </Stack>
          ))}
        </Group>
      </MetricStrip>
    );
  }

  if (variant === 'grid') {
    return (
      <MetricStrip>
        <SimpleGrid cols={2} spacing="xs" verticalSpacing={2}>
          {rows.map((row) => (
            <Stack key={row.name} gap={0} style={{ minWidth: 0 }}>
              <MetricCaption>{humanise(row.name)}</MetricCaption>
              <Text size="sm" fw={600} lh={1.2} truncate style={{ minWidth: 0 }}>
                {formatSecondary(row.value)}
              </Text>
            </Stack>
          ))}
        </SimpleGrid>
      </MetricStrip>
    );
  }

  return (
    <MetricStrip>
      {rows.map((row) => (
        <Group key={row.name} justify="space-between" gap="xs" wrap="nowrap">
          <MetricCaption>{humanise(row.name)}</MetricCaption>
          <MetricCaption strong>{formatSecondary(row.value)}</MetricCaption>
        </Group>
      ))}
    </MetricStrip>
  );
};

export default StatList;
