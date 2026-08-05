import React from 'react';

import { percent, rankTint } from './format';
import { METRIC, Meter, MetricCaption, MetricStrip } from './tokens';
import { BreakdownTooltip, evennessLabel } from './breakdownTooltip';
import type { BreakdownPayload } from './types';

/**
 * ``composition`` — what the column is *made of*, and whether it is balanced.
 *
 *   ▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▒▒▒▒▒▒
 *   Alpha 45% · Delta 25% · other 30%
 *   balanced (0.87) · 47 values
 *
 * Where ``top_n`` ranks and ``concentration`` quantifies dominance, this shows
 * proportion: one 100%-wide bar split into the top-N segments plus a muted
 * remainder, so the parts always sum to the whole. That makes it the one
 * breakdown layout that stays readable in a 2×1 card, where ``top_n``'s stacked
 * rows have no room.
 *
 * Segment tints step down in opacity by rank, so adjacent slices stay
 * distinguishable without introducing a second hue.
 */
const CompositionMetric: React.FC<{
  payload: BreakdownPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  if (!payload.top.length) return null;

  // Derive the remainder from top_share rather than by summing the segments:
  // the server computed it over the full distribution, so it stays correct even
  // when rounding the individual percents would not close to 100.
  const otherShare = Math.max(0, 1 - payload.top_share);
  const evenness = typeof payload.evenness === 'number' ? payload.evenness : null;

  const legend = payload.top
    .map((row) => `${row.name} ${percent(row.percent)}`)
    .join(' · ');

  return (
    <MetricStrip
      tooltip={<BreakdownTooltip payload={payload} color={color} />}
      ariaLabel={`Composition of ${payload.column}`}
    >
      <Meter
        height={METRIC.meterHeight}
        segments={[
          ...payload.top.map((row, idx) => ({
            key: row.name,
            share: row.percent,
            color: rankTint(color, idx),
          })),
          { key: '__other__', share: otherShare, color: METRIC.remainder },
        ]}
      />
      <MetricCaption>
        {legend}
        {otherShare > 0 ? ` · other ${percent(otherShare)}` : ''}
      </MetricCaption>
      {evenness !== null ? (
        <MetricCaption>
          {evennessLabel(evenness)} ({evenness.toFixed(2)}) ·{' '}
          {payload.unique_values.toLocaleString()} values
        </MetricCaption>
      ) : null}
    </MetricStrip>
  );
};

export default CompositionMetric;
