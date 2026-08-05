import React from 'react';
import { Stack } from '@mantine/core';

import { percent, rankTint } from './format';
import { TooltipDivider, TooltipNote, TooltipStat } from './tokens';
import type { BreakdownPayload } from './types';

/** Evenness → plain-language reading. Shared so ``composition``, ``donut`` and
 *  ``concentration`` describe the same distribution in compatible terms. */
export function evennessLabel(evenness: number): string {
  if (evenness >= 0.85) return 'balanced';
  if (evenness >= 0.6) return 'fairly even';
  if (evenness >= 0.3) return 'uneven';
  return 'dominated';
}

/** How concentrated a top-N share is, in words. */
export function concentrationLabel(topShare: number): string {
  if (topShare >= 0.75) return 'highly concentrated';
  if (topShare >= 0.4) return 'concentrated';
  return 'long-tailed';
}

/**
 * The tooltip body shared by every layout that reads ``__breakdown__``.
 *
 * ``composition``, ``donut`` and ``concentration`` each used to spell out the
 * same eleven rows — column, total, distinct count, one row per segment, the
 * tail, the evenness reading — with small divergences in wording and ordering
 * that made the same data look like different data depending on the layout.
 */
export const BreakdownTooltip: React.FC<{
  payload: BreakdownPayload;
  color?: string | null;
  /** Draw a colour swatch beside each value, matching the chart's segments.
   *  Off for `concentration`, which draws no segments to match. */
  swatches?: boolean;
}> = ({ payload, color, swatches = true }) => {
  const tailRows = Math.max(0, payload.unique_values - payload.top.length);
  const tailShare = Math.max(0, 1 - payload.top_share);
  const evenness = typeof payload.evenness === 'number' ? payload.evenness : null;

  return (
    <Stack gap={2}>
      <TooltipStat label="column" value={payload.column} />
      <TooltipStat label="total" value={payload.total.toLocaleString()} />
      <TooltipStat label="unique values" value={payload.unique_values.toLocaleString()} />
      <TooltipDivider />
      {payload.top.map((row, idx) => (
        <TooltipStat
          key={row.name}
          label={row.name}
          swatch={swatches ? rankTint(color, idx) : undefined}
          value={`${row.count.toLocaleString()} (${percent(row.percent)})`}
        />
      ))}
      {tailRows > 0 ? (
        <TooltipStat
          label={`other (${tailRows.toLocaleString()} more)`}
          value={percent(tailShare)}
        />
      ) : null}
      <TooltipDivider />
      <TooltipStat
        label={`top ${payload.top.length} share`}
        value={`${percent(payload.top_share)} — ${concentrationLabel(payload.top_share)}`}
        strong
      />
      {evenness !== null ? (
        <>
          <TooltipStat
            label="evenness"
            value={`${evenness.toFixed(2)} — ${evennessLabel(evenness)}`}
          />
          <TooltipNote>1.00 = every value equally frequent; 0 = one dominates.</TooltipNote>
        </>
      ) : null}
    </Stack>
  );
};
