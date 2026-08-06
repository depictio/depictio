import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Text, Slider } from '@mantine/core';
import { CompactControlSlot } from 'depictio-components';

import { ColumnRange, fetchColumnRange, InteractiveFilter, StoredMetadata } from '../../api';
import ComponentSkeleton from '../ComponentSkeleton';
import {
  InteractiveFrame,
  InteractiveTitle,
  SLIDER_MARK_LABEL_STYLE,
  SLIDER_MARKS_CLASS,
  interactiveAccent,
} from './frame';
import { buildNumericScale, formatSliderValue } from './numericScale';

/**
 * Single-value Slider renderer for the React viewer.
 *
 * Mirror of the Dash `_build_slider_component` for `interactive_component_type === "Slider"`.
 * Reads the column's precomputed specs via `fetchColumnRange`, then renders a Mantine
 * `Slider` whose stops come from the column's own granularity (`buildNumericScale`).
 * On change emits `{index, value, column_name, interactive_component_type: 'Slider'}`
 * upstream.
 *
 * Mirrors the data-fetch + module-level cache pattern used by RangeSliderRenderer in
 * ComponentRenderer.tsx so multiple Slider instances on the same (dc_id, column) share
 * one in-flight fetch.
 */

const rangeCache = new Map<string, Promise<ColumnRange>>();

const SliderRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Compact rendering — drops the inner Paper, defaults marks to hidden. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  const [bounds, setBounds] = useState<{
    min: number;
    max: number;
    dtype?: string | null;
    unique?: number | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const defaultState = (metadata.default_state || {}) as Record<string, unknown>;
  const useLogScale = ((defaultState.scale as string) || 'linear') === 'log10';
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
        setBounds({ min: rawMin, max: rawMax, dtype: res.dtype, unique: res.unique });
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

  const scale = useMemo(
    () =>
      bounds
        ? buildNumericScale(bounds, {
            marksNumber,
            // Log bounds are transformed: whole numbers on them say nothing
            // about the column's own granularity.
            continuous: useLogScale,
            // Display label uses the original (non-log) value for log-scale
            // sliders, matching the Dash port at utils.py:184-198.
            format: (v) => formatSliderValue(useLogScale ? 10 ** v : v),
          })
        : null,
    [bounds, marksNumber, useLogScale],
  );

  // YAML wins; otherwise compact mode hides marks for higher density — except
  // on a discrete scale, where the marks are the only thing saying which values
  // the thumb can reach.
  const marksVisible =
    typeof metadata.show_marks === 'boolean'
      ? metadata.show_marks
      : !compact || Boolean(scale?.discrete);
  // A restricted slider still needs its marks passed even when their labels are
  // suppressed — they are what it snaps to.
  const marks = !scale
    ? undefined
    : marksVisible
      ? scale.marks
      : scale.discrete
        ? scale.marks.map((m) => ({ value: m.value }))
        : undefined;

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
        filter_expr: metadata.filter_expr,
      });
    },
    [onChange, metadata.index, metadata.column_name, metadata.filter_expr],
  );

  if (error) {
    return (
      <InteractiveFrame compact={compact}>
        <Text size="xs" c="red" className="dashboard-error">
          {error}
        </Text>
      </InteractiveFrame>
    );
  }

  if (loading || !bounds || !scale) {
    return (
      <InteractiveFrame compact={compact}>
        <ComponentSkeleton variant="control" />
      </InteractiveFrame>
    );
  }

  const value = selectedValue != null ? selectedValue : bounds.min;
  const readout = (v: number) => formatSliderValue(useLogScale ? 10 ** v : v);
  // Mantine takes a palette name on `color`; a raw hex has to be painted onto
  // the parts, which is also where the tick-label size is set.
  const accent = interactiveAccent(metadata);
  const rawAccent = accent?.startsWith('#') || accent?.startsWith('rgb') || accent?.startsWith('var(');

  return (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle
        metadata={metadata}
        compact={compact}
        right={
          <Text size="xs" c="dimmed" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {readout(value)}
          </Text>
        }
      />
      <CompactControlSlot compact={compact}>
        <Slider
          className={SLIDER_MARKS_CLASS}
          min={bounds.min}
          max={bounds.max}
          step={scale.step}
          restrictToMarks={scale.discrete}
          value={value}
          onChangeEnd={handleChange}
          marks={marks}
          size={compact ? 'sm' : 'md'}
          thumbSize={compact ? 12 : undefined}
          color={accent && !rawAccent ? accent : undefined}
          styles={{
            markLabel: SLIDER_MARK_LABEL_STYLE,
            ...(accent && rawAccent
              ? {
                  bar: { backgroundColor: accent },
                  thumb: { borderColor: accent, backgroundColor: accent },
                }
              : {}),
          }}
          label={readout}
          // Mark labels hang below the track, so they need the room a compact
          // slider otherwise gives away.
          mb={compact ? (marksVisible ? 'sm' : 0) : 'xs'}
        />
      </CompactControlSlot>
    </InteractiveFrame>
  );
};

export default SliderRenderer;
