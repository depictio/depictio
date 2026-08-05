import React from 'react';
import { Box, Group, Stack } from '@mantine/core';

import { axisNumber, hexWithAlpha } from './format';
import { METRIC, MetricCaption, MetricStrip, TooltipStat } from './tokens';
import type { HistogramPayload } from './types';

/**
 * ``histogram`` — the distribution's *shape* as a sparkline.
 *
 *   ▁▂▅█▇▄▂▁ ▁▂▄█▆▂
 *   4.3 · med 5.8 · 7.9
 *
 * This is the one thing ``box_plot`` structurally cannot show. Five-number
 * summaries are blind to modality: a bimodal column and a flat one can share
 * min/Q1/median/Q3/max exactly, and the box-plot draws them identically. The
 * bars make the second peak visible at a glance.
 *
 * Bar heights are scaled to the tallest bin, so the shape is preserved but the
 * absolute counts are not readable — that is what the tooltip is for. Empty
 * bins keep a hairline so a gap between two modes reads as "no data here"
 * rather than as a rendering artefact.
 */
const HistogramMetric: React.FC<{
  payload: HistogramPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  const bins = payload.bins || [];
  if (!bins.length) return null;
  const peak = Math.max(...bins);
  if (peak <= 0) return null;

  const fill = hexWithAlpha(color, 0.8);

  const tooltip = (
    <Stack gap={2}>
      <TooltipStat
        label="range"
        value={`${axisNumber(payload.min)} — ${axisNumber(payload.max)}`}
      />
      {payload.median !== null ? (
        <TooltipStat label="median" value={axisNumber(payload.median)} strong />
      ) : null}
      <TooltipStat
        label="values"
        value={(payload.total - payload.nulls).toLocaleString()}
      />
      {payload.nulls > 0 ? (
        <TooltipStat label="missing" value={payload.nulls.toLocaleString()} />
      ) : null}
      <TooltipStat label="tallest bin" value={peak.toLocaleString()} />
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} gap={2} ariaLabel={`Distribution of ${payload.min}–${payload.max}`}>
      <Group gap={1} wrap="nowrap" align="flex-end" style={{ height: METRIC.chartHeight }}>
        {bins.map((count, idx) => (
          <Box
            key={idx}
            style={{
              flex: 1,
              minWidth: 0,
              // Hairline for empty bins: a genuine gap between two modes has to
              // be distinguishable from a rendering glitch.
              height: count > 0 ? `${Math.max(8, (count / peak) * 100)}%` : 1,
              background: count > 0 ? fill : METRIC.remainder,
              borderRadius: 1,
            }}
          />
        ))}
      </Group>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <MetricCaption>{axisNumber(payload.min)}</MetricCaption>
        {payload.median !== null ? (
          <MetricCaption>med {axisNumber(payload.median)}</MetricCaption>
        ) : null}
        <MetricCaption>{axisNumber(payload.max)}</MetricCaption>
      </Group>
    </MetricStrip>
  );
};

export default HistogramMetric;
