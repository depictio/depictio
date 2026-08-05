import React from 'react';
import { Box, Group, Stack, Text, Tooltip } from '@mantine/core';

/**
 * The shared vocabulary of the card's secondary strips.
 *
 * Fourteen layouts draw into the same 40-odd pixels under a card's hero value.
 * Each one used to bring its own font size (10 / 11 / 12 px, sometimes two in
 * the same strip), its own bar height (8 / 9 / 12 / 14 / 18 px), its own top
 * margin (0 / 4 / 6 / 10) and its own hand-rolled tooltip rows — so a dashboard
 * mixing three card layouts looked like three different products.
 *
 * Everything visual is decided here. A layout should reach for a primitive
 * below, and only draw raw `Box`es for the geometry that is genuinely its own
 * (a box-plot's whiskers, a donut's arcs).
 */
export const METRIC = {
  /** Side padding — matches the card body's own inset. */
  paddingX: 'xs',
  paddingBottom: 'xs',
  /** Gap between the card's aggregation-description line and the strip. */
  marginTop: 6,
  /** Gap between stacked rows inside a strip. */
  rowGap: 3,
  /** Single full-width meter (completeness / threshold / composition / …). */
  meterHeight: 12,
  /** Per-row meter, where several stack vertically (top-N, attrition). */
  rowMeterHeight: 10,
  /** Drawing area for the chart-shaped layouts (sparkline, box-plot). */
  chartHeight: 28,
  radius: 4,
  /** Neutral rail every meter is drawn on. Deliberately an alpha grey rather
   *  than a theme token: it has to read as "empty" against both the light and
   *  the dark card background, and against any accent colour laid over it. */
  track: 'rgba(160,160,160,0.18)',
  /** A muted fill for the "everything else" part of a distribution. */
  remainder: 'rgba(160,160,160,0.35)',
  tooltipWidth: 270,
} as const;

/** Verdict colours. The one place a hard-coded hue is right: a pass/fail
 *  judgement is not a brand accent, and tinting "fail" with the card's colour
 *  would make a red-themed card look like everything failed. */
export const VERDICT = {
  pass: '#40c057',
  warn: '#fab005',
  fail: '#fa5252',
} as const;

/** Caption text — the line under a meter, a legend entry, an axis anchor.
 *
 *  `xs` (12px) rather than the 10-11px the strips used to hard-code: the strips
 *  are the only place in the product that went below the theme's smallest token,
 *  and they are also the place users read numbers off.
 */
export const MetricCaption: React.FC<{
  children: React.ReactNode;
  /** Emphasised captions carry the strip's headline figure. */
  strong?: boolean;
  dimmed?: boolean;
  /** Right-aligned trailing caption in a two-part row. */
  ta?: 'left' | 'right';
}> = ({ children, strong, dimmed = true, ta }) => (
  <Text
    size="xs"
    lh={1.2}
    fw={strong ? 600 : 400}
    c={dimmed && !strong ? 'dimmed' : undefined}
    ta={ta}
    truncate
    style={{ fontVariantNumeric: 'tabular-nums', minWidth: 0 }}
  >
    {children}
  </Text>
);

export interface MetricStripProps {
  children: React.ReactNode;
  /** Tooltip body. Every strip has one — it is where the numbers the drawing
   *  cannot fit are read — so it is part of the frame rather than each
   *  layout's own `Tooltip` with its own width and delay. */
  tooltip?: React.ReactNode;
  /** Vertical gap between the strip's own rows. */
  gap?: number;
  /** Distance from the card text above. */
  mt?: number;
  ariaLabel?: string;
}

/**
 * The box every strip lives in: consistent inset, clipped horizontally so a
 * wide label or a stray outlier dot cannot escape the card, and lifted above
 * the card's icon watermark.
 */
export const MetricStrip: React.FC<MetricStripProps> = ({
  children,
  tooltip,
  gap = METRIC.rowGap,
  mt = METRIC.marginTop,
  ariaLabel,
}) => {
  const body = (
    <Stack
      gap={gap}
      mt={mt}
      px={METRIC.paddingX}
      pb={METRIC.paddingBottom}
      aria-label={ariaLabel}
      style={{
        overflow: 'hidden',
        minWidth: 0,
        position: 'relative',
        // Above the card's 40px icon watermark, which is absolutely positioned
        // and would otherwise sit on top of the bars.
        zIndex: 2,
        cursor: tooltip ? 'help' : undefined,
      }}
    >
      {children}
    </Stack>
  );
  if (!tooltip) return body;
  return (
    <Tooltip
      label={tooltip}
      multiline
      w={METRIC.tooltipWidth}
      withArrow
      position="bottom"
      openDelay={150}
      styles={{ tooltip: { padding: '8px 10px' } }}
    >
      {body}
    </Tooltip>
  );
};

export interface MeterSegment {
  key: string;
  /** 0–1 share of the meter's full width. */
  share: number;
  color: string;
}

/**
 * Horizontal meter: a neutral rail with one or more coloured segments laid
 * left to right. Covers the single-fill layouts (completeness, coverage,
 * gauge's linear fallback) and the stacked ones (composition, threshold)
 * alike — the difference is only how many segments are passed.
 */
export const Meter: React.FC<{
  segments: MeterSegment[];
  height?: number;
  /** Content drawn over the rail — the coverage strip prints its percentage
   *  inside the bar rather than under it. */
  children?: React.ReactNode;
}> = ({ segments, height = METRIC.meterHeight, children }) => (
  <Group
    gap={0}
    wrap="nowrap"
    style={{
      position: 'relative',
      height,
      borderRadius: METRIC.radius,
      overflow: 'hidden',
      background: METRIC.track,
    }}
  >
    {segments.map((s) =>
      s.share > 0 ? (
        <Box
          key={s.key}
          style={{
            width: `${Math.max(0, Math.min(100, s.share * 100))}%`,
            height: '100%',
            background: s.color,
            transition: 'width 200ms ease-out',
          }}
        />
      ) : null,
    )}
    {children}
  </Group>
);

/** Label / value row inside a tooltip. Replaces the ~40 hand-rolled copies of
 *  the same `Group justify="space-between"` block. */
export const TooltipStat: React.FC<{
  label: React.ReactNode;
  value: React.ReactNode;
  /** Headline row of the tooltip (a share, a verdict). */
  strong?: boolean;
  /** Colour swatch drawn before the label, matching a chart segment. */
  swatch?: string;
}> = ({ label, value, strong, swatch }) => (
  <Group gap={4} wrap="nowrap" justify="space-between" align="center">
    <Group gap={5} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
      {swatch ? (
        <Box
          style={{ width: 8, height: 8, borderRadius: 2, background: swatch, flexShrink: 0 }}
        />
      ) : null}
      <Text size="xs" c="dimmed" lh={1.2} truncate style={{ minWidth: 0 }}>
        {label}
      </Text>
    </Group>
    <Text
      size="xs"
      lh={1.2}
      fw={strong ? 700 : 500}
      style={{ fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}
    >
      {value}
    </Text>
  </Group>
);

/** Note line at the bottom of a tooltip — what the numbers do *not* say. */
export const TooltipNote: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text size="xs" c="dimmed" lh={1.2}>
    {children}
  </Text>
);

/** Separator inside a tooltip. `currentColor` rather than a fixed white:
 *  Mantine flips the tooltip's own background between light and dark themes,
 *  so a hard-coded white rule vanished in one of them. */
export const TooltipDivider: React.FC = () => (
  <Box
    style={{
      height: 1,
      background: 'currentColor',
      opacity: 0.25,
      margin: '4px 0',
    }}
  />
);
