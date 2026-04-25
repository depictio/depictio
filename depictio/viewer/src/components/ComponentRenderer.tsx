import React, { useEffect, useState, useRef } from 'react';
import {
  DepictioCard,
  DepictioMultiSelect,
  DepictioRangeSlider,
} from 'depictio-components';

import {
  fetchColumnRange,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../api';
import FigureRenderer from './FigureRenderer';
import TableRenderer from './TableRenderer';

interface ComponentRendererProps {
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Computed value from bulk compute endpoint. Parent manages the state. */
  cardValue?: unknown;
  /** True while the parent's bulk compute is in flight. */
  cardLoading?: boolean;
  /** Required for figure/table fetches. */
  dashboardId?: string;
}

/**
 * Renders ONE component based on metadata.component_type. Data flow:
 *   - Cards: parent App runs a single bulk_compute_cards fetch for all cards
 *     on mount AND on filter change. This component just displays `cardValue`.
 *   - MultiSelect: self-fetches its options list once (dedup cached in parent
 *     via useRef if the same dc_id+column recurs).
 */
const ComponentRenderer: React.FC<ComponentRendererProps> = ({
  metadata,
  filters,
  onFilterChange,
  cardValue,
  cardLoading,
  dashboardId,
}) => {
  if (metadata.component_type === 'card') {
    return (
      <CardRenderer
        metadata={metadata}
        value={cardValue}
        loading={cardLoading}
        filterApplied={filters.length > 0}
      />
    );
  }

  if (metadata.component_type === 'interactive') {
    const subType = metadata.interactive_component_type;
    if (subType === 'MultiSelect' || subType === 'Select') {
      return (
        <MultiSelectRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
        />
      );
    }
    if (subType === 'RangeSlider') {
      return (
        <RangeSliderRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
        />
      );
    }
    return (
      <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
        Interactive type "{subType}" not yet ported to the React viewer.
      </div>
    );
  }

  if (metadata.component_type === 'figure' && dashboardId) {
    return (
      <FigureRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
      />
    );
  }

  if (metadata.component_type === 'table' && dashboardId) {
    return (
      <TableRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
      />
    );
  }

  return (
    <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
      Component type "{metadata.component_type}" not yet ported.
    </div>
  );
};

export default ComponentRenderer;

// ---------------------------------------------------------------------------

const CardRenderer: React.FC<{
  metadata: StoredMetadata;
  value?: unknown;
  loading?: boolean;
  filterApplied: boolean;
}> = ({ metadata, value, loading, filterApplied }) => {
  const displayValue =
    loading && value == null
      ? '…'
      : value != null
      ? formatValue(value)
      : '—';

  return (
    <DepictioCard
      title={metadata.title || inferCardTitle(metadata)}
      value={displayValue}
      icon_name={metadata.icon_name}
      icon_color={metadata.icon_color}
      title_color={metadata.title_color}
      background_color={metadata.background_color}
      title_font_size={metadata.title_font_size || 'md'}
      value_font_size={metadata.value_font_size || 'xl'}
      aggregation_description={
        metadata.aggregation ? `(${capitalize(metadata.aggregation)})` : undefined
      }
      filter_applied={filterApplied}
    />
  );
};

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
    const cacheKey = `${metadata.dc_id}|${metadata.column_name}`;
    let p = uniqueValuesCache.get(cacheKey);
    if (!p) {
      p = fetchUniqueValues(metadata.dc_id, metadata.column_name);
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
  }, [metadata.dc_id, metadata.column_name]);

  const selected =
    (filters.find((f) => f.index === metadata.index)?.value as string[]) || [];

  return (
    <DepictioMultiSelect
      title={metadata.title}
      column_name={metadata.column_name}
      options={options}
      value={selected}
      placeholder={
        loading
          ? 'Loading options…'
          : `Select ${metadata.column_name || 'values'}…`
      }
      color={metadata.icon_color}
      icon_name={metadata.icon_name}
      onChange={(next) =>
        onChange?.({
          index: metadata.index,
          value: next,
          column_name: metadata.column_name,
          interactive_component_type: metadata.interactive_component_type,
        })
      }
    />
  );
};

// ---------------------------------------------------------------------------

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
      min={bounds.min}
      max={bounds.max}
      value={selectedValue || [bounds.min, bounds.max]}
      icon_name={metadata.icon_name}
      color={metadata.icon_color}
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

// ---------------------------------------------------------------------------

function inferCardTitle(m: StoredMetadata): string {
  if (m.aggregation && m.column_name) {
    return `${capitalize(String(m.aggregation))} of ${m.column_name}`;
  }
  return String(m.column_name || 'Metric');
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatValue(v: unknown): string | number {
  if (typeof v === 'number') {
    if (!Number.isInteger(v)) return v.toFixed(4).replace(/\.?0+$/, '');
    return v;
  }
  return String(v);
}
