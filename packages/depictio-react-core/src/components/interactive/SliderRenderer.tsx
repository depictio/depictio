import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Paper, Stack, Text, Group, Slider } from '@mantine/core';
import { Icon } from '@iconify/react';

import { fetchColumnRange, InteractiveFilter, StoredMetadata } from '../../api';

/**
 * Single-value Slider renderer for the React viewer.
 *
 * Mirror of the Dash `_build_slider_component` for `interactive_component_type === "Slider"`.
 * Reads the column's precomputed numeric min/max via `fetchColumnRange`, then renders a
 * Mantine `Slider` with marks. On change emits `{index, value, column_name,
 * interactive_component_type: 'Slider'}` upstream.
 *
 * Mirrors the data-fetch + module-level cache pattern used by RangeSliderRenderer in
 * ComponentRenderer.tsx so multiple Slider instances on the same (dc_id, column) share
 * one in-flight fetch.
 */

const rangeCache = new Map<string, Promise<{ min: number | null; max: number | null }>>();

const SliderRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
}> = ({ metadata, filters, onChange }) => {
  const [bounds, setBounds] = useState<{ min: number; max: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const defaultState = (metadata.default_state || {}) as Record<string, unknown>;
  const scale = (defaultState.scale as string) || 'linear';
  const useLogScale = scale === 'log10';
  const marksNumber = Math.max(
    2,
    typeof defaultState.marks_number === 'number' ? (defaultState.marks_number as number) : 5,
  );

  useEffect(() => {
    if (!metadata.dc_id || !metadata.column_name) {
      setLoading(false);
      return;
    }
    const cacheKey = `${metadata.dc_id}|${metadata.column_name}`;
    let p = rangeCache.get(cacheKey);
    if (!p) {
      p = fetchColumnRange(metadata.dc_id, metadata.column_name);
      rangeCache.set(cacheKey, p);
    }
    let cancelled = false;
    p.then((res) => {
      if (cancelled) return;
      if (typeof res.min !== 'number' || typeof res.max !== 'number') {
        setError(
          `No numeric min/max available for column "${metadata.column_name}".`,
        );
        return;
      }
      // Apply log10 transformation to bounds — matches Dash utils.py:791-793.
      const rawMin = res.min;
      const rawMax = res.max;
      if (useLogScale) {
        if (rawMin <= 0 || rawMax <= 0) {
          setError(
            `Cannot apply log10 scale to column "${metadata.column_name}" — non-positive bounds.`,
          );
          return;
        }
        setBounds({ min: Math.log10(rawMin), max: Math.log10(rawMax) });
      } else {
        setBounds({ min: rawMin, max: rawMax });
      }
    })
      .catch((err) => {
        console.warn('[SliderRenderer] fetchColumnRange failed:', err);
        rangeCache.delete(cacheKey);
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, metadata.column_name, useLogScale]);

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selectedValue =
    typeof filterEntry?.value === 'number' ? (filterEntry!.value as number) : null;

  const marks = useMemo(() => {
    if (!bounds) return [];
    const n = Math.max(2, marksNumber);
    const stepSize = (bounds.max - bounds.min) / (n - 1);
    return Array.from({ length: n }, (_, i) => {
      const v = bounds.min + stepSize * i;
      // Display label uses the original (non-log) value for log-scale sliders,
      // matching the Dash port at utils.py:184-198.
      const labelVal = useLogScale ? 10 ** v : v;
      return { value: v, label: formatMark(labelVal) };
    });
  }, [bounds, marksNumber, useLogScale]);

  // Hook order is fixed for every render — keep useCallback BEFORE any
  // early returns. Otherwise React's hook-count check (error #310) trips on
  // the loading→loaded transition.
  const handleChange = useCallback(
    (next: number) => {
      onChange?.({
        index: metadata.index,
        value: next,
        column_name: metadata.column_name,
        interactive_component_type: 'Slider',
      });
    },
    [onChange, metadata.index, metadata.column_name],
  );

  if (error) {
    return (
      <div
        className="dashboard-error"
        style={{ fontSize: '0.75rem', color: 'var(--mantine-color-red-6)' }}
      >
        {error}
      </div>
    );
  }

  if (loading || !bounds) {
    return (
      <div className="dashboard-loading" style={{ minHeight: 80, fontSize: '0.75rem' }}>
        Loading range…
      </div>
    );
  }

  const value = selectedValue != null ? selectedValue : bounds.min;
  const displayTitle =
    metadata.title || (metadata.column_name ? `Slider on ${metadata.column_name}` : '');
  const iconCol = metadata.icon_color || 'var(--mantine-color-blue-6)';
  const stepSize = (bounds.max - bounds.min) / 100;

  return (
    <Paper
      p="md"
      radius="md"
      shadow="xs"
      className="dashboard-component-hover"
      style={{
        height: '100%',
        boxSizing: 'border-box',
      }}
    >
      <Stack gap="md">
        {displayTitle && (
          <Group gap="xs" align="center" wrap="nowrap" justify="space-between">
            <Group gap="xs" align="center" wrap="nowrap">
              {metadata.icon_name && (
                <Icon
                  icon={metadata.icon_name}
                  width={18}
                  height={18}
                  style={{ color: iconCol, flexShrink: 0 }}
                />
              )}
              <Text fw={600} size="sm">
                {displayTitle}
              </Text>
            </Group>
            <Text size="xs" c="dimmed">
              {formatMark(useLogScale ? 10 ** value : value)}
            </Text>
          </Group>
        )}
        <Slider
          min={bounds.min}
          max={bounds.max}
          step={stepSize}
          value={value}
          onChangeEnd={handleChange}
          marks={marks}
          color={metadata.icon_color || undefined}
          label={(v) => formatMark(useLogScale ? 10 ** v : v)}
          mb="xs"
        />
      </Stack>
    </Paper>
  );
};

function formatMark(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return String(v);
  const abs = Math.abs(v);
  if (abs >= 1000 || (abs > 0 && abs < 0.01)) return v.toExponential(2);
  return v.toFixed(2).replace(/\.?0+$/, '');
}

export default SliderRenderer;
