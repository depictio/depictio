import React from 'react';
import { Stack } from '@mantine/core';

import { hexWithAlpha, percent } from './format';
import {
  METRIC,
  Meter,
  MetricCaption,
  MetricStrip,
  TooltipDivider,
  TooltipNote,
  TooltipStat,
} from './tokens';
import type { UniquenessPayload } from './types';

/**
 * ``uniqueness`` — how much of the column repeats itself.
 *
 *   ▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱
 *   142/150 distinct (95%) · 8 repeated
 *
 * The other half of the data-quality pair: ``completeness`` counts what is
 * missing, this counts what is duplicated. A sample-sheet column meant to be an
 * identifier is the common case — one repeated accession silently doubles every
 * downstream join, and neither a ``count`` card nor a ``completeness`` bar shows
 * it, because nothing is missing.
 *
 * The bar is distinct-over-measured, so a real key reads as a full bar and any
 * shortfall is exactly the duplication.
 */
const UniquenessMetric: React.FC<{
  payload: UniquenessPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  if (!payload.measured) return null;
  const isKey = payload.duplicated === 0;

  const tooltip = (
    <Stack gap={2}>
      <TooltipStat label="column" value={payload.column} />
      <TooltipStat
        label="distinct"
        value={`${payload.distinct.toLocaleString()} / ${payload.measured.toLocaleString()}`}
        strong
      />
      <TooltipStat label="repeated" value={payload.duplicated.toLocaleString()} />
      {payload.nulls > 0 ? (
        <TooltipStat label="missing" value={payload.nulls.toLocaleString()} />
      ) : null}
      {payload.top_repeat ? (
        <>
          <TooltipDivider />
          <TooltipStat
            label="most repeated"
            value={`${payload.top_repeat.name} ×${payload.top_repeat.count.toLocaleString()}`}
          />
        </>
      ) : null}
      <TooltipNote>
        {isKey
          ? 'Every value occurs once — this column can be used as a key.'
          : 'Repeated values are counted against the non-null rows only.'}
      </TooltipNote>
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} ariaLabel={`Uniqueness of ${payload.column}`}>
      <Meter
        segments={[
          { key: 'distinct', share: payload.unique_rate, color: hexWithAlpha(color, 0.85) },
          {
            key: 'repeated',
            share: 1 - payload.unique_rate,
            color: METRIC.remainder,
          },
        ]}
      />
      <MetricCaption strong>
        {payload.distinct.toLocaleString()}/{payload.measured.toLocaleString()} distinct (
        {percent(payload.unique_rate)})
        {isKey ? ' · unique key' : ` · ${payload.duplicated.toLocaleString()} repeated`}
      </MetricCaption>
    </MetricStrip>
  );
};

export default UniquenessMetric;
