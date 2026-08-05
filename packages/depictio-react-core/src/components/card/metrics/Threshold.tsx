import React from 'react';
import { Stack } from '@mantine/core';

import { axisNumber } from './format';
import {
  Meter,
  MetricCaption,
  MetricStrip,
  TooltipDivider,
  TooltipNote,
  TooltipStat,
  VERDICT,
} from './tokens';
import type { ThresholdPayload } from './types';

/**
 * ``threshold`` — how many rows clear a QC cut-off.
 *
 *   ▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▓▓
 *   37/40 pass ≥ 30 · 2 warn · 1 fail
 *
 * The question every nf-core pipeline asks and no other layout answers. A
 * ``box_plot`` of coverage shows the spread but never says whether three
 * samples are unusable; this counts them against the cut-off the lab actually
 * uses. ``direction`` decides which side passes, so it works for both
 * "higher is better" (Q30, breadth) and "lower is better" (duplication,
 * contamination).
 */
const ThresholdMetric: React.FC<{
  payload: ThresholdPayload;
}> = ({ payload }) => {
  const measured = payload.measured || 0;
  if (measured <= 0) return null;
  const passShare = payload.passing / measured;
  const warnShare = payload.warning / measured;
  const failShare = Math.max(0, 1 - passShare - warnShare);
  const comparator = payload.direction === 'max' ? '≤' : '≥';

  const bands: { key: string; label: string; count: number; color: string }[] = [
    { key: 'pass', label: 'pass', count: payload.passing, color: VERDICT.pass },
    ...(payload.warn_threshold !== null
      ? [{ key: 'warn', label: 'warn', count: payload.warning, color: VERDICT.warn }]
      : []),
    { key: 'fail', label: 'fail', count: payload.failing, color: VERDICT.fail },
  ];

  const tooltip = (
    <Stack gap={2}>
      <TooltipStat
        label="criterion"
        value={`${payload.column} ${comparator} ${axisNumber(payload.threshold)}`}
      />
      <TooltipDivider />
      {bands.map((b) => (
        <TooltipStat
          key={b.key}
          label={b.label}
          swatch={b.color}
          value={`${b.count.toLocaleString()} (${Math.round((b.count / measured) * 100)}%)`}
        />
      ))}
      {payload.warn_threshold !== null ? (
        <TooltipNote>
          warn band: {comparator} {axisNumber(payload.warn_threshold)} but not {comparator}{' '}
          {axisNumber(payload.threshold)}
        </TooltipNote>
      ) : null}
      {payload.nulls > 0 ? (
        <>
          <TooltipDivider />
          <TooltipStat label="not measured" value={payload.nulls.toLocaleString()} />
          <TooltipNote>Missing values are neither passed nor failed.</TooltipNote>
        </>
      ) : null}
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} ariaLabel={`Pass rate against ${payload.threshold}`}>
      <Meter
        segments={[
          { key: 'pass', share: passShare, color: VERDICT.pass },
          { key: 'warn', share: warnShare, color: VERDICT.warn },
          { key: 'fail', share: failShare, color: VERDICT.fail },
        ]}
      />
      <MetricCaption strong>
        {payload.passing.toLocaleString()}/{measured.toLocaleString()} pass {comparator}{' '}
        {axisNumber(payload.threshold)}
        {payload.warning > 0 ? ` · ${payload.warning.toLocaleString()} warn` : ''}
        {payload.failing > 0 ? ` · ${payload.failing.toLocaleString()} fail` : ''}
      </MetricCaption>
    </MetricStrip>
  );
};

export default ThresholdMetric;
