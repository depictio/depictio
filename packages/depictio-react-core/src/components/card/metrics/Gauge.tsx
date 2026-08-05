import React from 'react';
import { Group, Stack } from '@mantine/core';

import { hexWithAlpha, percent } from './format';
import { METRIC, MetricCaption, MetricStrip, TooltipDivider, TooltipStat } from './tokens';
import { coverageStatus } from './Coverage';

const R = 24;
const CX = 28;
const CY = 30;
const WIDTH = 56;
const HEIGHT = 34;
const STROKE = 7;
/** Length of the half-circle the needleless gauge sweeps. */
const ARC_LEN = Math.PI * R;
const ARC = `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`;

/**
 * ``gauge`` — the same ``value / max`` as ``coverage``, drawn as a dial.
 *
 *      ╭───────╮
 *     ╱   82%   ╲        36 of 44
 *
 * Reads faster than a bar when the number is a *level* rather than a quantity:
 * "is this close to full" is a glance at a dial, where a horizontal bar has to
 * be measured against its own right edge. Same relationship to ``coverage`` as
 * ``donut`` has to ``composition`` — same numbers, and the choice belongs to
 * whoever is laying out the dashboard.
 *
 * The status colours are shared with ``coverage`` so the two never disagree
 * about what counts as complete.
 */
const GaugeMetric: React.FC<{
  value: number;
  max: number;
  color?: string | null;
}> = ({ value, max, color }) => {
  const share = Math.max(0, Math.min(1, value / max));
  const status = coverageStatus(share);
  const fill = status === 'complete' ? hexWithAlpha(color, 0.9) : 'rgba(250,176,5,0.85)';

  const tooltip = (
    <Stack gap={2}>
      <TooltipStat label="value" value={value.toLocaleString()} />
      <TooltipStat label="maximum" value={max.toLocaleString()} />
      <TooltipStat label="remaining" value={Math.max(0, max - value).toLocaleString()} />
      <TooltipDivider />
      <TooltipStat label="filled" value={percent(share, share === 1 ? 0 : 1)} strong />
      <TooltipStat label="status" value={status} />
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} gap={0} ariaLabel="Gauge">
      <Group gap="sm" wrap="nowrap" align="center" justify="center">
        <svg
          width={WIDTH}
          height={HEIGHT}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ flexShrink: 0, display: 'block' }}
          role="img"
          aria-label={`${percent(share)} of maximum`}
        >
          <path d={ARC} fill="none" stroke={METRIC.track} strokeWidth={STROKE} strokeLinecap="round" />
          <path
            d={ARC}
            fill="none"
            stroke={fill}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={`${share * ARC_LEN} ${ARC_LEN}`}
            style={{ transition: 'stroke-dasharray 200ms ease-out' }}
          />
          <text
            x={CX}
            y={CY - 3}
            textAnchor="middle"
            style={{ fontSize: 12, fontWeight: 700, fill: 'currentColor' }}
          >
            {percent(share)}
          </text>
        </svg>
        <MetricCaption strong>
          {value.toLocaleString()} of {max.toLocaleString()}
        </MetricCaption>
      </Group>
    </MetricStrip>
  );
};

export default GaugeMetric;
