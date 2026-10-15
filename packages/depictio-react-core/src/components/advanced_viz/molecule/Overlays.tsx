/**
 * The small overlays drawn over the 3D canvas: colour legend (bottom left),
 * hover tooltip (follows the pointer), model credit (bottom right) and the
 * view buttons (top right).
 */

import React from 'react';
import {
  ActionIcon,
  Anchor,
  Box,
  Code,
  Collapse,
  CopyButton,
  Group,
  Paper,
  Popover,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { LegendSpec } from './residueData';
import type { ExplanationDetail, ModelExplanationNote } from './resolve';

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

/**
 * The "Technical details" of an external call: collapsed by default, so the
 * popover stays short, but one click away from the exact endpoint. The endpoint
 * is shown as text (and copyable), never linked: it is not a page to open.
 */
const TechnicalDetails: React.FC<{ details: ExplanationDetail[] }> = ({ details }) => {
  const [open, setOpen] = React.useState(false);
  const panelId = React.useId();
  if (!details.length) return null;
  return (
    <Box>
      <UnstyledButton
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
      >
        <Icon icon={open ? 'tabler:chevron-down' : 'tabler:chevron-right'} width={12} height={12} />
        <Text size="xs" c="dimmed" fw={500}>
          {open ? 'Hide details' : 'Show details'}
        </Text>
      </UnstyledButton>
      <Collapse in={open} id={panelId}>
        <Box component="dl" m={0} mt={6}>
          <Stack gap={6}>
            {details.map((row) => (
              <Box key={row.label}>
                <Text component="dt" size="xs" c="dimmed" fw={600}>
                  {row.label}
                </Text>
                <Box component="dd" m={0}>
                  {row.code ? (
                    <Group gap={4} wrap="nowrap" align="flex-start">
                      <Code block style={{ flex: 1, minWidth: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                        {row.value}
                      </Code>
                      <CopyButton value={row.value} timeout={1500}>
                        {({ copied, copy }) => (
                          <Tooltip label={copied ? 'Copied' : 'Copy'} withinPortal>
                            <ActionIcon
                              size="xs"
                              variant="subtle"
                              color="gray"
                              aria-label={`Copy ${row.label.toLowerCase()}`}
                              onClick={copy}
                            >
                              <Icon icon={copied ? 'tabler:check' : 'tabler:copy'} width={12} height={12} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                      </CopyButton>
                    </Group>
                  ) : (
                    <Text size="xs">{row.value}</Text>
                  )}
                </Box>
              </Box>
            ))}
          </Stack>
        </Box>
      </Collapse>
    </Box>
  );
};

/**
 * Model credit (bottom right). With `info`, a small info button next to it
 * opens a note on where the structure comes from and how to read it.
 */
export const MoleculeCredit: React.FC<{
  text: string | null;
  info?: ModelExplanationNote | null;
}> = ({
  text,
  info = null,
}) =>
  text || info ? (
    <Group
      gap={4}
      wrap="nowrap"
      style={{ position: 'absolute', right: 6, bottom: 4, zIndex: 2, pointerEvents: 'none' }}
    >
      {text ? (
        <Text size="xs" c="dimmed">
          {text}
        </Text>
      ) : null}
      {info ? (
        <Popover width={300} position="top-end" withArrow shadow="md" withinPortal>
          <Popover.Target>
            <ActionIcon
              size="xs"
              variant="subtle"
              color="gray"
              aria-label="About this structure"
              style={{ pointerEvents: 'auto' }}
            >
              <Icon icon="tabler:info-circle" width={14} height={14} />
            </ActionIcon>
          </Popover.Target>
          <Popover.Dropdown p="xs">
            <Stack gap={6}>
              <Text size="xs">{info.text}</Text>
              {info.links.length ? (
                <Group gap={10} wrap="wrap">
                  {info.links.map((link) => (
                    <Anchor
                      key={link.href}
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      size="xs"
                    >
                      {link.label}
                    </Anchor>
                  ))}
                </Group>
              ) : null}
              <TechnicalDetails details={info.details} />
            </Stack>
          </Popover.Dropdown>
        </Popover>
      ) : null}
    </Group>
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
