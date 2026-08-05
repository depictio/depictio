import React from 'react';
import { Box, Group, Stack } from '@mantine/core';

import { percent, rankTint } from './format';
import { METRIC, MetricCaption, MetricStrip } from './tokens';
import { BreakdownTooltip } from './breakdownTooltip';
import type { BreakdownPayload } from './types';

const SIZE = 54;
const R_OUTER = 25;
const R_INNER = 16;
const CX = SIZE / 2;
const CY = SIZE / 2;

/** Polar coordinate → SVG point on a circle. Angles run clockwise from 12
 *  o'clock, which is where a reader expects a ring to start. */
function polar(cx: number, cy: number, r: number, fraction: number): [number, number] {
  const angle = fraction * 2 * Math.PI - Math.PI / 2;
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
}

/** SVG path for one ring segment (an annular sector) between two fractions. */
function ringSegment(
  cx: number,
  cy: number,
  rOuter: number,
  rInner: number,
  from: number,
  to: number,
): string {
  // A full ring cannot be drawn as a single arc — start and end points would
  // coincide and the path collapses to nothing. Split it in two half arcs.
  if (to - from >= 1) {
    const half = ringSegment(cx, cy, rOuter, rInner, 0, 0.5);
    return `${half} ${ringSegment(cx, cy, rOuter, rInner, 0.5, 1)}`;
  }
  const [x0, y0] = polar(cx, cy, rOuter, from);
  const [x1, y1] = polar(cx, cy, rOuter, to);
  const [x2, y2] = polar(cx, cy, rInner, to);
  const [x3, y3] = polar(cx, cy, rInner, from);
  const largeArc = to - from > 0.5 ? 1 : 0;
  return [
    `M ${x0} ${y0}`,
    `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${x1} ${y1}`,
    `L ${x2} ${y2}`,
    `A ${rInner} ${rInner} 0 ${largeArc} 0 ${x3} ${y3}`,
    'Z',
  ].join(' ');
}

/**
 * ``donut`` — the top-N shares as a ring, distinct-value count in the hole.
 *
 * Same payload as ``composition``, but part-of-a-whole reads faster on a ring:
 * a single dominant category is a visibly three-quarter-full circle, which no
 * horizontal strip conveys as fast. The legend sits beside the ring so the card
 * stays readable at 2×2.
 */
const DonutMetric: React.FC<{
  payload: BreakdownPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  if (!payload.top.length) return null;

  const segments = payload.top.map((row, idx) => ({ ...row, fill: rankTint(color, idx) }));
  // Derived from top_share, which the server computed over the whole
  // distribution — summing the rounded segment percents would not close.
  const otherShare = Math.max(0, 1 - payload.top_share);

  let cursor = 0;
  const arcs = segments.map((row) => {
    const from = cursor;
    cursor += row.percent;
    return { ...row, from, to: Math.min(1, cursor) };
  });

  const legend = [
    ...segments.map((row) => ({ key: row.name, name: row.name, share: row.percent, fill: row.fill })),
    ...(otherShare > 0
      ? [{ key: '__other__', name: 'other', share: otherShare, fill: METRIC.remainder }]
      : []),
  ];

  return (
    <MetricStrip
      tooltip={<BreakdownTooltip payload={payload} color={color} />}
      gap={0}
      mt={4}
      ariaLabel={`Composition of ${payload.column}`}
    >
      <Group gap="xs" wrap="nowrap" align="center" style={{ minWidth: 0 }}>
        <svg
          width={SIZE}
          height={SIZE}
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          style={{ flexShrink: 0, display: 'block' }}
          role="img"
          aria-label={`Composition of ${payload.column}`}
        >
          {/* Full track first: the remainder shows through wherever the top-N
              arcs don't cover, so "other" needs no arc of its own. */}
          <circle
            cx={CX}
            cy={CY}
            r={(R_OUTER + R_INNER) / 2}
            fill="none"
            stroke={METRIC.track}
            strokeWidth={R_OUTER - R_INNER}
          />
          {arcs.map((arc) =>
            arc.to > arc.from ? (
              <path
                key={arc.name}
                d={ringSegment(CX, CY, R_OUTER, R_INNER, arc.from, arc.to)}
                fill={arc.fill}
              />
            ) : null,
          )}
          <text
            x={CX}
            y={CY}
            textAnchor="middle"
            dominantBaseline="central"
            style={{ fontSize: 13, fontWeight: 700, fill: 'currentColor' }}
          >
            {payload.unique_values.toLocaleString()}
          </text>
        </svg>
        <Stack gap={1} style={{ flex: 1, minWidth: 0 }}>
          {legend.map((row) => (
            <Group key={row.key} gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
              <Box
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: 2,
                  background: row.fill,
                  flexShrink: 0,
                }}
              />
              <Box style={{ flex: 1, minWidth: 0 }}>
                <MetricCaption dimmed={row.key === '__other__'}>{row.name}</MetricCaption>
              </Box>
              <Box style={{ flexShrink: 0 }}>
                <MetricCaption>{percent(row.share)}</MetricCaption>
              </Box>
            </Group>
          ))}
        </Stack>
      </Group>
    </MetricStrip>
  );
};

export default DonutMetric;
