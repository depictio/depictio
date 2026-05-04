import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Group,
  RangeSlider,
  SegmentedControl,
  Stack,
  Text,
} from '@mantine/core';

import {
  fetchSpecs,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';

/**
 * Timeline scrubber for datetime columns.
 *
 * Mantine `RangeSlider` over the [min, max] epoch-second range of the
 * configured datetime column. A `SegmentedControl` lets the user switch the
 * timescale at runtime (year/month/day/hour/minute) — this only affects tick
 * spacing and label formatting; the underlying value is always emitted as
 * a `[startIso, endIso]` pair so the server filter pipeline (DateRange-style
 * branch in `add_filter`) can apply it uniformly.
 */
type Timescale = 'year' | 'month' | 'day' | 'hour' | 'minute';
const TIMESCALES: Timescale[] = ['year', 'month', 'day', 'hour', 'minute'];
const TIMESCALE_LABELS: Record<Timescale, string> = {
  year: 'Year',
  month: 'Month',
  day: 'Day',
  hour: 'Hour',
  minute: 'Min',
};
const MONTH_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

interface FormatContext {
  spansYears: boolean;
  spansDays: boolean;
}

const dateRangeCache = new Map<
  string,
  Promise<{ min: Date | null; max: Date | null }>
>();

async function fetchDatetimeRange(
  dcId: string,
  columnName: string,
  filterExpr?: string,
): Promise<{ min: Date | null; max: Date | null }> {
  const specs = await fetchSpecs(dcId);
  let entrySpecs: Record<string, unknown> = {};
  if (Array.isArray(specs)) {
    const entry = (specs as Array<Record<string, unknown>>).find(
      (e) => (e?.name as string) === columnName,
    );
    entrySpecs = (entry?.specs || {}) as Record<string, unknown>;
  } else {
    const dict = specs as Record<string, Record<string, unknown>>;
    entrySpecs = (dict[columnName] || {}) as Record<string, unknown>;
  }
  const min = toDate(entrySpecs.min);
  const max = toDate(entrySpecs.max);
  if (min && max) return { min, max };

  // Fallback: ISO-string columns are stored as `type: object` so the
  // precomputed specs only carry count/mode/nunique. Fetch unique values
  // and parse them as dates to derive min/max client-side. Caps at 1000
  // (the unique_values endpoint default) which is fine for timeline scopes.
  try {
    const values = await fetchUniqueValues(dcId, columnName, filterExpr);
    let lo: number | null = null;
    let hi: number | null = null;
    for (const v of values) {
      const ms = new Date(v).getTime();
      if (!Number.isFinite(ms)) continue;
      if (lo === null || ms < lo) lo = ms;
      if (hi === null || ms > hi) hi = ms;
    }
    return {
      min: lo !== null ? new Date(lo) : min,
      max: hi !== null ? new Date(hi) : max,
    };
  } catch (e) {
    console.warn('[TimelineRenderer] unique-values fallback failed:', e);
    return { min, max };
  }
}

function toDate(raw: unknown): Date | null {
  if (raw == null) return null;
  if (raw instanceof Date) return Number.isNaN(raw.getTime()) ? null : raw;
  if (typeof raw === 'number') {
    const ms = raw < 1e11 ? raw * 1000 : raw;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof raw === 'string') {
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function formatAt(scale: Timescale, ms: number, ctx: FormatContext): string {
  const d = new Date(ms);
  switch (scale) {
    case 'year':
      return String(d.getFullYear());
    case 'month':
      return ctx.spansYears
        ? `${MONTH_SHORT[d.getMonth()]} ${d.getFullYear()}`
        : MONTH_SHORT[d.getMonth()];
    case 'day':
      return ctx.spansYears
        ? `${MONTH_SHORT[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`
        : `${MONTH_SHORT[d.getMonth()]} ${d.getDate()}`;
    case 'hour':
      return ctx.spansDays
        ? `${MONTH_SHORT[d.getMonth()]} ${d.getDate()} ${pad2(d.getHours())}:00`
        : `${pad2(d.getHours())}:00`;
    case 'minute':
      return ctx.spansDays
        ? `${MONTH_SHORT[d.getMonth()]} ${d.getDate()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
        : `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  }
}

function toIsoFull(ms: number): string {
  return new Date(ms).toISOString();
}

function buildFormatContext(min: number, max: number): FormatContext {
  const dLo = new Date(min);
  const dHi = new Date(max);
  const spansYears = dLo.getFullYear() !== dHi.getFullYear();
  const sameDay =
    dLo.getFullYear() === dHi.getFullYear() &&
    dLo.getMonth() === dHi.getMonth() &&
    dLo.getDate() === dHi.getDate();
  return { spansYears, spansDays: !sameDay };
}

/**
 * 4 evenly-spaced labeled marks (start, 1/3, 2/3, end) — keeps labels readable
 * without overlap even at the narrowest panel widths.
 */
function buildMarks(
  min: number,
  max: number,
  scale: Timescale,
  ctx: FormatContext,
): { value: number; label: string }[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [];
  const NMARKS = 3;
  const out: { value: number; label: string }[] = [];
  for (let i = 0; i <= NMARKS; i++) {
    const v = min + ((max - min) * i) / NMARKS;
    out.push({ value: v, label: formatAt(scale, v, ctx) });
  }
  return out;
}

const TimelineRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Compact rendering — tightens spacing and defaults marks to hidden. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  const [bounds, setBounds] = useState<{ min: Date | null; max: Date | null } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const initialScale = (metadata.timescale as Timescale | undefined) || 'day';
  const [scale, setScale] = useState<Timescale>(initialScale);

  useEffect(() => {
    if (!metadata.dc_id || !metadata.column_name) {
      setError('Missing dc_id or column_name');
      setLoading(false);
      return;
    }
    const cacheKey = `${metadata.dc_id}|${metadata.column_name}|${metadata.filter_expr || ''}`;
    let p = dateRangeCache.get(cacheKey);
    if (!p) {
      p = fetchDatetimeRange(
        metadata.dc_id,
        metadata.column_name,
        metadata.filter_expr,
      );
      dateRangeCache.set(cacheKey, p);
    }
    let cancelled = false;
    p.then((res) => {
      if (!cancelled) setBounds(res);
    })
      .catch((err) => {
        if (cancelled) return;
        console.warn('[TimelineRenderer] fetchDatetimeRange failed:', err);
        dateRangeCache.delete(cacheKey);
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, metadata.column_name, metadata.filter_expr]);

  const minMs = bounds?.min?.getTime();
  const maxMs = bounds?.max?.getTime();

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selected = useMemo<[number, number] | null>(() => {
    if (!Array.isArray(filterEntry?.value) || filterEntry.value.length !== 2) return null;
    const [a, b] = filterEntry.value as [string, string];
    const av = new Date(a).getTime();
    const bv = new Date(b).getTime();
    return Number.isFinite(av) && Number.isFinite(bv) ? [av, bv] : null;
  }, [filterEntry]);

  if (error) {
    return (
      <Text size="xs" c="red">
        Timeline: {error}
      </Text>
    );
  }
  if (loading) {
    return (
      <Text size="xs" c="dimmed">
        Loading timeline…
      </Text>
    );
  }
  if (!Number.isFinite(minMs) || !Number.isFinite(maxMs) || (maxMs as number) <= (minMs as number)) {
    return (
      <Text size="xs" c="dimmed">
        Timeline unavailable for column "{metadata.column_name}".
      </Text>
    );
  }

  const lo = minMs as number;
  const hi = maxMs as number;
  const value: [number, number] = selected ?? [lo, hi];
  const ctx = buildFormatContext(lo, hi);
  // YAML wins; otherwise compact mode hides marks for higher density.
  const marksVisible =
    typeof metadata.show_marks === 'boolean' ? metadata.show_marks : !compact;
  const marks = marksVisible ? buildMarks(lo, hi, scale, ctx) : undefined;

  const stepFor = (s: Timescale): number => {
    const SEC = 1000;
    const MIN = 60 * SEC;
    const HOUR = 60 * MIN;
    const DAY = 24 * HOUR;
    switch (s) {
      case 'year':
        return 365 * DAY;
      case 'month':
        return 30 * DAY;
      case 'day':
        return DAY;
      case 'hour':
        return HOUR;
      case 'minute':
        return MIN;
    }
  };

  // Clamp the slider step so it never exceeds the available range — for short
  // datasets at coarse scales (e.g. minute-level data viewed at "year") the
  // raw step would be larger than (hi - lo) and freeze the slider.
  const rawStep = stepFor(scale);
  const sliderStep = Math.max(1, Math.min(rawStep, Math.floor((hi - lo) / 2)));

  const emit = (next: [number, number]) => {
    const [a, b] = next;
    const isFull = a <= lo && b >= hi;
    onChange?.({
      index: metadata.index,
      value: isFull ? null : [toIsoFull(a), toIsoFull(b)],
      column_name: metadata.column_name,
      interactive_component_type: 'Timeline',
      filter_expr: metadata.filter_expr,
    });
  };

  const title = metadata.title || (metadata.column_name ? `Timeline · ${metadata.column_name}` : 'Timeline');

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="nowrap" align="center" justify="space-between">
        <Text size="xs" fw={600} truncate style={{ flex: 1, minWidth: 0 }}>
          {title}
        </Text>
        <SegmentedControl
          size="xs"
          data={TIMESCALES.map((s) => ({ value: s, label: TIMESCALE_LABELS[s] }))}
          value={scale}
          onChange={(v) => setScale(v as Timescale)}
        />
      </Group>
      <Box pt={4} pb={marksVisible ? 28 : 4} px={8}>
        <RangeSlider
          size="sm"
          thumbSize={compact ? 12 : 14}
          min={lo}
          max={hi}
          step={sliderStep}
          minRange={sliderStep}
          marks={marks}
          value={value}
          onChange={(v) => emit(v as [number, number])}
          label={(v) => formatAt(scale, v, ctx)}
        />
      </Box>
      <Text size="xs" c="dimmed" ta="center">
        {formatAt(scale, value[0], ctx)} → {formatAt(scale, value[1], ctx)}
      </Text>
    </Stack>
  );
};

export default TimelineRenderer;
