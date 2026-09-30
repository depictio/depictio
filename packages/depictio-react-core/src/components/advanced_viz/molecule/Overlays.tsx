/**
 * The small overlays drawn over the 3D canvas: colour legend (bottom left),
 * hover tooltip (follows the pointer), model credit (bottom right) and the
 * view buttons (top right).
 */

import React from 'react';
import { ActionIcon, Box, Group, Paper, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { LegendSpec } from './residueData';

const SWATCH: React.CSSProperties = {
  width: 10,
  height: 10,
  borderRadius: 2,
  flex: '0 0 auto',
};

type SwatchSpec = Extract<NonNullable<LegendSpec>, { kind: 'swatches' }>;

/** The swatches of a legend: one per line, or flowing in rows when `compact`. */
const SwatchList: React.FC<{ legend: SwatchSpec; compact: boolean }> = ({ legend, compact }) => {
  const { items, more } = legend;
  const swatches = items.map((item) => (
    <Group key={item.label} gap={compact ? 4 : 6} wrap="nowrap">
      <span style={{ ...SWATCH, background: item.colour }} />
      <Text size="xs" lineClamp={1}>
        {item.label}
      </Text>
    </Group>
  ));
  const moreNote = more ? (
    <Text size="xs" c="dimmed">
      {compact ? `+${more}` : `and ${more} more`}
    </Text>
  ) : null;
  if (compact) {
    return (
      <Group gap={8} wrap="wrap" style={{ rowGap: 0 }}>
        {swatches}
        {moreNote}
      </Group>
    );
  }
  return (
    <Stack gap={1}>
      {swatches}
      {moreNote}
    </Stack>
  );
};

/**
 * `compact` (a tile at half width or about 400 px high): the swatches flow in
 * rows instead of one per line and the gradient is shorter, so the legend
 * covers a corner of the structure rather than a side of it.
 */
export const MoleculeLegend: React.FC<{ legend: LegendSpec; compact?: boolean }> = ({
  legend,
  compact = false,
}) => {
  if (!legend) return null;
  return (
    <Paper
      withBorder
      shadow="xs"
      p={compact ? 4 : 6}
      radius="sm"
      style={{
        position: 'absolute',
        left: 6,
        bottom: 6,
        maxWidth: compact ? '70%' : '55%',
        opacity: 0.92,
        zIndex: 2,
        pointerEvents: 'none',
      }}
    >
      <Text size="xs" fw={600} mb={compact ? 0 : 2}>
        {legend.title}
      </Text>
      {legend.kind === 'swatches' ? (
        <SwatchList legend={legend} compact={compact} />
      ) : (
        <Group gap={6} wrap="nowrap">
          <Text size="xs">{legend.min}</Text>
          <span
            style={{
              width: compact ? 56 : 80,
              height: 8,
              borderRadius: 2,
              background: `linear-gradient(to right, ${legend.stops.join(', ')})`,
            }}
          />
          <Text size="xs">{legend.max}</Text>
        </Group>
      )}
    </Paper>
  );
};

export interface TooltipLine {
  label: string;
  value: string;
}

export const MoleculeTooltip: React.FC<{
  x: number;
  y: number;
  title: string;
  lines: TooltipLine[];
  bounds: { width: number; height: number };
}> = ({ x, y, title, lines, bounds }) => {
  // Flip to the other side of the pointer near the right or bottom edge.
  const left = x + 14 + 220 > bounds.width ? Math.max(4, x - 14 - 220) : x + 14;
  const boxHeight = 24 + lines.length * 18;
  const top = y + 14 + boxHeight > bounds.height ? Math.max(4, y - 14 - boxHeight) : y + 14;
  return (
    <Paper
      withBorder
      shadow="sm"
      p={6}
      radius="sm"
      style={{ position: 'absolute', left, top, width: 220, pointerEvents: 'none', zIndex: 3 }}
    >
      <Text size="xs" fw={600}>
        {title}
      </Text>
      {lines.map((l) => (
        <Group key={l.label} gap={6} wrap="nowrap" justify="space-between">
          <Text size="xs" c="dimmed">
            {l.label}
          </Text>
          <Text size="xs" lineClamp={2} ta="right">
            {l.value}
          </Text>
        </Group>
      ))}
    </Paper>
  );
};

export const MoleculeCredit: React.FC<{ text: string | null }> = ({ text }) =>
  text ? (
    <Text
      size="xs"
      c="dimmed"
      style={{ position: 'absolute', right: 6, bottom: 4, zIndex: 2, pointerEvents: 'none' }}
    >
      {text}
    </Text>
  ) : null;

export const MoleculeViewButtons: React.FC<{
  onReset: () => void;
  onSnapshot: () => void;
  spinning: boolean;
  onSpin: () => void;
}> = ({ onReset, onSnapshot, spinning, onSpin }) => (
  <Box style={{ position: 'absolute', right: 6, top: 6, zIndex: 2 }}>
    <Group gap={4}>
      <Tooltip label="Reset view" withinPortal>
        <ActionIcon size="sm" variant="default" aria-label="Reset view" onClick={onReset}>
          <Icon icon="tabler:focus-centered" width={14} height={14} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label={spinning ? 'Stop spinning' : 'Spin'} withinPortal>
        <ActionIcon
          size="sm"
          variant={spinning ? 'filled' : 'default'}
          aria-label="Spin"
          aria-pressed={spinning}
          onClick={onSpin}
        >
          <Icon icon="tabler:rotate-360" width={14} height={14} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Save as PNG" withinPortal>
        <ActionIcon size="sm" variant="default" aria-label="Save as PNG" onClick={onSnapshot}>
          <Icon icon="tabler:camera" width={14} height={14} />
        </ActionIcon>
      </Tooltip>
    </Group>
  </Box>
);
