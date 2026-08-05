import React from 'react';
import { Stack } from '@mantine/core';

import { hexWithAlpha } from './format';
import { Meter, MetricCaption, MetricStrip, TooltipNote, TooltipStat } from './tokens';
import type { CompletenessPayload } from './types';

/**
 * ``completeness`` — how much of the column is actually populated.
 *
 *   ▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱
 *   128/150 filled (85%) · 22 missing
 *
 * The first question asked of any clinical or sample metadata table, and one a
 * hero ``count`` actively hides: ``count`` already skips nulls, so a card
 * reading "128" looks complete until you know the table has 150 rows.
 */
const CompletenessMetric: React.FC<{
  payload: CompletenessPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  if (!payload.total) return null;
  const pct = Math.round(payload.fill_rate * 100);

  const tooltip = (
    <Stack gap={2}>
      <TooltipStat label="column" value={payload.column} />
      <TooltipStat
        label="filled"
        value={`${payload.filled.toLocaleString()} / ${payload.total.toLocaleString()}`}
        strong
      />
      <TooltipStat label="missing" value={payload.nulls.toLocaleString()} />
      <TooltipNote>
        Counts nulls only — empty strings and sentinels like "NA" are indistinguishable
        from real values here.
      </TooltipNote>
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} ariaLabel={`Completeness of ${payload.column}`}>
      <Meter
        segments={[{ key: 'filled', share: payload.fill_rate, color: hexWithAlpha(color, 0.85) }]}
      />
      <MetricCaption strong>
        {payload.filled.toLocaleString()}/{payload.total.toLocaleString()} filled ({pct}%)
        {payload.nulls > 0 ? ` · ${payload.nulls.toLocaleString()} missing` : ''}
      </MetricCaption>
    </MetricStrip>
  );
};

export default CompletenessMetric;
