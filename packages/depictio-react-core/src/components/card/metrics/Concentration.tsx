import React from 'react';
import { Text } from '@mantine/core';

import { hexWithAlpha, percent } from './format';
import { MetricCaption, MetricStrip } from './tokens';
import { BreakdownTooltip } from './breakdownTooltip';
import type { BreakdownPayload } from './types';

/**
 * ``concentration`` — one line answering "is there a dominant value?".
 *
 *   Top 3 cover 18% of 1,326 rows
 *   P681H, D614G, P323L
 *
 * Same payload as ``top_n``, without the bars: useful when the *answer* is what
 * matters and the per-value detail is noise. It is also the shortest breakdown
 * strip, so it is the one that fits under a card that already spends its height
 * on a large hero value.
 */
const ConcentrationMetric: React.FC<{
  payload: BreakdownPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  if (!payload.top.length) return null;
  const names = payload.top.map((r) => r.name).join(', ');

  return (
    <MetricStrip
      tooltip={<BreakdownTooltip payload={payload} color={color} swatches={false} />}
      gap={2}
      ariaLabel={`Concentration of ${payload.column}`}
    >
      <Text size="xs" lh={1.25} truncate style={{ minWidth: 0 }}>
        <Text component="span" fw={700} style={{ color: hexWithAlpha(color, 0.85) }}>
          Top {payload.top.length} cover {percent(payload.top_share)}
        </Text>
        <Text component="span" c="dimmed">
          {' '}
          of {payload.total.toLocaleString()} rows
        </Text>
      </Text>
      <MetricCaption>{names}</MetricCaption>
    </MetricStrip>
  );
};

export default ConcentrationMetric;
