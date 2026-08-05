import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
import ComponentSkeleton from '../ComponentSkeleton';
import { INTERACTIVE_FRAME, InteractiveTitle, SLIDER_MARK_LABEL_STYLE } from './frame';
import './TimelineRenderer.css';

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

interface DatetimeRange {
  min: Date | null;
  max: Date | null;
  /** All distinct timestamps present in the column (ms since epoch, ascending).
   *  Populated for ISO/object columns (whose specs carry no min/max), so the
   *  slider can mark every acquisition. Empty when only precomputed min/max is
   *  available (a large numeric datetime column not worth enumerating). */
  stamps: number[];
}

const dateRangeCache = new Map<string, Promise<DatetimeRange>>();

async function fetchDatetimeRange(
  dcId: string,
  columnName: string,
  filterExpr?: string,
): Promise<DatetimeRange> {
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
  if (min && max) return { min, max, stamps: [] };

  // Fallback: ISO-string columns are stored as `type: object` so the
  // precomputed specs only carry count/mode/nunique. Fetch unique values
  // and parse them as dates to derive min/max — and keep the full sorted set
  // of distinct timestamps so the slider can mark every acquisition. Caps at
  // 1000 (the unique_values endpoint default) which is fine for timeline scopes.
  try {
    const values = await fetchUniqueValues(dcId, columnName, filterExpr);
    const stamps = Array.from(
      new Set(
        values
          .map((v) => new Date(v).getTime())
          .filter((ms) => Number.isFinite(ms)),
      ),
    ).sort((a, b) => a - b);
    return {
      min: stamps.length ? new Date(stamps[0]) : min,
      max: stamps.length ? new Date(stamps[stamps.length - 1]) : max,
      stamps,
    };
  } catch (e) {
    console.warn('[TimelineRenderer] unique-values fallback failed:', e);
    return { min, max, stamps: [] };
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
// Label for a per-timestamp mark. Picks precision from the total span so
// acquisitions that are seconds apart still get distinct labels (formatAt's
// coarsest unit is the minute, which would collide for a sub-minute run).
function formatStampLabel(ms: number, spanMs: number): string {
  const d = new Date(ms);
  const p = (n: number): string => String(n).padStart(2, '0');
  if (spanMs < 60 * 60 * 1000) return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  if (spanMs < 2 * 24 * 60 * 60 * 1000) return `${p(d.getHours())}:${p(d.getMinutes())}`;
  return `${MONTH_SHORT[d.getMonth()]} ${d.getDate()}`;
}

// Cap on how many distinct timestamps we render as individual slider marks —
// beyond this the ticks blur together and the DOM bloats, so fall back to the
// regularly-spaced scale ticks instead.
const MAX_STAMP_MARKS = 80;
// Beyond this many marks, drop the text labels (keep the ticks) to avoid
// overlapping, unreadable labels.
const MAX_STAMP_LABELS = 12;

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
  /** Realtime refresh counter — bumping it re-fetches the datetime bounds so
   *  the slider range extends as new rows stream in. */
  refreshTick?: number;
}> = ({ metadata, filters, onChange, compact, refreshTick }) => {
  const [bounds, setBounds] = useState<DatetimeRange | null>(null);
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
    // refreshTick participates in the cache key so a realtime update computes
    // fresh bounds (bounds only grow), while repeated renders at the same tick
    // still hit the cached promise.
    const prefix = `${metadata.dc_id}|${metadata.column_name}|${metadata.filter_expr || ''}|`;
    const cacheKey = `${prefix}${refreshTick ?? 0}`;
    let p = dateRangeCache.get(cacheKey);
    if (!p) {
      // Drop superseded ticks for this dc/column/filter so the cache doesn't
      // grow one stale entry per realtime update over a long session.
      for (const key of dateRangeCache.keys()) {
        if (key.startsWith(prefix) && key !== cacheKey) dateRangeCache.delete(key);
      }
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
  }, [metadata.dc_id, metadata.column_name, metadata.filter_expr, refreshTick]);

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

  // Geometry of Mantine's slider track relative to our wrapper, so the custom
  // clickable timestamp dots overlay exactly on the track (Mantine insets the
  // track by the thumb radius; we mirror that by measuring rather than guessing).
  const sliderRef = useRef<HTMLDivElement>(null);
  const [trackBox, setTrackBox] = useState<{ left: number; width: number; top: number } | null>(
    null,
  );
  useLayoutEffect(() => {
    const root = sliderRef.current;
    if (!root) return;
    const measure = () => {
      const track = root.querySelector('.mantine-Slider-track') as HTMLElement | null;
      if (!track) return;
      const rb = root.getBoundingClientRect();
      const tb = track.getBoundingClientRect();
      setTrackBox({ left: tb.left - rb.left, width: tb.width, top: tb.top - rb.top + tb.height / 2 });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    return () => ro.disconnect();
  }, [bounds, loading, compact]);

  if (error) {
    return (
      <Text size="xs" c="red">
        Timeline: {error}
      </Text>
    );
  }
  if (loading) {
    return <ComponentSkeleton variant="control" />;
  }
  // Only genuinely-missing bounds (non-finite) are "unavailable". A single
  // distinct timestamp (min === max) is a normal early-stream state for a
  // real-time collection — one acquisition so far — so we still render a
  // usable scrubber by padding the collapsed range into a small window
  // centred on that timestamp, rather than dropping to an error message.
  if (!Number.isFinite(minMs) || !Number.isFinite(maxMs)) {
    return (
      <Text size="xs" c="dimmed">
        Timeline unavailable for column "{metadata.column_name}".
      </Text>
    );
  }

  const SINGLE_STAMP_PAD_MS = 60_000; // ±1 min window for a lone timestamp
  const collapsed = (maxMs as number) <= (minMs as number);
  const lo = collapsed ? (minMs as number) - SINGLE_STAMP_PAD_MS : (minMs as number);
  const hi = collapsed ? (maxMs as number) + SINGLE_STAMP_PAD_MS : (maxMs as number);
  const value: [number, number] = selected ?? [lo, hi];
  const ctx = buildFormatContext(lo, hi);

  // Default view: mark every distinct timestamp the column actually contains
  // (one per acquisition), so the whole set of available acquisition times is
  // visible on the slider — not just evenly-spaced scale ticks. Falls back to
  // scale ticks when the distinct set is unknown (numeric column, min/max only)
  // or too dense to render one mark each.
  const stampMarks = ((): { value: number; label: string }[] | null => {
    const st = bounds?.stamps ?? [];
    if (st.length < 2 || st.length > MAX_STAMP_MARKS) return null;
    const span = hi - lo;
    const labelAll = st.length <= MAX_STAMP_LABELS;
    return st.map((v) => ({ value: v, label: labelAll ? formatStampLabel(v, span) : '' }));
  })();

  // YAML `show_marks` wins; otherwise show marks by default when we have the
  // per-timestamp set (even in compact mode — that's the point of this view),
  // else keep the old compact-hides-marks behaviour.
  const marksVisible =
    typeof metadata.show_marks === 'boolean'
      ? metadata.show_marks
      : stampMarks
        ? true
        : !compact;
  const marks = marksVisible ? (stampMarks ?? buildMarks(lo, hi, scale, ctx)) : undefined;

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

  // Click a timestamp dot → snap the nearer window handle exactly to it (clamped
  // so the handles can't cross). This is the reliable replacement for Mantine's
  // `restrictToMarks`, which mis-snapped on irregularly-spaced timestamps.
  const snapToStamp = (t: number) => {
    const [a, b] = value;
    if (Math.abs(t - a) <= Math.abs(t - b)) emit([Math.min(t, b), b]);
    else emit([a, Math.max(t, a)]);
  };

  // Round an arbitrary slider value to the nearest actual acquisition timestamp.
  // Dragging or clicking the bare track would otherwise land a handle between
  // acquisitions (e.g. 20:50:38 — a time no data exists at); snapping keeps the
  // window bounds on real timestamps only.
  const snapToNearestStamp = (v: number): number => {
    const st = bounds?.stamps;
    if (!st || !st.length) return v;
    return st.reduce((best, s) => (Math.abs(s - v) < Math.abs(best - v) ? s : best), st[0]);
  };
  const handleSliderChange = (v: [number, number]) => {
    emit(stampMarks ? [snapToNearestStamp(v[0]), snapToNearestStamp(v[1])] : v);
  };

  // When the slider is snapped to per-acquisition marks, label thumbs/readout
  // with the exact timestamp (span-aware) rather than the coarse scale format,
  // so the value shown matches the mark the thumb sits on.
  const fmt = (v: number): string =>
    stampMarks ? formatStampLabel(v, hi - lo) : formatAt(scale, v, ctx);

  return (
    <Stack gap={INTERACTIVE_FRAME.gap}>
      {/* Compact header: title left, selected-range readout right. Keeps the
       * footer to two rows (header + slider/timescale row below). Shares the
       * Filters panel's title row so the top panel and the sidebar read as one
       * control surface. */}
      <InteractiveTitle
        metadata={metadata}
        right={
          <Text size="xs" c="dimmed" truncate style={{ flexShrink: 0 }}>
            {fmt(value[0])} → {fmt(value[1])}
          </Text>
        }
      />
      {/* Main row: range slider (flex) + timescale picker share one line so
       * the footer stays compact. */}
      <Group gap="sm" wrap="nowrap" align="center">
      <Box
        ref={sliderRef}
        pos="relative"
        pt={4}
        pb={marksVisible ? 28 : 4}
        px={8}
        className="depictio-timeline-slider"
        style={{ flex: 1, minWidth: 0 }}
      >
        <RangeSlider
          size="sm"
          thumbSize={compact ? 12 : 14}
          min={lo}
          max={hi}
          step={sliderStep}
          minRange={stampMarks ? 0 : sliderStep}
          // With per-acquisition dots we render our own clickable marks+labels
          // overlay below; hand Mantine no marks so they don't double up.
          marks={stampMarks ? undefined : marks}
          styles={{ markLabel: SLIDER_MARK_LABEL_STYLE }}
          value={value}
          onChange={(v) => handleSliderChange(v as [number, number])}
          // Show the snapped timestamp in the drag tooltip so it never displays a
          // between-acquisitions time the window can't actually land on.
          label={(v) => fmt(stampMarks ? snapToNearestStamp(v) : v)}
        />
        {stampMarks && marksVisible && trackBox && (
          <div
            className="depictio-timeline-dots"
            style={{ left: trackBox.left, width: trackBox.width, top: trackBox.top }}
          >
            {(bounds?.stamps ?? []).map((t) => {
              const pct = ((t - lo) / (hi - lo)) * 100;
              const inRange = t >= value[0] && t <= value[1];
              const lbl = formatStampLabel(t, hi - lo);
              return (
                <button
                  key={t}
                  type="button"
                  className={`depictio-timeline-dot${inRange ? ' is-in-range' : ''}`}
                  style={{ left: `${pct}%` }}
                  title={lbl}
                  aria-label={`Set acquisition window bound to ${lbl}`}
                  onClick={() => snapToStamp(t)}
                >
                  {stampMarks.length <= MAX_STAMP_LABELS && (
                    <span className="depictio-timeline-dot-label">{lbl}</span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </Box>
        <SegmentedControl
          size="xs"
          data={TIMESCALES.map((s) => ({ value: s, label: TIMESCALE_LABELS[s] }))}
          value={scale}
          onChange={(v) => setScale(v as Timescale)}
          style={{ flexShrink: 0 }}
        />
      </Group>
    </Stack>
  );
};

export default TimelineRenderer;
