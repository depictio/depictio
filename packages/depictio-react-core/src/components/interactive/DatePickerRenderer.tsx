import React, { useEffect, useMemo, useState } from 'react';
import { Text } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import ComponentSkeleton from '../ComponentSkeleton';

import {
  fetchSpecs,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { INTERACTIVE_FRAME, InteractiveFrame, InteractiveTitle } from './frame';

/**
 * DatePicker (range) interactive filter — selects a [start, end] date range.
 *
 * Mirrors `_build_date_range_picker_component` in
 * `depictio/dash/modules/interactive_component/utils.py`. The Dash version uses
 * DMC `DatePickerInput type="range"` and reads min/max date from precomputed
 * column specs. We follow the same pattern: bounds-fetched-once-then-display
 * (analogous to RangeSliderRenderer).
 *
 * The Dash `interactive_component_type` string is `"DateRangePicker"`. The MVP
 * dispatcher accepts both `"DatePicker"` and `"DateRangePicker"` for safety.
 */

// Module-level cache for date-range fetches. Keyed by `${dcId}|${column}`.
const dateRangeCache = new Map<
  string,
  Promise<{ min: Date | null; max: Date | null }>
>();

async function fetchColumnDateRange(
  dcId: string,
  columnName: string,
): Promise<{ min: Date | null; max: Date | null }> {
  const specs = await fetchSpecs(dcId);

  // Specs may be list-shape `[{name, type, specs: {min, max, ...}}]` or
  // legacy dict-shape `{ columnName: { min, max, ... } }` — handle both.
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

  return {
    min: coerceToDate(entrySpecs.min),
    max: coerceToDate(entrySpecs.max),
  };
}

/** Accept ISO date strings ("YYYY-MM-DD" / full ISO) or epoch numbers. */
function coerceToDate(raw: unknown): Date | null {
  if (raw == null) return null;
  if (raw instanceof Date) {
    return Number.isNaN(raw.getTime()) ? null : raw;
  }
  if (typeof raw === 'number') {
    // Heuristic: epoch seconds vs milliseconds. Anything < 10^11 we treat as
    // seconds (covers everything up to year ~5138 in seconds).
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

function toIsoDateString(d: Date | null): string | null {
  if (!d) return null;
  // Use YYYY-MM-DD (date portion only) to match the Dash store format.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

const DatePickerRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Compact rendering — drops the frame, relies on the parent group's card. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  const [bounds, setBounds] = useState<{ min: Date | null; max: Date | null } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Mantine's DatePickerInput is fully controlled. When the user clicks the
  // first date in a range, Mantine fires onChange with [Date, null] —
  // we only emit upward once BOTH ends are picked, so we need to track that
  // intermediate state locally; otherwise the controlled value prop never
  // changes and Mantine keeps restarting on every click, so the user can
  // never finish picking a range. The initial value mirrors the full
  // bounds so the picker shows "oldest → most recent" by default.
  const [pickerValue, setPickerValue] = useState<[Date | null, Date | null]>(
    [null, null],
  );

  useEffect(() => {
    if (!metadata.dc_id || !metadata.column_name) {
      setError('Missing dc_id or column_name');
      setLoading(false);
      return;
    }
    const cacheKey = `${metadata.dc_id}|${metadata.column_name}`;
    let p = dateRangeCache.get(cacheKey);
    if (!p) {
      p = fetchColumnDateRange(metadata.dc_id, metadata.column_name);
      dateRangeCache.set(cacheKey, p);
    }
    let cancelled = false;
    p.then((res) => {
      if (cancelled) return;
      // Render the picker even when one or both bounds are missing — the
      // user can still pick dates, we just skip the min/max constraints.
      // This used to error out ("No date bounds available for column …")
      // for any DC ingested before precompute_columns_specs learned to
      // honor normalized dtype keys for datetime columns.
      setBounds({ min: res.min, max: res.max });
    })
      .catch((err) => {
        if (cancelled) return;
        console.warn('[DatePickerRenderer] fetchColumnDateRange failed:', err);
        // Drop the rejected promise so a later mount can retry.
        dateRangeCache.delete(cacheKey);
        // A failed spec fetch says nothing about whether this control is
        // usable: a data collection whose deltatable document is missing
        // answers /specs with a 404. Fall back to an unconstrained picker
        // rather than replacing the control with a raw "Failed to fetch
        // specs: 404" — the user can still pick dates and the filter still
        // applies downstream.
        setBounds({ min: null, max: null });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, metadata.column_name]);

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selected: [Date | null, Date | null] = useMemo(() => {
    const v = filterEntry?.value;
    if (Array.isArray(v) && v.length === 2) {
      return [coerceToDate(v[0]), coerceToDate(v[1])];
    }
    return [null, null];
  }, [filterEntry]);

  // Sync local picker state with the parent filter when one is set, or
  // default to the full bounds (oldest → most recent) on first load /
  // after an external reset. Picker-internal updates come through
  // Mantine's onChange and don't go through this effect.
  useEffect(() => {
    if (filterEntry?.value) {
      setPickerValue(selected);
    } else if (bounds?.min && bounds?.max) {
      setPickerValue([bounds.min, bounds.max]);
    } else {
      setPickerValue([null, null]);
    }
  }, [filterEntry, selected, bounds]);

  if (loading) {
    return (
      <InteractiveFrame compact={compact}>
        <ComponentSkeleton variant="control" />
      </InteractiveFrame>
    );
  }

  if (error || !bounds) {
    return (
      <InteractiveFrame compact={compact}>
        <Text size="xs" c="red" className="dashboard-error">
          {error || 'Date range unavailable'}
        </Text>
      </InteractiveFrame>
    );
  }

  // pickerValue holds either the parent's filter (synced via the effect
  // above) or the current in-progress picks. Either way, it's the single
  // source of truth that Mantine reads from.
  const value: [Date | null, Date | null] = pickerValue;

  return (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle metadata={metadata} compact={compact} />
      <DatePickerInput
        type="range"
        value={value}
        minDate={bounds.min ?? undefined}
        maxDate={bounds.max ?? undefined}
        clearable={false}
        w="100%"
        size={INTERACTIVE_FRAME.controlSize}
        allowSingleDateInRange
        onChange={(next: [Date | null, Date | null] | null) => {
          const [a, b] = (next ?? [null, null]) as [Date | null, Date | null];
          // Always reflect Mantine's intermediate value locally so the
          // controlled picker actually advances through partial picks.
          // Without this, the controlled `value` prop is constant and
          // Mantine restarts on every click (the user can only ever pick
          // a "start" date and never the "end").
          setPickerValue([a, b]);
          // Wait until both ends are picked before emitting upward.
          if (!a || !b) return;
          const isoA = toIsoDateString(a);
          const isoB = toIsoDateString(b);
          const isFull =
            !!bounds.min &&
            !!bounds.max &&
            isoA === toIsoDateString(bounds.min) &&
            isoB === toIsoDateString(bounds.max);
          onChange?.({
            index: metadata.index,
            // Mirror the Dash "drop filter when equal to full bounds" pattern
            // by emitting null in that case (filter inactive). Otherwise emit
            // [iso, iso] strings to match the persisted Dash format.
            value: isFull ? null : [isoA, isoB],
            column_name: metadata.column_name,
            interactive_component_type: 'DateRangePicker',
            filter_expr: metadata.filter_expr,
          });
        }}
        styles={{
          input: metadata.icon_color ? { borderColor: metadata.icon_color } : undefined,
        }}
      />
    </InteractiveFrame>
  );
};

export default DatePickerRenderer;
