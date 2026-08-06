import React from 'react';
import { Group, Stack } from '@mantine/core';

import { compactNumber, hexWithAlpha, percent } from './format';
import { METRIC, MetricCaption, MetricStrip, TooltipDivider, TooltipStat } from './tokens';
import type { TrendPayload } from './types';

/** Buckets to name in the tooltip. Enough to see the shape, few enough that the
 *  tooltip stays a tooltip. */
const TOOLTIP_POINTS = 6;

/**
 * ``trend`` — the hero metric recomputed per bucket of an ordered column.
 *
 *   ╱‾╲__╱‾‾‾
 *   2024-01 → 2024-09 · 12.4k → 18.1k ▲ 46%
 *
 * The one question none of the other layouts can answer: is this number moving?
 * ``attrition`` walks a fixed sequence of *columns* (a pipeline's stages), while
 * this walks the *values* of one column (a date, a run index, a batch), so it is
 * the layout for anything that accumulates over time.
 *
 * The line is scaled to the payload's own min/max rather than to zero: a 3%
 * drift on a large baseline is the interesting signal, and a zero-anchored axis
 * would flatten it into a straight line.
 */
const TrendMetric: React.FC<{
  payload: TrendPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  const points = payload.points || [];
  if (points.length < 2) return null;

  const span = payload.max - payload.min;
  const stroke = hexWithAlpha(color, 0.9);
  const area = hexWithAlpha(color, 0.18);

  // Normalised to a 100 × chartHeight box, stretched to the card's width by
  // `preserveAspectRatio="none"`. The stroke keeps its width regardless, which
  // is what `vector-effect` is for.
  const H = METRIC.chartHeight;
  const xy = points.map((p, i) => {
    const x = (i / (points.length - 1)) * 100;
    // A flat series (span 0) sits on the middle of the box rather than on an
    // edge, where it would read as "at the minimum".
    const y = span > 0 ? H - ((p.value - payload.min) / span) * H : H / 2;
    return [x, y] as const;
  });
  const line = xy.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const fill = `0,${H} ${line} 100,${H}`;
  const [lastX, lastY] = xy[xy.length - 1];

  const rising = payload.change !== null && payload.change > 0;
  const flat = payload.change === null || Math.abs(payload.change) < 0.005;
  const arrow = flat ? '·' : rising ? '▲' : '▼';
  const changeText =
    payload.change === null ? 'n/a' : `${arrow} ${percent(Math.abs(payload.change))}`;

  // Head and tail of the series: the middle is visible on the line, the ends
  // are the numbers a reader wants to quote.
  const named =
    points.length <= TOOLTIP_POINTS
      ? points
      : [...points.slice(0, TOOLTIP_POINTS - 2), ...points.slice(-2)];

  const tooltip = (
    <Stack gap={2}>
      <TooltipStat label="metric" value={`${payload.aggregation} of ${payload.column}`} />
      <TooltipStat label="over" value={payload.axis} />
      <TooltipStat label="buckets" value={points.length.toLocaleString()} />
      <TooltipDivider />
      {named.map((p, i) => (
        <TooltipStat
          key={`${p.label}-${i}`}
          label={p.label}
          value={compactNumber(p.value)}
        />
      ))}
      {points.length > TOOLTIP_POINTS ? (
        <MetricCaption>
          {points.length - named.length} more bucket
          {points.length - named.length === 1 ? '' : 's'} between
        </MetricCaption>
      ) : null}
      <TooltipDivider />
      <TooltipStat
        label="change"
        value={
          payload.change === null
            ? 'n/a (first bucket is zero)'
            : `${compactNumber(payload.first)} → ${compactNumber(payload.last)} (${changeText})`
        }
        strong
      />
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} gap={2} ariaLabel={`Trend of ${payload.column}`}>
      <svg
        viewBox={`0 0 100 ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: H, display: 'block', overflow: 'visible' }}
        role="img"
        aria-label={`${payload.aggregation} of ${payload.column} over ${payload.axis}`}
      >
        <polygon points={fill} fill={area} />
        <polyline
          points={line}
          fill="none"
          stroke={stroke}
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
        {/* Marker on the latest bucket — the value the card's hero number is
            closest to, and the one the eye should land on. */}
        <circle cx={lastX} cy={lastY} r={2} fill={stroke} vectorEffect="non-scaling-stroke" />
      </svg>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <MetricCaption>{points[0].label}</MetricCaption>
        <MetricCaption strong>
          {compactNumber(payload.first)} → {compactNumber(payload.last)} {changeText}
        </MetricCaption>
      </Group>
    </MetricStrip>
  );
};

export default TrendMetric;
