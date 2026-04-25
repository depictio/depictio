import React, { useEffect, useState } from 'react';
import { Paper, Stack, Group, Text } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { Icon } from '@iconify/react';

import {
  fetchSpecs,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';

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
}> = ({ metadata, filters, onChange }) => {
  const [bounds, setBounds] = useState<{ min: Date; max: Date } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      if (!res.min || !res.max) {
        setError(
          `No date bounds available for column "${metadata.column_name}"`,
        );
        return;
      }
      setBounds({ min: res.min, max: res.max });
    })
      .catch((err) => {
        if (cancelled) return;
        console.warn('[DatePickerRenderer] fetchColumnDateRange failed:', err);
        dateRangeCache.delete(cacheKey);
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, metadata.column_name]);

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selected: [Date | null, Date | null] = (() => {
    const v = filterEntry?.value;
    if (Array.isArray(v) && v.length === 2) {
      return [coerceToDate(v[0]), coerceToDate(v[1])];
    }
    return [null, null];
  })();

  const displayTitle =
    metadata.title ||
    (metadata.column_name ? `Date range on ${metadata.column_name}` : '');
  const iconCol = metadata.icon_color || 'var(--mantine-color-blue-6)';

  if (loading) {
    return (
      <div className="dashboard-loading" style={{ minHeight: 80, fontSize: '0.75rem' }}>
        Loading date range…
      </div>
    );
  }

  if (error || !bounds) {
    return (
      <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
        {error || 'Date range unavailable'}
      </div>
    );
  }

  // Default the picker to the full bounds when no filter is set.
  const value: [Date | null, Date | null] = [
    selected[0] ?? bounds.min,
    selected[1] ?? bounds.max,
  ];

  return (
    <Paper
      p="md"
      radius="md"
      shadow="xs"
      className="dashboard-component-hover"
      style={{
        backgroundColor: 'var(--app-surface-color, #ffffff)',
        height: '100%',
        boxSizing: 'border-box',
      }}
    >
      <Stack gap="md">
        {displayTitle && (
          <Group gap="xs" align="center" wrap="nowrap">
            {metadata.icon_name && (
              <Icon
                icon={metadata.icon_name}
                width={18}
                height={18}
                style={{ color: iconCol, flexShrink: 0 }}
              />
            )}
            <Text fw={600} size="sm" style={{ color: 'var(--app-text-color, #1a1b1e)' }}>
              {displayTitle}
            </Text>
          </Group>
        )}
        <DatePickerInput
          type="range"
          value={value}
          minDate={bounds.min}
          maxDate={bounds.max}
          clearable={false}
          w="100%"
          size="sm"
          allowSingleDateInRange
          onChange={(next: [Date | null, Date | null] | null) => {
            const [a, b] = (next ?? [null, null]) as [Date | null, Date | null];
            // Wait until both ends are picked before emitting (Mantine fires
            // intermediate values as the user clicks first the start, then end).
            if (!a || !b) return;
            const isoA = toIsoDateString(a);
            const isoB = toIsoDateString(b);
            const isFull =
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
            });
          }}
          styles={{
            input: metadata.icon_color
              ? { borderColor: metadata.icon_color }
              : undefined,
          }}
        />
      </Stack>
    </Paper>
  );
};

export default DatePickerRenderer;
