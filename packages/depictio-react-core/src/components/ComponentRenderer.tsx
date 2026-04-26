import React, { useRef } from 'react';
import { DepictioCard } from 'depictio-components';
import type { GridApi } from 'ag-grid-community';

import { InteractiveFilter, StoredMetadata } from '../api';
import FigureRenderer from './FigureRenderer';
import TableRenderer from './TableRenderer';
import ImageRenderer from './ImageRenderer';
import MapRenderer from './MapRenderer';
import JBrowseRenderer from './JBrowseRenderer';
import MultiQCRenderer from './MultiQCRenderer';
import MultiSelectRenderer from './interactive/MultiSelectRenderer';
import RangeSliderRenderer from './interactive/RangeSliderRenderer';
import SliderRenderer from './interactive/SliderRenderer';
import DatePickerRenderer from './interactive/DatePickerRenderer';
import CheckboxSwitchRenderer from './interactive/CheckboxSwitchRenderer';
import SegmentedControlRenderer from './interactive/SegmentedControlRenderer';
import { wrapWithChrome } from './chrome';

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
  /** Extra action-icon nodes appended to the chrome row. Editor uses this to inject the per-cell "..." edit menu. */
  extraActions?: React.ReactNode;
  /** Show the drag handle (3×3 grip) on the chrome — typically only in editor mode. */
  showDragHandle?: boolean;
}

/**
 * Renders ONE component based on metadata.component_type, wrapped in a
 * `ComponentChrome` that adds metadata/fullscreen/download/reset action icons.
 */
const ComponentRenderer: React.FC<ComponentRendererProps> = ({
  metadata,
  filters,
  onFilterChange,
  cardValue,
  cardLoading,
  dashboardId,
  extraActions,
  showDragHandle,
}) => {
  if (metadata.component_type === 'card') {
    return wrapWithChrome(
      'card',
      metadata,
      undefined,
      <CardRenderer
        metadata={metadata}
        value={cardValue}
        loading={cardLoading}
        filterApplied={filters.length > 0}
      />,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'interactive') {
    const onResetFilter = onFilterChange
      ? () => onFilterChange({ index: metadata.index, value: null })
      : undefined;
    const subType = metadata.interactive_component_type;
    let inner: React.ReactNode;
    if (subType === 'MultiSelect' || subType === 'Select') {
      inner = (
        <MultiSelectRenderer metadata={metadata} filters={filters} onChange={onFilterChange} />
      );
    } else if (subType === 'RangeSlider') {
      inner = (
        <RangeSliderRenderer metadata={metadata} filters={filters} onChange={onFilterChange} />
      );
    } else if (subType === 'Slider') {
      inner = <SliderRenderer metadata={metadata} filters={filters} onChange={onFilterChange} />;
    } else if (subType === 'DatePicker' || subType === 'DateRangePicker') {
      inner = (
        <DatePickerRenderer metadata={metadata} filters={filters} onChange={onFilterChange} />
      );
    } else if (subType === 'Checkbox' || subType === 'Switch') {
      inner = (
        <CheckboxSwitchRenderer metadata={metadata} filters={filters} onChange={onFilterChange} />
      );
    } else if (subType === 'SegmentedControl') {
      inner = (
        <SegmentedControlRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
        />
      );
    } else {
      inner = (
        <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
          Interactive type "{subType}" not yet ported to the React viewer.
        </div>
      );
    }
    return wrapWithChrome('interactive', metadata, undefined, inner, { onResetFilter, extraActions, showDragHandle });
  }

  if (metadata.component_type === 'figure' && dashboardId) {
    return wrapWithChrome(
      'figure',
      metadata,
      undefined,
      <FigureRenderer dashboardId={dashboardId} metadata={metadata} filters={filters} />,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'table' && dashboardId) {
    return (
      <TableBlock
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        extraActions={extraActions}
        showDragHandle={showDragHandle}
      />
    );
  }

  if (metadata.component_type === 'image' && dashboardId) {
    return wrapWithChrome(
      'image',
      metadata,
      undefined,
      <ImageRenderer dashboardId={dashboardId} metadata={metadata} />,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'map' && dashboardId) {
    return wrapWithChrome(
      'map',
      metadata,
      undefined,
      <MapRenderer dashboardId={dashboardId} metadata={metadata} filters={filters} />,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'jbrowse' && dashboardId) {
    return wrapWithChrome(
      'jbrowse',
      metadata,
      undefined,
      <JBrowseRenderer dashboardId={dashboardId} metadata={metadata} filters={filters} />,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'multiqc' && dashboardId) {
    return wrapWithChrome(
      'multiqc',
      metadata,
      undefined,
      <MultiQCRenderer dashboardId={dashboardId} metadata={metadata} filters={filters} />,
      { extraActions, showDragHandle },
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
// Per-type wrappers that own refs locally — keeps hooks-rules-of-hooks happy
// (no useRef inside a switch).

const TableBlock: React.FC<{
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
}> = ({ dashboardId, metadata, filters, extraActions, showDragHandle }) => {
  const agGridApiRef = useRef<GridApi | null>(null);
  return wrapWithChrome(
    'table',
    metadata,
    undefined,
    <TableRenderer
      dashboardId={dashboardId}
      metadata={metadata}
      filters={filters}
      agGridApiRef={agGridApiRef}
    />,
    { agGridApiRef, extraActions, showDragHandle },
  );
};

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
