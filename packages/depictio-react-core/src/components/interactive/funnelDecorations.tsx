/**
 * Shared funnel-filtering decorations (issue #939).
 *
 * Two small pieces of differential color highlighting, used by the
 * categorical filter renderers when the dashboard's funnel toggle is on:
 *
 * - `FunnelOptionMarker`: an option row with a colored dot — teal for values
 *   that still lead to a non-empty result set, dimmed grey for values the
 *   current filter state has exhausted.
 * - `FunnelAvailabilityBadge`: a per-component "n/N available" badge — teal
 *   while the component can still narrow the result set, orange once nothing
 *   (or only one value) remains selectable.
 *
 * Colors come from Mantine theme tokens only.
 */
import React from 'react';
import { Badge, Group, Text, Tooltip } from '@mantine/core';

export const FunnelOptionMarker: React.FC<{
  label: string;
  available: boolean;
}> = ({ label, available }) => (
  <Group gap={6} wrap="nowrap">
    <span
      aria-hidden
      style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        flexShrink: 0,
        backgroundColor: available
          ? 'var(--mantine-color-teal-6)'
          : 'var(--mantine-color-gray-5)',
        opacity: available ? 1 : 0.6,
      }}
    />
    <Text size="sm" c={available ? undefined : 'dimmed'} truncate>
      {label}
    </Text>
  </Group>
);

export const FunnelAvailabilityBadge: React.FC<{
  available: number;
  total: number;
  truncated?: boolean;
}> = ({ available, total, truncated }) => {
  const exhausted = available === 0;
  const tooltip = exhausted
    ? 'No value of this filter matches the current result set'
    : `${available} of ${total} values still lead to a non-empty result set` +
      (truncated ? ' (list truncated)' : '');
  return (
    <Tooltip label={tooltip} withArrow>
      <Badge
        size="xs"
        variant="light"
        color={exhausted ? 'orange' : 'teal'}
        mt={4}
        style={{ alignSelf: 'flex-start', textTransform: 'none' }}
      >
        {available}/{total} available
      </Badge>
    </Tooltip>
  );
};
