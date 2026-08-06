import React from 'react';
import { Box, Group, Stack, Text } from '@mantine/core';

import { formatSecondary, hexWithAlpha } from './format';
import { METRIC, MetricCaption, MetricStrip, TooltipDivider, TooltipStat } from './tokens';
import StatList from './StatList';
import type { MetricRow } from './types';

/** Compound payload returned by the server's ``box_plot_stats`` aggregation. */
export interface BoxPlotStats {
  min: number;
  max: number;
  q1: number;
  q3: number;
  median: number;
  mean: number;
  lower_whisker: number;
  upper_whisker: number;
  outliers: number[];
  outlier_count: number;
}

const isBoxPlotStats = (v: unknown): v is BoxPlotStats => {
  if (!v || typeof v !== 'object') return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.min === 'number' &&
    typeof o.max === 'number' &&
    typeof o.q1 === 'number' &&
    typeof o.q3 === 'number' &&
    typeof o.median === 'number' &&
    Array.isArray(o.outliers)
  );
};

/**
 * ``box_plot`` — a proper Tukey box-and-whisker plot.
 *
 *  Outlier dot   whisker low      box (IQR)       whisker high   Outlier dot
 *  •             ├────[█████│██▲██]──────────┤                              •
 *  min           lo-w     Q1 med^mean Q3    up-w                            max
 *
 *  - Box: Q1 → Q3 (middle 50%)
 *  - Whiskers: extend to the most extreme datum still inside the 1.5×IQR fence
 *  - Median: thick vertical line inside the box
 *  - Mean:   small ▲ marker (often differs from median for skewed data)
 *  - Outlier dots: each datum outside the fence
 *  - Min / max: labels for the absolute extremes, which are typically the
 *    outermost outliers rather than the whisker endpoints
 *
 * Falls back to the vertical stat list when the payload does not match, rather
 * than drawing a plot from numbers it does not have.
 */
const BoxPlotMetric: React.FC<{
  rows: MetricRow[];
  color?: string | null;
}> = ({ rows, color }) => {
  const statsRow = rows.find(
    (r) => r.name.toLowerCase() === 'box_plot_stats' && isBoxPlotStats(r.value),
  );

  if (!statsRow) {
    return (
      <StatList
        variant="vertical"
        rows={rows.map((r) => ({
          ...r,
          value: typeof r.value === 'object' ? '—' : r.value,
        }))}
      />
    );
  }

  const s = statsRow.value as BoxPlotStats;

  // A constant column has no spread to draw; say so instead of rendering a
  // degenerate plot where every marker sits on the same pixel.
  if (s.min === s.max) {
    return (
      <MetricStrip>
        <Stack gap={0} align="center">
          <Text size="sm" fw={600} lh={1.2}>
            {formatSecondary(s.median)}
          </Text>
          <MetricCaption>(constant)</MetricCaption>
        </Stack>
      </MetricStrip>
    );
  }

  const range = s.max - s.min;
  const frac = (v: number): number => Math.min(1, Math.max(0, (v - s.min) / range));
  const fLowW = frac(s.lower_whisker);
  const fUpW = frac(s.upper_whisker);
  const fQ1 = frac(s.q1);
  const fQ3 = frac(s.q3);
  const fMed = frac(s.median);
  const fMean = frac(s.mean);

  const TRACK_H = METRIC.chartHeight;
  const AXIS_Y = TRACK_H / 2;
  const BOX_H = 14;
  const BOX_TOP = AXIS_Y - BOX_H / 2;
  const CAP_H = 10; // height of whisker end-cap ticks
  const WHISKER_THICK = 1.5;
  const OUTLIER_R = 2.5;
  const INK = 'var(--mantine-color-text, #111)';
  const MEAN_MARKER = '#E74C3C';

  const iqr = s.q3 - s.q1;
  const skewHint =
    Math.abs(s.mean - s.median) > 0.05 * range
      ? s.mean > s.median
        ? 'right-skewed'
        : 'left-skewed'
      : 'symmetric';

  // Rows ordered low→high so the tooltip reads in the same direction as the
  // chart above it.
  const tooltip = (
    <Stack gap={2}>
      <TooltipStat label="min" value={formatSecondary(s.min)} />
      <TooltipStat label="lower whisker" value={formatSecondary(s.lower_whisker)} />
      <TooltipStat label="Q1" value={formatSecondary(s.q1)} />
      <TooltipStat label="median" value={formatSecondary(s.median)} strong />
      <TooltipStat label="mean ▲" value={formatSecondary(s.mean)} />
      <TooltipStat label="Q3" value={formatSecondary(s.q3)} />
      <TooltipStat label="upper whisker" value={formatSecondary(s.upper_whisker)} />
      <TooltipStat label="max" value={formatSecondary(s.max)} />
      <TooltipDivider />
      <TooltipStat label="IQR" value={formatSecondary(iqr)} />
      <TooltipStat label="outliers" value={s.outlier_count.toLocaleString()} />
      <TooltipStat label="shape" value={skewHint} />
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} gap={2} ariaLabel="Distribution box plot">
      <Box style={{ width: '100%', position: 'relative', height: TRACK_H }}>
        {/* Whisker baseline — only between the two whisker endpoints */}
        <Box
          style={{
            position: 'absolute',
            left: `${fLowW * 100}%`,
            width: `${Math.max(0, fUpW - fLowW) * 100}%`,
            top: AXIS_Y - WHISKER_THICK / 2,
            height: WHISKER_THICK,
            background: INK,
            opacity: 0.7,
          }}
        />
        {[fLowW, fUpW].map((f, i) => (
          <Box
            key={`cap-${i}`}
            style={{
              position: 'absolute',
              left: `${f * 100}%`,
              top: AXIS_Y - CAP_H / 2,
              height: CAP_H,
              width: WHISKER_THICK,
              marginLeft: -WHISKER_THICK / 2,
              background: INK,
              opacity: 0.85,
            }}
          />
        ))}
        {/* IQR box (Q1 → Q3), tinted with the card's accent colour. */}
        {fQ3 > fQ1 ? (
          <Box
            style={{
              position: 'absolute',
              left: `${fQ1 * 100}%`,
              width: `${(fQ3 - fQ1) * 100}%`,
              top: BOX_TOP,
              height: BOX_H,
              background: hexWithAlpha(color, 0.45),
              border: `1px solid ${hexWithAlpha(color, 0.95)}`,
              borderRadius: 2,
            }}
          />
        ) : null}
        {/* Median line */}
        <Box
          style={{
            position: 'absolute',
            left: `${fMed * 100}%`,
            top: BOX_TOP,
            height: BOX_H,
            width: 2,
            marginLeft: -1,
            background: INK,
          }}
        />
        {/* Mean marker — the mean-vs-median gap is the skew, and it is the one
            thing the five-number summary alone will not show. */}
        <Box
          style={{
            position: 'absolute',
            left: `${fMean * 100}%`,
            top: AXIS_Y - 5,
            marginLeft: -4,
            width: 0,
            height: 0,
            borderLeft: '4px solid transparent',
            borderRight: '4px solid transparent',
            borderBottom: `6px solid ${MEAN_MARKER}`,
          }}
        />
        {/* Outlier dots — capped at 100 by the server; the full count is in the
            tooltip. Older payloads carry only the scalar count, so a missing
            array means "none" rather than a crash. */}
        {(s.outliers ?? []).map((v, i) => (
          <Box
            key={`out-${i}`}
            style={{
              position: 'absolute',
              left: `${frac(v) * 100}%`,
              top: AXIS_Y - OUTLIER_R,
              width: OUTLIER_R * 2,
              height: OUTLIER_R * 2,
              marginLeft: -OUTLIER_R,
              borderRadius: '50%',
              background: 'rgba(127,127,127,0.85)',
              border: `0.5px solid ${INK}`,
            }}
          />
        ))}
      </Box>
      {/* Axis ends + median, so the plot is readable at a narrow card width
          without opening the tooltip. */}
      <Group justify="space-between" gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
        <MetricCaption>{formatSecondary(s.min)}</MetricCaption>
        <MetricCaption strong>{formatSecondary(s.median)}</MetricCaption>
        <MetricCaption>{formatSecondary(s.max)}</MetricCaption>
      </Group>
    </MetricStrip>
  );
};

export default BoxPlotMetric;
