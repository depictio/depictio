import React, { useEffect, useState } from 'react';
import { DepictioRangeSlider } from 'depictio-components';

import {
  fetchColumnRange,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';

const rangeCache = new Map<string, Promise<{ min: number | null; max: number | null }>>();

const RangeSliderRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
}> = ({ metadata, filters, onChange }) => {
  const [bounds, setBounds] = useState<{ min: number; max: number } | null>(null);
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
      setBounds({ min, max });
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

  if (loading || !bounds) {
    return (
      <div className="dashboard-loading" style={{ minHeight: 80, fontSize: '0.75rem' }}>
        Loading range…
      </div>
    );
  }

  return (
    <DepictioRangeSlider
      title={metadata.title}
      column_name={metadata.column_name}
      interactive_component_type={metadata.interactive_component_type}
      min={bounds.min}
      max={bounds.max}
      value={selectedValue || [bounds.min, bounds.max]}
      icon_name={metadata.icon_name || 'bx:slider-alt'}
      icon_color={metadata.icon_color}
      color={
        // Mirrors `kwargs.get("color") or kwargs.get("custom_color")` from
        // depictio/dash/modules/interactive_component/utils.py:1612
        ((metadata as Record<string, unknown>).color as string | undefined) ||
        ((metadata as Record<string, unknown>).custom_color as string | undefined)
      }
      title_color={metadata.title_color}
      title_size={
        ((metadata as Record<string, unknown>).title_size as
          | 'xs' | 'sm' | 'md' | 'lg' | 'xl' | undefined) ||
        metadata.title_font_size ||
        'md'
      }
      marks_number={(metadata.default_state as Record<string, unknown> | undefined)?.marks_number as number | undefined}
      onChange={(next) =>
        onChange?.({
          index: metadata.index,
          value: next,
          column_name: metadata.column_name,
          interactive_component_type: 'RangeSlider',
        })
      }
    />
  );
};

export default RangeSliderRenderer;
