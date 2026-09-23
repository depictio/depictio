import React, { useEffect, useMemo, useState } from 'react';
import { CompactControlSlot, DepictioRangeSlider } from 'depictio-components';
import { Tooltip } from '@mantine/core';
import ComponentSkeleton from '../ComponentSkeleton';

import {
  ColumnRange,
  fetchAdvancedVizData,
  fetchColumnRange,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { InteractiveFrame, InteractiveTitle, interactiveAccent, interactiveAccentRaw } from './frame';
import { buildNumericScale, formatSliderValue } from './numericScale';

const rangeCache = new Map<string, Promise<ColumnRange>>();

/** Bars in the distribution sparkline. Enough to show a mode and a tail inside
 *  the Filters panel's width, few enough that each bar stays a bar. */
const HISTOGRAM_BINS = 32;
/** Sparkline height. Tall enough to read a shape, short enough that the filter
 *  keeps reading as a control with a hint above it rather than as a chart. */
const HISTOGRAM_HEIGHT = 32;

/** Bin counts per column, shared by every slider bound to it. Keyed on the
 *  bounds too: a different [min, max] is a different set of bars. */
const histogramCache = new Map<string, Promise<number[] | null>>();

/**
 * Bin a column's values into `HISTOGRAM_BINS` equal-width buckets across the
 * slider's own [min, max], so bar *i* stands exactly where the track's value
 * for bin *i* is. Returns null when nothing numeric came back, which is the
 * signal to draw no sparkline at all.
 */
function binValues(values: unknown[], min: number, max: number): number[] | null {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return null;
  const counts = new Array<number>(HISTOGRAM_BINS).fill(0);
  let seen = 0;
  for (const raw of values) {
    const v = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(v) || v < min || v > max) continue;
    const bin = Math.min(
      HISTOGRAM_BINS - 1,
      Math.floor(((v - min) / (max - min)) * HISTOGRAM_BINS),
    );
    counts[bin] += 1;
    seen += 1;
  }
  return seen > 0 ? counts : null;
}

/**
 * The bound column's distribution, drawn on the slider's own domain.
 *
 * Plain SVG rather than a Plotly bar chart: at this size every axis, margin
 * and modebar Plotly would bring has to be turned off again, and the Filters
 * panel would pay for the plotly chunk to draw 32 rectangles. The viewBox is
 * one unit per bin with `preserveAspectRatio="none"`, so the bars stretch to
 * whatever width the track has and stay aligned to it.
 *
 * Bins the thumbs currently span are drawn in the filter's own accent; the
 * rest of the distribution stays visible but dimmed, so the reader sees what
 * the threshold is excluding rather than only what it keeps.
 */
const ColumnHistogram: React.FC<{
  bins: number[];
  min: number;
  max: number;
  range: [number, number];
  color: string;
}> = ({ bins, min, max, range, color }) => {
  // The bin under the pointer, resolved from the pointer's x on the wrapper:
  // the bars are stretched by `preserveAspectRatio="none"`, so one bin is one
  // equal slice of the width whatever the container is.
  const [hovered, setHovered] = useState<number | null>(null);
  const peak = Math.max(...bins);
  if (peak <= 0) return null;
  const span = max - min;
  const total = bins.reduce((acc, n) => acc + n, 0);
  const edges = (i: number): [number, number] => [
    min + (span * i) / bins.length,
    min + (span * (i + 1)) / bins.length,
  ];
  const label =
    hovered === null
      ? null
      : `${formatSliderValue(edges(hovered)[0])} to ${formatSliderValue(edges(hovered)[1])}: ` +
        `${bins[hovered].toLocaleString('en-US')} rows` +
        (total > 0 ? ` (${((100 * bins[hovered]) / total).toFixed(1)}%)` : '');
  return (
    <Tooltip
      label={label ?? ''}
      opened={label !== null}
      disabled={label === null}
      position="top"
      withArrow
    >
      <div
        style={{ width: '100%', height: HISTOGRAM_HEIGHT, cursor: 'crosshair' }}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width <= 0) return;
          const i = Math.floor(((e.clientX - rect.left) / rect.width) * bins.length);
          setHovered(Math.max(0, Math.min(bins.length - 1, i)));
        }}
        onMouseLeave={() => setHovered(null)}
      >
        <svg
          viewBox={`0 0 ${bins.length} 10`}
          preserveAspectRatio="none"
          role="presentation"
          aria-hidden
          style={{ width: '100%', height: HISTOGRAM_HEIGHT, display: 'block' }}
        >
          {bins.map((count, i) => {
            const [binLow, binHigh] = edges(i);
            const inRange = binHigh >= range[0] && binLow <= range[1];
            const height = (count / peak) * 10;
            const isHovered = hovered === i;
            return (
              <rect
                key={i}
                x={i + 0.1}
                y={10 - height}
                width={0.8}
                height={height}
                fill={color}
                opacity={isHovered ? 1 : inRange ? 0.85 : 0.2}
              />
            );
          })}
        </svg>
      </div>
    </Tooltip>
  );
};

const RangeSliderRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** When true (e.g. inside an InteractiveGroupCard), drop the inner Paper
   *  and default tick marks to hidden — relies on the parent to provide the
   *  visual frame. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  const [bounds, setBounds] = useState<{
    min: number;
    max: number;
    dtype?: string | null;
    unique?: number | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);

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
      const min = typeof res.min === 'number' ? res.min : 0;
      const max = typeof res.max === 'number' ? res.max : 100;
      setBounds({ min, max, dtype: res.dtype, unique: res.unique });
    })
      .catch((err) => {
        console.warn('[RangeSliderRenderer] fetchColumnRange failed:', err);
        rangeCache.delete(cacheKey);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, metadata.column_name]);

  // Opt-in, so a slider that says nothing keeps exactly the layout it had.
  const showHistogram = (metadata as { show_histogram?: boolean }).show_histogram === true;
  const [histogram, setHistogram] = useState<number[] | null>(null);

  useEffect(() => {
    const column = metadata.column_name;
    if (!showHistogram || !bounds || !metadata.wf_id || !metadata.dc_id || !column) return;
    // The bounds fetch reads the DC's precomputed specs, which carry min, max
    // and a distinct count but no values, so there is nothing there to bin.
    // This is the one extra call, and it goes to the endpoint that already
    // projects a column subset out of a DC.
    //
    // Sent unfiltered on purpose: the reader is placing a threshold against
    // the column's own distribution, and a histogram that shrank as the thumbs
    // moved would be measuring the answer with the question. That also makes
    // the result cacheable for the life of the page.
    const key = `${metadata.dc_id}|${column}|${bounds.min}|${bounds.max}`;
    let p = histogramCache.get(key);
    if (!p) {
      p = fetchAdvancedVizData({
        wfId: metadata.wf_id,
        dcId: metadata.dc_id,
        columns: [column],
        filters: [],
      })
        .then((res) => binValues(res.rows?.[column] ?? [], bounds.min, bounds.max))
        .catch((err) => {
          // No sparkline rather than an error or a spinner that never ends:
          // the slider itself is unaffected and still filters.
          console.warn('[RangeSliderRenderer] histogram fetch failed:', err);
          histogramCache.delete(key);
          return null;
        });
      histogramCache.set(key, p);
    }
    let cancelled = false;
    p.then((bins) => {
      if (!cancelled) setHistogram(bins);
    });
    return () => {
      cancelled = true;
    };
  }, [
    showHistogram,
    metadata.wf_id,
    metadata.dc_id,
    metadata.column_name,
    bounds?.min,
    bounds?.max,
  ]);

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selectedValue =
    Array.isArray(filterEntry?.value) && filterEntry!.value.length === 2
      ? (filterEntry!.value as [number, number])
      : null;

  const marksNumber = (metadata.default_state as Record<string, unknown> | undefined)
    ?.marks_number as number | undefined;
  const scale = useMemo(
    // A continuous range slider anchors on its two ends unless the author asks
    // for more — that is what it has always drawn, and five labels do not fit
    // the Filters panel's width. A discrete scale ignores the number and marks
    // every value it has.
    () => (bounds ? buildNumericScale(bounds, { marksNumber: marksNumber ?? 2 }) : null),
    [bounds, marksNumber],
  );

  if (loading || !bounds || !scale) {
    return (
      <InteractiveFrame compact={compact}>
        <ComponentSkeleton variant="control" />
      </InteractiveFrame>
    );
  }

  const currentRange: [number, number] = selectedValue || [bounds.min, bounds.max];

  return (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle metadata={metadata} compact={compact} />
      {/* Above the slot rather than inside it: the slot reserves one fixed
          control height in compact mode, and the sparkline is a hint sitting on
          top of the track, not part of the control. */}
      {showHistogram && histogram ? (
        <ColumnHistogram
          bins={histogram}
          min={bounds.min}
          max={bounds.max}
          range={currentRange}
          color={interactiveAccent(metadata) ?? 'var(--mantine-primary-color-filled)'}
        />
      ) : null}
      <CompactControlSlot compact={compact}>
      <DepictioRangeSlider
        bare
        min={bounds.min}
        max={bounds.max}
        value={currentRange}
        // Same accent the title row paints its icon and label with.
        color={interactiveAccentRaw(metadata)}
        step={scale.step}
        // Hand the canonical formatter down rather than letting the slider fall
        // back to its own copy: depictio-components cannot import from here (the
        // dependency runs the other way, and the Dash bundle uses it standalone),
        // so its mirror is a mirror, and this keeps the viewer reading the one in
        // numericScale.ts.
        format_value={formatSliderValue}
        marks={scale.marks}
        restrict_to_marks={scale.discrete}
        show_marks={
          // YAML wins; otherwise compact mode hides marks for higher density,
          // ungrouped renders show them — except on a discrete scale, where the
          // marks are the only thing saying which values the thumbs can reach.
          typeof metadata.show_marks === 'boolean'
            ? metadata.show_marks
            : !compact || scale.discrete
        }
        compact={compact}
        onChange={(next) =>
          onChange?.({
            index: metadata.index,
            value: next,
            column_name: metadata.column_name,
            interactive_component_type: 'RangeSlider',
            filter_expr: metadata.filter_expr,
          })
        }
      />
      </CompactControlSlot>
    </InteractiveFrame>
  );
};

export default RangeSliderRenderer;
