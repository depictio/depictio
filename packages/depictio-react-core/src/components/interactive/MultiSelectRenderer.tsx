import React, { useEffect, useMemo, useState, useRef } from 'react';
import { CompactControlSlot, DepictioMultiSelect } from 'depictio-components';
import ComponentSkeleton from '../ComponentSkeleton';

import {
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { useAvailableSet } from '../../availableValues';
import { INTERACTIVE_FRAME, InteractiveFrame, InteractiveTitle } from './frame';

// Module-level cache for unique-values fetches. Keyed by `${dcId}|${column}`.
// Cleared on page reload — adequate for the MVP; a longer-lived cache (TTL +
// invalidation on filter-column upload) can come later.
const uniqueValuesCache = new Map<string, Promise<string[]>>();

const MultiSelectRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Compact rendering — drops the frame, relies on the parent group's card. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  const [options, setOptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    if (!metadata.dc_id || !metadata.column_name) {
      setLoading(false);
      return;
    }
    // filter_expr varies the option set, so include it in the cache key.
    const cacheKey = `${metadata.dc_id}|${metadata.column_name}|${metadata.filter_expr || ''}`;
    let p = uniqueValuesCache.get(cacheKey);
    if (!p) {
      p = fetchUniqueValues(metadata.dc_id, metadata.column_name, metadata.filter_expr);
      uniqueValuesCache.set(cacheKey, p);
    }
    p.then((values) => {
      if (mountedRef.current) setOptions(values);
    })
      .catch((err) => {
        console.warn('[MultiSelectRenderer] fetchUniqueValues failed:', err);
        // Remove from cache on error so next mount retries.
        uniqueValuesCache.delete(cacheKey);
      })
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });

    return () => {
      mountedRef.current = false;
    };
  }, [metadata.dc_id, metadata.column_name, metadata.filter_expr]);

  // Coerce rather than cast: programmatic writers (AI set_widget plans,
  // hand-edited dashboards) can carry a scalar here, and handing Mantine's
  // MultiSelect a bare string crashes the whole page render (`.map` on a
  // non-array).
  const rawSelected = filters.find((f) => f.index === metadata.index)?.value;
  const selected = Array.isArray(rawSelected)
    ? rawSelected.map(String)
    : rawSelected == null
      ? []
      : [String(rawSelected)];

  // Grey out values that the filter's source DC declares but that aren't
  // present in the dashboard's joined data — see `availableValues.tsx`.
  // Sort order: available values first (so they're immediately visible),
  // then unavailable (greyed) values; alphabetical within each bucket using
  // a locale-aware natural compare so `Sample_2` sorts before `Sample_10`.
  const availableSet = useAvailableSet(metadata.dc_id, metadata.column_name);
  const optionItems = useMemo(() => {
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
    if (!availableSet) {
      return [...options]
        .sort((a, b) => collator.compare(a, b))
        .map((v) => ({ value: v, label: v }));
    }
    return [...options]
      .sort((a, b) => {
        const aAvail = availableSet.has(a);
        const bAvail = availableSet.has(b);
        if (aAvail !== bAvail) return aAvail ? -1 : 1;
        return collator.compare(a, b);
      })
      .map((v) => ({ value: v, label: v, disabled: !availableSet.has(v) }));
  }, [options, availableSet]);

  // Skeleton on first load so this widget matches the rest of the dashboard's
  // loading treatment instead of flashing an empty select. Framed like the
  // loaded state, so the panel row doesn't gain a border on arrival.
  if (loading) {
    return (
      <InteractiveFrame compact={compact}>
        <ComponentSkeleton variant="control" />
      </InteractiveFrame>
    );
  }

  return (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle metadata={metadata} compact={compact} />
      <CompactControlSlot compact={compact}>
        <DepictioMultiSelect
          bare
          size={compact ? 'xs' : INTERACTIVE_FRAME.controlSize}
          column_name={metadata.column_name}
          options={optionItems}
          value={selected}
          placeholder={`Select ${metadata.column_name || 'values'}…`}
          onChange={(next) =>
            onChange?.({
              index: metadata.index,
              value: next,
              column_name: metadata.column_name,
              interactive_component_type: metadata.interactive_component_type,
              filter_expr: metadata.filter_expr,
            })
          }
        />
      </CompactControlSlot>
    </InteractiveFrame>
  );
};

export default MultiSelectRenderer;
