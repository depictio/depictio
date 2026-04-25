import React from 'react';
import { DepictioCard } from 'depictio-components';

import { InteractiveFilter, StoredMetadata } from '../api';
import FigureRenderer from './FigureRenderer';
import TableRenderer from './TableRenderer';
import ImageRenderer from './ImageRenderer';
import MultiSelectRenderer from './interactive/MultiSelectRenderer';
import RangeSliderRenderer from './interactive/RangeSliderRenderer';
import SliderRenderer from './interactive/SliderRenderer';
import DatePickerRenderer from './interactive/DatePickerRenderer';
import CheckboxSwitchRenderer from './interactive/CheckboxSwitchRenderer';
import SegmentedControlRenderer from './interactive/SegmentedControlRenderer';

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
 *   - Interactive sub-types live under ./interactive/ and self-fetch their
 *     own bounds/options as needed.
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
    if (subType === 'Slider') {
      return (
        <SliderRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
        />
      );
    }
    if (subType === 'DatePicker' || subType === 'DateRangePicker') {
      return (
        <DatePickerRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
        />
      );
    }
    if (subType === 'Checkbox' || subType === 'Switch') {
      return (
        <CheckboxSwitchRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
        />
      );
    }
    if (subType === 'SegmentedControl') {
      return (
        <SegmentedControlRenderer
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

  if (metadata.component_type === 'image' && dashboardId) {
    return (
      <ImageRenderer
        dashboardId={dashboardId}
        metadata={metadata}
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
