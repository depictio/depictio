import React, { useEffect, useState, useRef } from 'react';
import { DepictioMultiSelect } from 'depictio-components';

import {
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';

// Module-level cache for unique-values fetches. Keyed by `${dcId}|${column}`.
// Cleared on page reload — adequate for the MVP; a longer-lived cache (TTL +
// invalidation on filter-column upload) can come later.
const uniqueValuesCache = new Map<string, Promise<string[]>>();

const MultiSelectRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
}> = ({ metadata, filters, onChange }) => {
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

  const selected =
    (filters.find((f) => f.index === metadata.index)?.value as string[]) || [];

  // Mirrors Dash DEFAULT_ICONS in interactive_component/utils.py:1622.
  const defaultIcon =
    metadata.interactive_component_type === 'SegmentedControl' ||
    metadata.interactive_component_type === 'Switch'
      ? 'mdi:toggle-switch'
      : 'mdi:form-select';

  return (
    <DepictioMultiSelect
      title={metadata.title}
      column_name={metadata.column_name}
      interactive_component_type={metadata.interactive_component_type}
      options={options}
      value={selected}
      placeholder={
        loading
          ? 'Loading options…'
          : `Select ${metadata.column_name || 'values'}…`
      }
      color={
        // Mirrors `kwargs.get("color") or kwargs.get("custom_color")` from
        // depictio/dash/modules/interactive_component/utils.py:1612
        ((metadata as Record<string, unknown>).color as string | undefined) ||
        ((metadata as Record<string, unknown>).custom_color as string | undefined)
      }
      icon_name={metadata.icon_name || defaultIcon}
      icon_color={metadata.icon_color}
      title_color={metadata.title_color}
      title_size={
        ((metadata as Record<string, unknown>).title_size as
          | 'xs' | 'sm' | 'md' | 'lg' | 'xl' | undefined) ||
        metadata.title_font_size ||
        'md'
      }
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
  );
};

export default MultiSelectRenderer;
