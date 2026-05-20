import React from 'react';
import { Box, Group, Stack, Text, Tooltip } from '@mantine/core';

export type SecondaryLayout =
  | 'vertical'
  | 'compact'
  | 'box_plot'
  | 'top_n'
  | 'coverage'
  | 'concentration';

/** Server-computed payload for ``top_n`` / ``concentration`` layouts. Lives in
 *  ``rows`` under the synthetic name ``__breakdown__`` — populated by the
 *  ``bulk_compute_cards`` endpoint when ``breakdown_col`` is bound. */
interface BreakdownPayload {
  column: string;
  total: number;
  top: { name: string; count: number; percent: number }[];
  top_share: number;
  unique_values: number;
}

const isBreakdownPayload = (v: unknown): v is BreakdownPayload => {
  if (!v || typeof v !== 'object') return false;
  const o = v as Record<string, unknown>;
  return Array.isArray(o.top) && typeof o.total === 'number';
};

interface SecondaryMetricsProps {
  rows: { name: string; value: unknown }[];
  layout?: SecondaryLayout;
  /** Hex colour used to tint the IQR box + median bar in `box_plot` layout
   *  and the top-N bars / coverage fill. Falls back to teal. */
  color?: string | null;
  /** Numerator for ``layout: coverage`` — the card's hero value. */
  coverageValue?: number | null;
  /** Denominator for ``layout: coverage`` — e.g. 44 samples / 11 ORFs. */
  coverageMax?: number | null;
}

const SecondaryMetrics: React.FC<SecondaryMetricsProps> = ({
  rows,
  layout = 'vertical',
  color,
  coverageValue,
  coverageMax,
}) => {
  if (layout === 'box_plot') {
    if (!rows.length) return null;
    return <BoxPlotMetric rows={rows} color={color} />;
  }

  if (layout === 'top_n') {
    const breakdownRow = rows.find(
      (r) => r.name === '__breakdown__' && isBreakdownPayload(r.value),
    );
    if (!breakdownRow) return null;
    return <TopNMetric payload={breakdownRow.value as BreakdownPayload} color={color} />;
  }

  if (layout === 'concentration') {
    const breakdownRow = rows.find(
      (r) => r.name === '__breakdown__' && isBreakdownPayload(r.value),
    );
    if (!breakdownRow) return null;
    return (
      <ConcentrationMetric payload={breakdownRow.value as BreakdownPayload} color={color} />
    );
  }

  if (layout === 'coverage') {
    if (
      typeof coverageValue !== 'number' ||
      typeof coverageMax !== 'number' ||
      coverageMax <= 0
    ) {
      // Fall through to vertical if the renderer wasn't given the inputs.
      // (Avoids rendering a broken / always-zero bar.)
    } else {
      return (
        <CoverageMetric value={coverageValue} max={coverageMax} color={color} />
      );
    }
  }

  if (!rows.length) return null;

  if (layout === 'compact') {
    return (
      <Group gap="xs" px="sm" pb="xs" mt={4} wrap="nowrap" justify="space-between">
        {rows.map((row) => (
          <Stack key={row.name} gap={0} align="center" style={{ flex: 1, minWidth: 0 }}>
            <Text size="xs" c="dimmed" tt="capitalize" lh={1.1} ta="center">
              {row.name.replace(/_/g, ' ')}
            </Text>
            <Text size="sm" fw={600} lh={1.2} ta="center">
              {formatSecondary(row.value)}
            </Text>
          </Stack>
        ))}
      </Group>
    );
  }

  // vertical (default)
  return (
    <Stack gap={4} mt="xs" px="sm" pb="sm">
      {rows.map((row) => (
        <Group key={row.name} justify="space-between" gap="xs" wrap="nowrap">
          <Text size="xs" c="dimmed" tt="capitalize">
            {row.name.replace(/_/g, ' ')}
          </Text>
          <Text size="xs" fw={500}>
            {formatSecondary(row.value)}
          </Text>
        </Group>
      ))}
    </Stack>
  );
};

/** Compound payload returned by the server's ``box_plot_stats`` aggregation. */
interface BoxPlotStats {
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
    typeof o.median === 'number'
  );
};

/**
 * Box-plot variant — proper Tukey box-and-whisker plot.
 *
 *  Outlier dot   whisker low      box (IQR)       whisker high   Outlier dot
 *  •             ├────[█████│██▲██]──────────┤                              •
 *  min           lo-w     Q1 med^mean Q3    up-w                            max
 *
 *  - Box: Q1 → Q3 (middle 50%)
 *  - Whiskers: extend to the most extreme datum still inside the 1.5×IQR
 *    fence (lower_whisker / upper_whisker from the server)
 *  - Median: thick vertical line inside the box
 *  - Mean:   small ▲ marker (often differs from median for skewed data)
 *  - Outlier dots: each datum outside the fence, drawn as small circles
 *  - Min / max: just labels for the absolute extremes (which are typically
 *    the outermost outliers; not whisker endpoints)
 *
 * Consumes one row from the server: `aggregations: [box_plot_stats]` returns
 * a single dict with all 9 fields above. Falls back to vertical layout if
 * the payload doesn't match.
 */
/** Convert a hex colour ("#FF7F00" or "FF7F00") to an `rgba(...)` string
 *  with the given alpha. Returns a sensible teal fallback for invalid input. */
function hexWithAlpha(hex: string | null | undefined, alpha: number): string {
  const fallback = `rgba(69,184,172,${alpha})`;
  if (!hex || typeof hex !== 'string') return fallback;
  const cleaned = hex.replace('#', '').trim();
  if (cleaned.length !== 6 || !/^[0-9a-fA-F]{6}$/.test(cleaned)) return fallback;
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

const BoxPlotMetric: React.FC<{
  rows: { name: string; value: unknown }[];
  color?: string | null;
}> = ({ rows, color }) => {
  const statsRow = rows.find(
    (r) => r.name.toLowerCase() === 'box_plot_stats' && isBoxPlotStats(r.value),
  );

  // No usable box-plot payload — degrade to the vertical stat list rather
  // than render a broken plot.
  if (!statsRow) {
    return (
      <Stack gap={4} mt="xs" px="sm" pb="sm">
        {rows.map((row) => (
          <Group key={row.name} justify="space-between" gap="xs" wrap="nowrap">
            <Text size="xs" c="dimmed" tt="capitalize">
              {row.name.replace(/_/g, ' ')}
            </Text>
            <Text size="xs" fw={500}>
              {typeof row.value === 'object'
                ? '—'
                : formatSecondary(row.value)}
            </Text>
          </Group>
        ))}
      </Stack>
    );
  }

  const s = statsRow.value as BoxPlotStats;

  // Anchor the axis on the actual data range (min..max). If everything is
  // the same value (constant column) just show the value, no chart.
  if (s.min === s.max) {
    return (
      <Stack gap={2} mt={4} px="sm" pb="xs" align="center">
        <Text size="sm" fw={600} lh={1.2}>
          {formatSecondary(s.median)}
        </Text>
        <Text size="xs" c="dimmed">
          (constant)
        </Text>
      </Stack>
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

  // Y geometry — strip stays ~22px tall so the card fits in h=2.
  // `overflow: hidden` on the outer Stack keeps absolutely-positioned
  // outlier dots from leaking past the card edge at narrow widths.
  const TRACK_H = 22;
  const AXIS_Y = TRACK_H / 2;
  const BOX_H = 14;
  const BOX_TOP = AXIS_Y - BOX_H / 2;
  const CAP_H = 10; // height of whisker end-cap ticks
  const WHISKER_THICK = 1.5;
  const OUTLIER_R = 2.5;

  // Tooltip — table-style with rows ordered low→high to mirror the chart
  // direction, plus derived stats (IQR, skew indicator).
  const iqr = s.q3 - s.q1;
  const skewHint =
    Math.abs(s.mean - s.median) > 0.05 * (s.max - s.min)
      ? s.mean > s.median
        ? 'right-skewed'
        : 'left-skewed'
      : 'symmetric';
  const tooltipBody = (
    <Stack gap={2} miw={220}>
      <TooltipRow label="min" value={s.min} hint="data extreme" />
      <TooltipRow label="lower whisker" value={s.lower_whisker} hint="Q1 − 1.5×IQR fence" />
      <TooltipRow label="Q1" value={s.q1} accent="teal" />
      <TooltipRow label="median" value={s.median} accent="bold" marker="│" />
      <TooltipRow label="mean" value={s.mean} accent="red" marker="▲" />
      <TooltipRow label="Q3" value={s.q3} accent="teal" />
      <TooltipRow label="upper whisker" value={s.upper_whisker} hint="Q3 + 1.5×IQR fence" />
      <TooltipRow label="max" value={s.max} hint="data extreme" />
      <Box style={{ height: 1, background: 'rgba(255,255,255,0.18)', margin: '4px 0' }} />
      <TooltipRow label="IQR" value={iqr} dim />
      <TooltipRow label="outliers" value={s.outlier_count} dim />
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>
          shape
        </Text>
        <Text size="xs" fw={500} lh={1.2}>
          {skewHint}
        </Text>
      </Group>
    </Stack>
  );

  return (
    <Stack
      gap={2}
      mt={0}
      px="xs"
      pb="xs"
      style={{
        overflow: 'hidden',
        minWidth: 0,
        position: 'relative',
        zIndex: 2,
      }}
    >
      <Tooltip
        label={tooltipBody}
        multiline
        w={260}
        withArrow
        position="bottom"
        openDelay={150}
        styles={{ tooltip: { padding: '8px 10px' } }}
      >
        <Box style={{ width: '100%', cursor: 'help', position: 'relative', height: TRACK_H }}>
          {/* Whisker baseline — only between the two whisker endpoints */}
          <Box
            style={{
              position: 'absolute',
              left: `${fLowW * 100}%`,
              width: `${Math.max(0, fUpW - fLowW) * 100}%`,
              top: AXIS_Y - WHISKER_THICK / 2,
              height: WHISKER_THICK,
              background: 'var(--mantine-color-text, #111)',
              opacity: 0.7,
            }}
          />
          {/* Lower whisker end-cap */}
          <Box
            style={{
              position: 'absolute',
              left: `${fLowW * 100}%`,
              top: AXIS_Y - CAP_H / 2,
              height: CAP_H,
              width: WHISKER_THICK,
              marginLeft: -WHISKER_THICK / 2,
              background: 'var(--mantine-color-text, #111)',
              opacity: 0.85,
            }}
          />
          {/* Upper whisker end-cap */}
          <Box
            style={{
              position: 'absolute',
              left: `${fUpW * 100}%`,
              top: AXIS_Y - CAP_H / 2,
              height: CAP_H,
              width: WHISKER_THICK,
              marginLeft: -WHISKER_THICK / 2,
              background: 'var(--mantine-color-text, #111)',
              opacity: 0.85,
            }}
          />
          {/* IQR box (Q1 → Q3). Background + border inherit the card's
              icon/title colour when provided — falls back to teal for
              backward compatibility with cards that don't set a colour. */}
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
          {/* Median line — thick black bar inside the box */}
          <Box
            style={{
              position: 'absolute',
              left: `${fMed * 100}%`,
              top: BOX_TOP,
              height: BOX_H,
              width: 2,
              marginLeft: -1,
              background: 'var(--mantine-color-text, #111)',
            }}
          />
          {/* Mean marker — small filled triangle on the axis. Helps see the
              mean-vs-median gap (skew indicator). Positioned just above the
              axis baseline so it sits next to (not on) the median bar. */}
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
              borderBottom: '6px solid #E74C3C',
            }}
          />
          {/* Outlier dots — each datum outside the fence. Capped at 100 by
              the server; remaining count surfaces in the tooltip. */}
          {s.outliers.map((v, i) => (
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
                border: '0.5px solid var(--mantine-color-text, #111)',
              }}
            />
          ))}
        </Box>
      </Tooltip>
      {/* Compact bottom row — just min / median / max anchors. Mean +
          full quartile detail live in the tooltip; this row's job is to
          let the user read the axis ends + the median at a glance even
          when the card is narrow (w=3 ≈ 180px). */}
      <Group justify="space-between" gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
        <Text size="xs" c="dimmed" lh={1} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {formatSecondary(s.min)}
        </Text>
        <Text
          size="xs"
          fw={600}
          lh={1}
          style={{
            fontVariantNumeric: 'tabular-nums',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {formatSecondary(s.median)}
        </Text>
        <Text size="xs" c="dimmed" lh={1} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {formatSecondary(s.max)}
        </Text>
      </Group>
    </Stack>
  );
};

/** One row inside the box-plot tooltip. Label left, marker+value right,
 *  optional hint underneath in dimmed text. */
const TooltipRow: React.FC<{
  label: string;
  value: number;
  marker?: string;
  accent?: 'teal' | 'red' | 'bold';
  hint?: string;
  dim?: boolean;
}> = ({ label, value, marker, accent, hint, dim }) => {
  const valueColor =
    accent === 'red' ? '#E74C3C' : accent === 'teal' ? '#45B8AC' : undefined;
  const valueWeight = accent === 'bold' || accent === 'teal' ? 600 : 500;
  return (
    <Group gap={4} wrap="nowrap" justify="space-between" align="flex-start">
      <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
        <Text size="xs" c={dim ? 'dimmed' : undefined} lh={1.2} fw={dim ? 400 : 500}>
          {label}
        </Text>
        {hint ? (
          <Text size="10" c="dimmed" lh={1.1} style={{ fontSize: 10 }}>
            {hint}
          </Text>
        ) : null}
      </Stack>
      <Group gap={3} wrap="nowrap" align="center">
        {marker ? (
          <Text size="xs" lh={1.2} style={{ color: valueColor }}>
            {marker}
          </Text>
        ) : null}
        <Text
          size="xs"
          lh={1.2}
          fw={valueWeight}
          style={{ color: valueColor, fontVariantNumeric: 'tabular-nums' }}
        >
          {formatSecondary(value)}
        </Text>
      </Group>
    </Group>
  );
};

function formatSecondary(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '—';
    if (!Number.isInteger(v)) return v.toFixed(4).replace(/\.?0+$/, '');
    return String(v);
  }
  return String(v);
}

/**
 * ``top_n`` layout — hybrid Pareto headline + honest proportional bars.
 *
 *   Top 3 cover 83% of 1,326
 *   orf1ab  ▰▰▰▰▰▰▰▰▰         45%
 *   S       ▰▰▰▰▰             25%
 *   N       ▰▰▰               13%
 *
 *  - **Pareto headline** (top line) leads with the *insight*: do the top
 *    rows carry the bulk? Reads directly without parsing the bars.
 *  - **Bars are scaled to TOTAL** (not the leader), so a 45 % bar is 45 % of
 *    the width. Visually honest — no implicit "100 % wide leader" lie.
 *  - **Three columns** per row (name / bar / percent), aligned on fixed
 *    widths so the bars stack vertically.
 *  - **Per-row tooltip** on hover surfaces the exact count + percent + the
 *    rank metadata that doesn't fit on the strip.
 */
const TopNMetric: React.FC<{
  payload: BreakdownPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  if (!payload.top.length) return null;
  const barFill = hexWithAlpha(color, 0.75);
  const barTrack = hexWithAlpha(color, 0.12);
  const topShare = Math.round(payload.top_share * 100);
  const tailRows = Math.max(0, payload.unique_values - payload.top.length);
  // Pareto headline ("Top 3 = 83%") now lives in the card's aggregation
  // description line (composed by CardRenderer) so we don't duplicate it
  // here. The strip is just the bars + their per-row labels, with a small
  // ``mt`` so they don't crowd the description line. ``pt={2}`` ensures the
  // first bar's text doesn't get clipped by the Stack's ``overflow: hidden``
  // when line-height pushes the top pixel above the row baseline.
  return (
    <Stack
      gap={3}
      mt={10}
      pt={2}
      px="xs"
      pb={4}
      style={{ overflow: 'hidden', minWidth: 0, position: 'relative', zIndex: 2 }}
    >
      {payload.top.map((row, idx) => {
        const pct = row.percent * 100;
        const widthPct = Math.max(1.5, pct);
        const tooltipBody = (
          <Stack gap={2} miw={180}>
            <Text size="xs" fw={600} lh={1.2}>
              {row.name}
            </Text>
            <Group gap={4} wrap="nowrap" justify="space-between">
              <Text size="xs" c="dimmed" lh={1.2}>
                rank
              </Text>
              <Text size="xs" lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
                #{idx + 1} of {payload.unique_values.toLocaleString()}
              </Text>
            </Group>
            <Group gap={4} wrap="nowrap" justify="space-between">
              <Text size="xs" c="dimmed" lh={1.2}>
                count
              </Text>
              <Text size="xs" lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
                {row.count.toLocaleString()}
              </Text>
            </Group>
            <Group gap={4} wrap="nowrap" justify="space-between">
              <Text size="xs" c="dimmed" lh={1.2}>
                share
              </Text>
              <Text size="xs" fw={500} lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
                {pct.toFixed(1)}%
              </Text>
            </Group>
            {idx === payload.top.length - 1 && tailRows > 0 ? (
              <>
                <Box style={{ height: 1, background: 'rgba(255,255,255,0.18)', margin: '2px 0' }} />
                <Group gap={4} wrap="nowrap" justify="space-between">
                  <Text size="xs" c="dimmed" lh={1.2}>
                    column
                  </Text>
                  <Text size="xs" lh={1.2}>
                    {payload.column}
                  </Text>
                </Group>
                <Group gap={4} wrap="nowrap" justify="space-between">
                  <Text size="xs" c="dimmed" lh={1.2}>
                    tail
                  </Text>
                  <Text size="xs" lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {tailRows.toLocaleString()} more · {100 - topShare}%
                  </Text>
                </Group>
              </>
            ) : null}
          </Stack>
        );
        return (
          <Tooltip
            key={row.name}
            label={tooltipBody}
            multiline
            w={200}
            withArrow
            position="left"
            openDelay={120}
            styles={{ tooltip: { padding: '6px 8px' } }}
          >
            <Group gap={6} wrap="nowrap" align="center" style={{ cursor: 'help' }}>
              {/* Fixed-width name column so all bars start at the same x. */}
              <Text
                size="10"
                fw={500}
                style={{
                  fontSize: 10,
                  lineHeight: 1.2,
                  width: 56,
                  flex: '0 0 56px',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {row.name}
              </Text>
              {/* Bar — width = share of TOTAL (honest proportional). */}
              <Box
                style={{
                  flex: '1 1 auto',
                  minWidth: 0,
                  position: 'relative',
                  height: 9,
                  background: barTrack,
                  borderRadius: 2,
                  overflow: 'hidden',
                }}
              >
                <Box
                  style={{
                    position: 'absolute',
                    inset: 0,
                    width: `${widthPct}%`,
                    background: barFill,
                    borderRadius: 2,
                  }}
                />
              </Box>
              {/* Count + percent column — fixed width, right-aligned,
                  tabular nums so columns align across rows. ``count (%)``
                  is more information-dense than ``%`` alone and matches
                  what the user had before — the Pareto summary up in the
                  aggregation_description line carries the cumulative share
                  so this column can focus on per-row detail. */}
              <Text
                size="10"
                c="dimmed"
                style={{
                  fontSize: 10,
                  lineHeight: 1.2,
                  flex: '0 0 auto',
                  textAlign: 'right',
                  fontVariantNumeric: 'tabular-nums',
                  whiteSpace: 'nowrap',
                }}
              >
                {row.count.toLocaleString()} ({Math.round(pct)}%)
              </Text>
            </Group>
          </Tooltip>
        );
      })}
    </Stack>
  );
};

/**
 * ``coverage`` layout — single horizontal fill bar showing ``value / max``.
 * Colour gradient nudges from amber (low) to teal (high) so a glance tells
 * you how close the metric is to its theoretical ceiling.
 *
 *   ▰▰▰▰▰▰▰▰▰▰ 100% / 44
 *
 * The numerator comes from the card's hero value (passed via ``coverageValue``
 * prop). The denominator is the YAML-declared ``coverage_max``.
 */
const CoverageMetric: React.FC<{
  value: number;
  max: number;
  color?: string | null;
}> = ({ value, max, color }) => {
  const pct = Math.max(0, Math.min(1, value / max));
  // High-coverage cards (≥ 90%) use the requested colour / teal; lower coverage
  // shifts to amber to flag "incomplete" status visually.
  const accent = pct >= 0.9 ? hexWithAlpha(color, 0.8) : 'rgba(250,176,5,0.75)';
  const track = 'rgba(160,160,160,0.18)';
  const remaining = Math.max(0, max - value);
  const status = pct >= 0.9 ? 'complete' : pct >= 0.5 ? 'partial' : 'sparse';
  const tooltipBody = (
    <Stack gap={2} miw={220}>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>covered</Text>
        <Text size="xs" fw={600} lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {value.toLocaleString()}
        </Text>
      </Group>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>maximum</Text>
        <Text size="xs" fw={500} lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {max.toLocaleString()}
        </Text>
      </Group>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>remaining</Text>
        <Text size="xs" lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {remaining.toLocaleString()}
        </Text>
      </Group>
      <Box style={{ height: 1, background: 'rgba(255,255,255,0.18)', margin: '4px 0' }} />
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>coverage</Text>
        <Text size="xs" fw={700} lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {(pct * 100).toFixed(pct === 1 ? 0 : 1)}%
        </Text>
      </Group>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>status</Text>
        <Text size="xs" fw={500} lh={1.2}>
          {status}
        </Text>
      </Group>
    </Stack>
  );
  return (
    <Tooltip
      label={tooltipBody}
      multiline
      w={240}
      withArrow
      position="bottom"
      openDelay={150}
      styles={{ tooltip: { padding: '8px 10px' } }}
    >
    <Stack
      gap={2}
      mt={0}
      px="xs"
      pb="xs"
      style={{ overflow: 'hidden', minWidth: 0, position: 'relative', zIndex: 2, cursor: 'help' }}
    >
      <Box
        style={{
          position: 'relative',
          height: 18,
          background: track,
          borderRadius: 4,
          overflow: 'hidden',
        }}
      >
        <Box
          style={{
            position: 'absolute',
            inset: 0,
            width: `${pct * 100}%`,
            background: accent,
            transition: 'width 200ms ease-out',
          }}
        />
        <Text
          size="10"
          fw={600}
          style={{
            position: 'relative',
            fontSize: 11,
            lineHeight: '18px',
            paddingLeft: 8,
            color: 'var(--mantine-color-text)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {Math.round(pct * 100)}% / {max.toLocaleString()}
        </Text>
      </Box>
    </Stack>
    </Tooltip>
  );
};

/**
 * ``concentration`` layout — single line summarising how concentrated the
 * cardinality is. Reads the same ``__breakdown__`` payload as ``top_n`` but
 * displays only the headline "Top N cover X%" plus the names.
 *
 *   Top 3 cover 18%: P681H, D614G, P323L
 *
 * Useful when you want the *answer* (is there one dominant value or a long
 * tail?) without the per-row bar chart.
 */
const ConcentrationMetric: React.FC<{
  payload: BreakdownPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  if (!payload.top.length) return null;
  const shareColor = hexWithAlpha(color, 0.85);
  const sharePct = Math.round(payload.top_share * 100);
  const names = payload.top.map((r) => r.name).join(', ');
  const tailShare = Math.max(0, 100 - sharePct);
  const tailRows = Math.max(0, payload.unique_values - payload.top.length);
  // Heuristic: "dominant" when a handful of values own most of the rows.
  const shape =
    sharePct >= 75 ? 'highly concentrated' : sharePct >= 40 ? 'concentrated' : 'long-tailed';
  const tooltipBody = (
    <Stack gap={2} miw={240}>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>column</Text>
        <Text size="xs" fw={500} lh={1.2}>{payload.column}</Text>
      </Group>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>rows</Text>
        <Text size="xs" fw={500} lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {payload.total.toLocaleString()}
        </Text>
      </Group>
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>unique values</Text>
        <Text size="xs" fw={500} lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {payload.unique_values.toLocaleString()}
        </Text>
      </Group>
      <Box style={{ height: 1, background: 'rgba(255,255,255,0.18)', margin: '4px 0' }} />
      {payload.top.map((row) => (
        <Group key={row.name} gap={4} wrap="nowrap" justify="space-between">
          <Text size="xs" lh={1.2} style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {row.name}
          </Text>
          <Text size="xs" fw={500} lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
            {row.count.toLocaleString()} ({Math.round(row.percent * 100)}%)
          </Text>
        </Group>
      ))}
      <Box style={{ height: 1, background: 'rgba(255,255,255,0.18)', margin: '4px 0' }} />
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>top {payload.top.length} share</Text>
        <Text size="xs" fw={700} lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {sharePct}%
        </Text>
      </Group>
      {tailRows > 0 ? (
        <Group gap={4} wrap="nowrap" justify="space-between">
          <Text size="xs" c="dimmed" lh={1.2}>
            tail ({tailRows.toLocaleString()} more)
          </Text>
          <Text size="xs" lh={1.2} style={{ fontVariantNumeric: 'tabular-nums' }}>
            {tailShare}%
          </Text>
        </Group>
      ) : null}
      <Group gap={4} wrap="nowrap" justify="space-between">
        <Text size="xs" c="dimmed" lh={1.2}>shape</Text>
        <Text size="xs" fw={500} lh={1.2}>{shape}</Text>
      </Group>
    </Stack>
  );
  return (
    <Tooltip
      label={tooltipBody}
      multiline
      w={280}
      withArrow
      position="bottom"
      openDelay={150}
      styles={{ tooltip: { padding: '8px 10px' } }}
    >
    <Stack
      gap={2}
      mt={0}
      px="xs"
      pb="xs"
      style={{ overflow: 'hidden', minWidth: 0, position: 'relative', zIndex: 2, cursor: 'help' }}
    >
      <Text size="11" lh={1.25} style={{ fontSize: 11 }}>
        <Text component="span" fw={700} style={{ color: shareColor }}>
          Top {payload.top.length} cover {sharePct}%
        </Text>
        <Text component="span" c="dimmed" style={{ fontSize: 10, marginLeft: 4 }}>
          of {payload.total.toLocaleString()} rows
        </Text>
      </Text>
      <Text
        size="10"
        c="dimmed"
        lh={1.2}
        style={{
          fontSize: 10,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {names}
      </Text>
    </Stack>
    </Tooltip>
  );
};

export default SecondaryMetrics;
