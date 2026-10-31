/**
 * A compact key to the colours of a tile: swatches with labels, or a gradient
 * between the extreme values of an ordered scale. The visual language of the
 * genome browser's status bar, shared with the genome view so both tiles key
 * their colours alike.
 */
import { Box, ColorSwatch, Group, Text, Tooltip } from '@mantine/core';

import type { LegendEntry, LegendRamp } from './trackLegend';

export interface ColourKeyProps {
  /** What the colours colour ("Variants", "model class"); shown before them. */
  title?: string;
  entries?: readonly LegendEntry[];
  ramp?: LegendRamp | null;
  /** `data-testid` of the swatch row and of the gradient. */
  testId?: string;
  rampTestId?: string;
  /** Entries shown before the rest fold into a tooltip. */
  maxEntries?: number;
}

export default function ColourKey({
  title,
  entries = [],
  ramp = null,
  testId = 'colour-key',
  rampTestId = 'colour-key-ramp',
  maxEntries = 8,
}: ColourKeyProps) {
  if (!ramp && entries.length === 0) return null;
  const shown = entries.slice(0, maxEntries);
  const hidden = entries.slice(maxEntries);
  return (
    <Group gap={6} wrap="nowrap" style={{ minWidth: 0, flexShrink: 1 }} data-testid={`${testId}-group`}>
      {title ? (
        <Text size="xs" c="dimmed" fw={600} style={{ flexShrink: 0 }}>
          {title}
        </Text>
      ) : null}
      {ramp ? (
        <Tooltip label={ramp.values.join(' > ')} withinPortal={false}>
          <Group gap={4} wrap="nowrap" data-testid={rampTestId} style={{ flexShrink: 0 }}>
            <Text size="xs" c="dimmed">
              {ramp.from}
            </Text>
            <Box
              style={{
                width: 56,
                height: 8,
                borderRadius: 4,
                background: `linear-gradient(to right, ${ramp.stops.join(', ')})`,
              }}
            />
            <Text size="xs" c="dimmed">
              {ramp.to}
            </Text>
          </Group>
        </Tooltip>
      ) : (
        <Group
          gap={8}
          wrap="nowrap"
          data-testid={testId}
          style={{ minWidth: 0, overflow: 'hidden', flexShrink: 1 }}
        >
          {shown.map((entry) => (
            <Tooltip
              key={entry.color}
              label={entry.names.join(', ')}
              withinPortal={false}
              disabled={entry.names.length < 2}
            >
              <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
                <ColorSwatch color={entry.color} size={8} withShadow={false} />
                <Text size="xs" c="dimmed">
                  {entry.label}
                </Text>
              </Group>
            </Tooltip>
          ))}
          {hidden.length ? (
            <Tooltip label={hidden.flatMap((e) => e.names).join(', ')} withinPortal={false}>
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                +{hidden.length} more
              </Text>
            </Tooltip>
          ) : null}
        </Group>
      )}
    </Group>
  );
}
