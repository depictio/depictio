import React from 'react';
import { Box, Group, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { CHECK_LAYER_RUNS, checkStatusLabel, checkStatusVisual } from '../componentVisuals';
import type { RecordedCheck } from '../types';

/**
 * Which gates a generated component went through, and how each answered.
 *
 * The one surface both the running panel and the draft review draw it from,
 * so a tile reads the same during the run and a day later. Two shapes of the
 * same list: `compact` is a row of marks for a card in a grid, `list` names
 * every gate for the tile under review.
 *
 * The empty case matters as much as the full one. A tile whose checks were
 * never recorded (a draft generated before the run kept them) says so rather
 * than drawing nothing, because nothing reads as "fine" next to neighbours
 * carrying a row of green.
 */
export interface CheckStripProps {
  checks?: RecordedCheck[] | null;
  /** The finding a successful repair round corrected, when there was one. */
  repair?: string | null;
  variant?: 'compact' | 'list';
  /** Left off the compact form, where the card's own testid is the handle. */
  testId?: string;
}

const ICON_SIZE = 13;

function tooltipLabel(check: RecordedCheck): string {
  const runs = CHECK_LAYER_RUNS[check.layer] ?? check.layer;
  const head = `${check.layer}: ${checkStatusLabel(check.status)}`;
  return check.detail ? `${head}\n${runs}\n${check.detail}` : `${head}\n${runs}`;
}

/** The coloured mark heading one row of the `list` form. */
const RowMark: React.FC<{ icon: string; color: string }> = ({ icon, color }) => (
  <Box c={color} style={{ display: 'inline-flex', flexShrink: 0, marginTop: 1 }}>
    <Icon icon={icon} width={ICON_SIZE} height={ICON_SIZE} />
  </Box>
);

const CheckStrip: React.FC<CheckStripProps> = ({
  checks,
  repair,
  variant = 'compact',
  testId,
}) => {
  if (!checks || checks.length === 0) {
    return (
      <Text size="xs" c="dimmed" data-testid={testId} data-status="not-recorded">
        Checks not recorded for this tile.
      </Text>
    );
  }

  if (variant === 'compact') {
    return (
      <Group gap={4} wrap="nowrap" data-testid={testId}>
        {checks.map((check) => {
          const { icon, color } = checkStatusVisual(check.status);
          return (
            <Tooltip
              key={check.layer}
              label={tooltipLabel(check)}
              multiline
              w={280}
              withArrow
              openDelay={200}
            >
              <Box
                c={color}
                style={{ display: 'inline-flex' }}
                data-layer={check.layer}
                data-status={check.status}
              >
                <Icon icon={icon} width={ICON_SIZE} height={ICON_SIZE} />
              </Box>
            </Tooltip>
          );
        })}
      </Group>
    );
  }

  return (
    <Stack gap={2} data-testid={testId}>
      {checks.map((check) => {
        const { icon, color } = checkStatusVisual(check.status);
        return (
          <Group
            key={check.layer}
            gap={6}
            wrap="nowrap"
            align="flex-start"
            data-layer={check.layer}
            data-status={check.status}
          >
            <RowMark icon={icon} color={color} />
            <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
              {check.layer}
            </Text>
            {check.detail && (
              <Text size="xs" c="dimmed" lineClamp={2} title={check.detail} style={{ minWidth: 0 }}>
                {check.detail}
              </Text>
            )}
          </Group>
        );
      })}
      {repair && (
        <Group gap={6} wrap="nowrap" align="flex-start" data-testid="draft-review-repair">
          <RowMark icon="mdi:wrench-outline" color="yellow" />
          <Text size="xs" c="dimmed" lineClamp={3} title={repair} style={{ minWidth: 0 }}>
            {`Repaired: ${repair}`}
          </Text>
        </Group>
      )}
    </Stack>
  );
};

export default CheckStrip;
