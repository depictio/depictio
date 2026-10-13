import React from 'react';
import { Box, ColorSwatch, Group, Stack, Text, Tooltip } from '@mantine/core';

import { rankTint } from './metrics/format';
import { METRIC, Meter, TooltipDivider, TooltipStat, VERDICT } from './metrics/tokens';

/** Server payload for "Compare groups in cards" — one entry per selection
 *  group, in definition order (see api/v1/services/card_groups.py). When the
 *  card's secondary layout has a compact per-group form, `layout` names it and
 *  each entry carries the same sub-payload shape the layout itself uses. */
export interface GroupComparePayload {
  aggregation: string;
  /** Present when the entries carry per-group layout payloads (or when the
   *  layout is client-computable, e.g. coverage/gauge). */
  layout?: string;
  /** Shared value domain for scale-sensitive layouts (box_plot, histogram):
   *  every group's mini-rendering is drawn against it, not self-normalised. */
  domain?: { min: number; max: number } | null;
  groups: { name: string; color: string; value: unknown; count: number; payload?: unknown }[];
  other: { value: unknown; count: number; payload?: unknown } | null;
  /** Reduced over the whole frame — the "All rows" reference entry, present
   *  unless the user turned "Show overall" off. */
  overall?: { value: unknown; count: number; payload?: unknown } | null;
}

/** Ring/dial columns stay legible only so far; beyond this many groups the
 *  remainder folds into a "+N more" note (values stay reachable via chips). */
const MAX_RING_COLS = 3;

interface Row {
  key: string;
  color: string | null;
  label: string;
  value: unknown;
  count: number;
  dimmed: boolean;
  payload?: unknown;
  /** Group rows count toward the ring-layout visibility cap. */
  isGroup?: boolean;
}

interface BoxStats {
  min: number;
  max: number;
  q1: number;
  q3: number;
  median: number;
  mean: number;
  lower_whisker: number;
  upper_whisker: number;
  outlier_count: number;
}

interface BreakdownTop {
  top?: { name: string; count: number; percent: number }[];
}

interface TrendPoints {
  points?: { label: string; value: number | null }[];
}

/** The breakdown family: layouts whose per-group payload is a ranked `top`
 *  list. They share a tooltip form (one rank-tinted row per category) and hide
 *  the row's hero value, which is often `nunique` and reads as an index when
 *  printed bare — the labelled value lives in the tooltip instead. */
const BREAKDOWN_LAYOUTS = new Set(['donut', 'composition', 'top_n', 'concentration']);

/** Slim Tukey box on a shared domain: whisker span, IQR box in the group's
 *  color, a darker median tick. The full-size BoxPlot renderer self-normalises;
 *  this one deliberately takes the domain from outside so N group rows are
 *  comparable. */
const MiniBox: React.FC<{
  stats: BoxStats;
  color: string;
  domain: { min: number; max: number };
}> = ({ stats, color, domain }) => {
  const span = domain.max - domain.min;
  const frac = (v: number) => (span > 0 ? Math.max(0, Math.min(1, (v - domain.min) / span)) : 0.5);
  const pct = (v: number) => `${frac(v) * 100}%`;
  return (
    <Box style={{ position: 'relative', height: 12, flex: '1 1 auto', minWidth: 40 }}>
      <Box
        style={{
          position: 'absolute',
          top: 5,
          height: 2,
          left: pct(stats.lower_whisker),
          width: `${Math.max(0, (frac(stats.upper_whisker) - frac(stats.lower_whisker)) * 100)}%`,
          background: METRIC.remainder,
        }}
      />
      <Box
        style={{
          position: 'absolute',
          top: 0,
          height: 12,
          left: pct(stats.q1),
          width: `${Math.max(1, (frac(stats.q3) - frac(stats.q1)) * 100)}%`,
          background: color,
          opacity: 0.75,
          borderRadius: 2,
        }}
      />
      <Box
        style={{
          position: 'absolute',
          top: 0,
          height: 12,
          left: `calc(${pct(stats.median)} - 1px)`,
          width: 2,
          background: 'var(--mantine-color-text)',
        }}
      />
    </Box>
  );
};

/** Per-group sparkbars on the shared bin grid; heights against the shared
 *  peak so a tall bar means the same thing on every row. */
const MiniBars: React.FC<{ bins: number[]; peak: number; color: string }> = ({
  bins,
  peak,
  color,
}) => (
  <Group gap={1} wrap="nowrap" align="flex-end" style={{ height: 12, flex: '1 1 auto' }}>
    {bins.map((c, i) => (
      <Box
        key={i}
        style={{
          flex: 1,
          minWidth: 1,
          height: peak > 0 ? `${Math.max(c > 0 ? 12 : 4, (c / peak) * 100)}%` : '4%',
          background: c > 0 ? color : METRIC.track,
          borderRadius: 1,
        }}
      />
    ))}
  </Group>
);

/** 22px ring: the group's top categories as arcs (rank-tinted from the
 *  group's color) plus a neutral remainder. Legend-less — each ring is read
 *  alone, details live in the column tooltip. */
const MiniDonut: React.FC<{ payload: BreakdownTop; color: string }> = ({ payload, color }) => {
  const top = payload.top ?? [];
  if (!top.length) return null;
  // 56px ring — the compact header frees two text rows, and at ring sizes
  // below ~40px the arc proportions stop being comparable across groups.
  const S = 56;
  const R = 21;
  const C = 2 * Math.PI * R;
  let offset = 0;
  const arcs = top.map((t, i) => {
    const len = Math.max(0, Math.min(1, t.percent)) * C;
    const arc = (
      <circle
        key={t.name}
        r={R}
        cx={S / 2}
        cy={S / 2}
        fill="none"
        stroke={rankTint(color, i)}
        strokeWidth={11}
        strokeDasharray={`${len} ${C - len}`}
        strokeDashoffset={-offset}
        transform={`rotate(-90 ${S / 2} ${S / 2})`}
      />
    );
    offset += len;
    return arc;
  });
  return (
    <svg width={S} height={S} viewBox={`0 0 ${S} ${S}`} style={{ flexShrink: 0 }}>
      <circle r={R} cx={S / 2} cy={S / 2} fill="none" stroke={METRIC.track} strokeWidth={11} />
      {arcs}
    </svg>
  );
};

/** 24×15 half-dial: the group's hero value against the card's authored
 *  denominator, in the group's color on the neutral track. */
const MiniGauge: React.FC<{ fraction: number; color: string }> = ({ fraction, color }) => {
  // Sized like the donut ring: the dial reads at a glance instead of hinting.
  const R = 24;
  const C = Math.PI * R;
  const len = Math.max(0, Math.min(1, fraction)) * C;
  const d = `M 6 31 A ${R} ${R} 0 0 1 54 31`;
  return (
    <svg width={60} height={34} viewBox="0 0 60 34" style={{ flexShrink: 0 }}>
      <path d={d} fill="none" stroke={METRIC.track} strokeWidth={9} strokeLinecap="round" />
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={9}
        strokeLinecap="round"
        strokeDasharray={`${len} ${C}`}
      />
    </svg>
  );
};

/** N aligned trend series in one 28px chart — the overlay costs no extra
 *  height, which is why trend gets it instead of per-row copies. Series share
 *  the x grid (server-aligned buckets) and one y range; nulls (buckets where
 *  a group has no rows) break the line rather than inventing zeros. */
const TrendOverlay: React.FC<{
  series: { color: string; points: { value: number | null }[]; dimmed: boolean }[];
}> = ({ series }) => {
  const all = series
    .flatMap((s) => s.points.map((p) => p.value))
    .filter((v): v is number => v !== null);
  if (!all.length) return null;
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const H = 28;
  const y = (v: number) => (hi > lo ? H - 3 - ((v - lo) / (hi - lo)) * (H - 6) : H / 2);
  return (
    <svg
      width="100%"
      height={H}
      viewBox={`0 0 100 ${H}`}
      preserveAspectRatio="none"
      style={{ display: 'block' }}
    >
      {series.map((s, si) => {
        const n = s.points.length;
        // Contiguous non-null runs become separate polylines: a gap in one
        // group's data must read as a gap.
        const runs: string[][] = [];
        let current: string[] = [];
        s.points.forEach((p, i) => {
          if (p.value === null) {
            if (current.length) runs.push(current);
            current = [];
            return;
          }
          const x = n > 1 ? (i / (n - 1)) * 100 : 50;
          current.push(`${x},${y(p.value)}`);
        });
        if (current.length) runs.push(current);
        return runs.map((run, ri) => (
          <polyline
            key={`${si}-${ri}`}
            points={run.join(' ')}
            fill="none"
            stroke={s.color}
            strokeWidth={s.dimmed ? 1.4 : 1.6}
            strokeOpacity={s.dimmed ? 0.7 : 0.9}
            // Dashed: the reference series ("All", "Other") must be visible
            // yet unmistakably not one of the groups.
            strokeDasharray={s.dimmed ? '4 3' : undefined}
            vectorEffect="non-scaling-stroke"
          />
        ));
      })}
    </svg>
  );
};

/** The compact per-group rendering for one row, or null when the layout has
 *  no compact form (the row then shows value + count only). */
function miniRendering(
  layout: string | undefined,
  payload: unknown,
  color: string,
  domain: GroupComparePayload['domain'],
  value: unknown,
  coverageMax: number | null,
  histogramPeak: number,
): React.ReactNode {
  const p = payload as Record<string, unknown> | null | undefined;
  switch (layout) {
    case 'box_plot':
      if (!p || !domain || typeof p.median !== 'number') return null;
      return <MiniBox stats={p as unknown as BoxStats} color={color} domain={domain} />;
    case 'histogram':
      if (!p || !Array.isArray(p.bins)) return null;
      return <MiniBars bins={p.bins as number[]} peak={histogramPeak} color={color} />;
    case 'completeness':
      if (!p || typeof p.fill_rate !== 'number') return null;
      return <Meter height={10} segments={[{ key: 'filled', share: p.fill_rate, color }]} />;
    case 'uniqueness':
      if (!p || typeof p.unique_rate !== 'number') return null;
      return (
        <Meter
          height={10}
          segments={[
            { key: 'distinct', share: p.unique_rate, color },
            { key: 'dup', share: 1 - p.unique_rate, color: METRIC.remainder },
          ]}
        />
      );
    case 'threshold': {
      // Verdict hues, never the group color: a red-themed group would read as
      // "all failed". The group identity lives on the row's swatch.
      if (!p || typeof p.measured !== 'number' || p.measured <= 0) return null;
      const measured = p.measured as number;
      return (
        <Meter
          height={10}
          segments={[
            { key: 'pass', share: ((p.passing as number) ?? 0) / measured, color: VERDICT.pass },
            { key: 'warn', share: ((p.warning as number) ?? 0) / measured, color: VERDICT.warn },
            { key: 'fail', share: ((p.failing as number) ?? 0) / measured, color: VERDICT.fail },
          ]}
        />
      );
    }
    case 'coverage': {
      // Client-computable: this group's hero value against the card's authored
      // cohort-wide denominator — each bar is the group's share of the whole.
      if (typeof value !== 'number' || !coverageMax || coverageMax <= 0) return null;
      return <Meter height={10} segments={[{ key: 'cov', share: value / coverageMax, color }]} />;
    }
    case 'gauge': {
      if (typeof value !== 'number' || !coverageMax || coverageMax <= 0) return null;
      return <MiniGauge fraction={value / coverageMax} color={color} />;
    }
    case 'donut': {
      if (!p || !Array.isArray((p as BreakdownTop).top)) return null;
      return <MiniDonut payload={p as BreakdownTop} color={color} />;
    }
    case 'composition':
    case 'top_n':
    case 'concentration': {
      // The compact per-group form of every non-donut breakdown layout: one
      // composition meter, segments rank-tinted from the group's color.
      const top = (p as BreakdownTop | null | undefined)?.top;
      if (!Array.isArray(top) || top.length === 0) return null;
      return (
        <Meter
          height={10}
          segments={top.map((t, i) => ({
            key: t.name,
            share: t.percent,
            color: rankTint(color, i),
          }))}
        />
      );
    }
    default:
      return null;
  }
}

const pctText = (v: unknown) =>
  typeof v === 'number' ? `${Math.round(v * 100)}%` : '—';

/** Layout-aware tooltip body: the distribution details the mini-rendering
 *  cannot fit — same role (and same primitives) as the aggregate strip's
 *  tooltip, so comparing groups doesn't cost the numbers. */
function rowTooltip(
  layout: string | undefined,
  r: Row,
  aggregation: string,
  formatValue: (v: unknown) => string | number,
  coverageMax: number | null,
): React.ReactNode {
  const header = (
    <TooltipStat
      label={r.label}
      value={`${r.value == null ? '—' : formatValue(r.value)} (${aggregation}) · ${r.count} rows`}
      strong
      swatch={r.color ?? METRIC.remainder}
    />
  );
  const p = r.payload as Record<string, unknown> | null | undefined;
  let body: React.ReactNode = null;
  if (layout === 'box_plot' && p && typeof p.median === 'number') {
    const s = p as unknown as BoxStats;
    body = (
      <>
        <TooltipStat label="min" value={formatValue(s.min)} />
        <TooltipStat label="Q1" value={formatValue(s.q1)} />
        <TooltipStat label="median" value={formatValue(s.median)} />
        <TooltipStat label="mean" value={formatValue(s.mean)} />
        <TooltipStat label="Q3" value={formatValue(s.q3)} />
        <TooltipStat label="max" value={formatValue(s.max)} />
        {s.outlier_count > 0 && <TooltipStat label="outliers" value={s.outlier_count} />}
      </>
    );
  } else if (layout === 'histogram' && p && Array.isArray(p.bins)) {
    body = (
      <>
        <TooltipStat label="median" value={p.median == null ? '—' : formatValue(p.median)} />
        <TooltipStat label="min" value={formatValue(p.min)} />
        <TooltipStat label="max" value={formatValue(p.max)} />
        {typeof p.nulls === 'number' && p.nulls > 0 && (
          <TooltipStat label="missing" value={p.nulls as number} />
        )}
      </>
    );
  } else if (layout === 'threshold' && p && typeof p.measured === 'number') {
    body = (
      <>
        <TooltipStat label="passing" value={`${p.passing ?? 0} (${pctText(p.pass_rate)})`} />
        {typeof p.warning === 'number' && p.warning > 0 && (
          <TooltipStat label="warning" value={p.warning as number} />
        )}
        <TooltipStat label="failing" value={(p.failing as number) ?? 0} />
      </>
    );
  } else if (layout === 'completeness' && p && typeof p.fill_rate === 'number') {
    body = (
      <>
        <TooltipStat label="filled" value={`${p.filled ?? 0} (${pctText(p.fill_rate)})`} />
        <TooltipStat label="missing" value={(p.nulls as number) ?? 0} />
      </>
    );
  } else if (layout === 'uniqueness' && p && typeof p.unique_rate === 'number') {
    body = (
      <>
        <TooltipStat label="distinct" value={`${p.distinct ?? 0} (${pctText(p.unique_rate)})`} />
        <TooltipStat label="duplicated" value={(p.duplicated as number) ?? 0} />
      </>
    );
  } else if (BREAKDOWN_LAYOUTS.has(layout ?? '') && p && Array.isArray((p as BreakdownTop).top)) {
    const top = (p as BreakdownTop).top ?? [];
    body = (
      <>
        {top.map((t, i) => (
          <TooltipStat
            key={t.name}
            label={t.name}
            value={pctText(t.percent)}
            swatch={rankTint(r.color ?? METRIC.remainder, i)}
          />
        ))}
      </>
    );
  } else if (
    (layout === 'coverage' || layout === 'gauge') &&
    typeof r.value === 'number' &&
    coverageMax &&
    coverageMax > 0
  ) {
    body = <TooltipStat label={`of ${coverageMax}`} value={pctText(r.value / coverageMax)} />;
  }
  return (
    <Stack gap={2}>
      {header}
      {body != null && <TooltipDivider />}
      {body}
    </Stack>
  );
}

/**
 * Per-group comparison inside a card. Forms, chosen by the payload:
 *
 * - **Rows** (meter/box/bar layouts): one row per group — swatch, name,
 *   mini-rendering in the group's color, hero value, dimmed count — replacing
 *   the card's aggregate secondary rendering (the ~110px strip budget at the
 *   default card height fits one of the two, not both).
 * - **Columns** (donut/gauge): the rings side by side, capped at 3 groups.
 * - **Overlay** (trend): every group's series in one chart + a legend row.
 * - **Chips** (fallback): the hero value per group, wrapping inline.
 *
 * Groups keep their creation order; the optional "All" reference entry comes
 * first and rows outside every group appear last as a dimmed "Other".
 */
const GroupCompareStrip: React.FC<{
  payload: GroupComparePayload;
  formatValue: (v: unknown) => string | number;
  coverageMax?: number | null;
}> = ({ payload, formatValue, coverageMax = null }) => {
  if (!payload.groups.length) return null;

  // The "All rows" reference entry comes first so every group reads against
  // it; rows outside every group close the list as a dimmed "Other".
  const overallRow: Row | null = payload.overall
    ? {
        key: '__all__',
        color: null,
        label: 'All',
        value: payload.overall.value,
        count: payload.overall.count,
        dimmed: false,
        payload: payload.overall.payload,
      }
    : null;
  const groupRows: Row[] = payload.groups.map((g) => ({
    key: g.name,
    color: g.color,
    label: g.name,
    value: g.value,
    count: g.count,
    dimmed: false,
    payload: g.payload,
    isGroup: true,
  }));
  const otherRow: Row | null = payload.other
    ? {
        key: '__other__',
        color: null,
        label: 'Other',
        value: payload.other.value,
        count: payload.other.count,
        dimmed: true,
        payload: payload.other.payload,
      }
    : null;
  const compose = (groups: Row[]): Row[] => [
    ...(overallRow ? [overallRow] : []),
    ...groups,
    ...(otherRow ? [otherRow] : []),
  ];
  const rows = compose(groupRows);

  // Shared bar scale for histogram rows: the tallest bar across every row is
  // the reference, so bar heights compare across groups.
  const histogramPeak =
    payload.layout === 'histogram'
      ? Math.max(
          1,
          ...rows.flatMap((r) => {
            const bins = (r.payload as { bins?: number[] } | null | undefined)?.bins;
            return Array.isArray(bins) ? bins : [];
          }),
        )
      : 0;

  const isRing = payload.layout === 'donut' || payload.layout === 'gauge';
  // Ring/dial columns are the widest form, so the RICH rendering caps the
  // visible groups (default 3) and folds the remainder into a "+N more" note.
  // The chip fallback stays uncapped. "All" and "Other" don't count.
  const hiddenGroups = isRing ? Math.max(0, payload.groups.length - MAX_RING_COLS) : 0;
  const richRows = hiddenGroups ? compose(groupRows.slice(0, MAX_RING_COLS)) : rows;

  const mini = (r: Row) =>
    miniRendering(
      payload.layout,
      r.payload,
      r.color ?? METRIC.remainder,
      payload.domain,
      r.value,
      coverageMax,
      histogramPeak,
    );
  const hasTrendPoints = (r: Row) => {
    const pts = (r.payload as TrendPoints | null | undefined)?.points;
    return Array.isArray(pts) && pts.length > 0;
  };
  // Trend has no per-row mini (it renders as one overlay chart), so its
  // richness is judged on the series payloads instead.
  const rich =
    typeof payload.layout === 'string' &&
    (payload.layout === 'trend' ? rows.some(hasTrendPoints) : rows.some((r) => mini(r) !== null));
  const tooltipFor = (r: Row) =>
    rowTooltip(payload.layout, r, payload.aggregation, formatValue, coverageMax);
  const valueText = (r: Row) => (r.value == null ? '—' : formatValue(r.value));

  if (rich && payload.layout === 'trend') {
    const withSeries = richRows.filter(hasTrendPoints);
    return (
      <Stack
        gap={3}
        mt={4}
        px={METRIC.paddingX}
        pb={METRIC.paddingBottom}
        style={{ zIndex: 2, flex: '1 1 auto', justifyContent: 'space-evenly' }}
      >
        <TrendOverlay
          series={withSeries.map((r) => ({
            color: r.isGroup ? (r.color as string) : METRIC.remainder,
            points: ((r.payload as TrendPoints).points ?? []).map((pt) => ({ value: pt.value })),
            dimmed: !r.isGroup,
          }))}
        />
        <Group gap="sm" wrap="wrap">
          {richRows.map((r) => (
            <Tooltip key={r.key} label={tooltipFor(r)} withArrow openDelay={300} multiline w={220}>
              <Group gap={4} wrap="nowrap">
                <ColorSwatch color={r.color ?? METRIC.remainder} size={8} />
                <Text size="xs" fw={r.isGroup ? 500 : 400} c={r.dimmed ? 'dimmed' : undefined}>
                  {r.label}
                </Text>
                <Text size="xs" fw={600} c={r.dimmed ? 'dimmed' : undefined}>
                  {valueText(r)}
                </Text>
              </Group>
            </Tooltip>
          ))}
        </Group>
      </Stack>
    );
  }

  if (rich && isRing) {
    return (
      <Group
        gap="md"
        mt={4}
        px={METRIC.paddingX}
        pb={METRIC.paddingBottom}
        wrap="wrap"
        align="center"
        justify="space-evenly"
        style={{ zIndex: 2, position: 'relative', flex: '1 1 auto' }}
      >
        {richRows.map((r) => (
          <Tooltip key={r.key} label={tooltipFor(r)} withArrow openDelay={300} multiline w={220}>
            <Stack gap={2} align="center" style={{ minWidth: 0 }}>
              {mini(r)}
              <Group gap={3} wrap="nowrap" style={{ minWidth: 0 }}>
                <ColorSwatch color={r.color ?? METRIC.remainder} size={7} />
                <Text
                  size="xs"
                  c={r.dimmed ? 'dimmed' : undefined}
                  fw={r.dimmed ? 400 : 500}
                  truncate
                  style={{ maxWidth: 76 }}
                >
                  {r.label}
                </Text>
              </Group>
              {/* Under a donut the hero value is often `nunique` — a bare "1"
                  reads as an index, so the footer shows the row count instead
                  (the labelled value lives in the tooltip). A gauge's value is
                  a numerator and stays. */}
              {payload.layout === 'donut' ? (
                <Text size="xs" c="dimmed" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  ({r.count})
                </Text>
              ) : (
                <Text
                  size="xs"
                  fw={600}
                  c={r.dimmed ? 'dimmed' : undefined}
                  style={{ fontVariantNumeric: 'tabular-nums' }}
                >
                  {valueText(r)}
                </Text>
              )}
            </Stack>
          </Tooltip>
        ))}
        {hiddenGroups > 0 && (
          <Text size="xs" c="dimmed" style={{ alignSelf: 'center' }}>
            +{hiddenGroups} more
          </Text>
        )}
      </Group>
    );
  }

  if (rich) {
    return (
      <Stack
        gap={3}
        mt={4}
        px={METRIC.paddingX}
        pb={METRIC.paddingBottom}
        style={{ zIndex: 2, flex: '1 1 auto', justifyContent: 'space-evenly' }}
      >
        {richRows.map((r) => (
          <Tooltip key={r.key} label={tooltipFor(r)} withArrow openDelay={300} multiline w={220}>
            <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
              <ColorSwatch color={r.color ?? METRIC.remainder} size={10} />
              <Text
                size="xs"
                c={r.dimmed ? 'dimmed' : undefined}
                fw={r.dimmed ? 400 : 500}
                truncate
                style={{ flex: '0 1 72px', minWidth: 36 }}
              >
                {r.label}
              </Text>
              <Box style={{ flex: '1 1 auto', minWidth: 40 }}>{mini(r)}</Box>
              {!BREAKDOWN_LAYOUTS.has(payload.layout ?? '') && (
                <Text
                  size="xs"
                  fw={600}
                  c={r.dimmed ? 'dimmed' : undefined}
                  style={{ flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}
                >
                  {valueText(r)}
                </Text>
              )}
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                ({r.count})
              </Text>
            </Group>
          </Tooltip>
        ))}
      </Stack>
    );
  }

  return (
    <Group gap="sm" mt={4} wrap="wrap">
      {rows.map((r) => (
        <Tooltip
          key={r.key}
          label={`${r.label}: ${payload.aggregation} over ${r.count} row${r.count === 1 ? '' : 's'}`}
          withArrow
          openDelay={400}
        >
          <Group gap={4} wrap="nowrap">
            {r.color && <ColorSwatch color={r.color} size={10} />}
            <Text size="xs" c={r.dimmed ? 'dimmed' : undefined} fw={r.dimmed ? 400 : 500}>
              {r.label}
            </Text>
            <Text size="xs" fw={600} c={r.dimmed ? 'dimmed' : undefined}>
              {valueText(r)}
            </Text>
            <Text size="xs" c="dimmed">
              ({r.count})
            </Text>
          </Group>
        </Tooltip>
      ))}
    </Group>
  );
};

export default GroupCompareStrip;
