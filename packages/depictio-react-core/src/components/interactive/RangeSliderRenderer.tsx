import React, { useEffect, useMemo, useState } from 'react';
import { DepictioRangeSlider } from 'depictio-components';
import ComponentSkeleton from '../ComponentSkeleton';

import {
  ColumnRange,
  fetchColumnRange,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { InteractiveFrame, InteractiveTitle, interactiveAccentRaw } from './frame';
import { buildNumericScale } from './numericScale';

const rangeCache = new Map<string, Promise<ColumnRange>>();

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

  return (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle metadata={metadata} compact={compact} />
      <DepictioRangeSlider
        bare
        min={bounds.min}
        max={bounds.max}
        value={selectedValue || [bounds.min, bounds.max]}
        // Same accent the title row paints its icon and label with.
        color={interactiveAccentRaw(metadata)}
        step={scale.step}
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
    </InteractiveFrame>
  );
};

export default RangeSliderRenderer;
