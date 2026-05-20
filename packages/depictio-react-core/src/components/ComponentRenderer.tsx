import React, { useRef } from 'react';
import { DepictioCard } from 'depictio-components';
import type { GridApi } from 'ag-grid-community';

import { InteractiveFilter, StoredMetadata } from '../api';
import FigureRenderer from './FigureRenderer';
import TableRenderer from './TableRenderer';
import ImageRenderer from './ImageRenderer';
import MapRenderer from './MapRenderer';
import TextRenderer from './TextRenderer';
import JBrowseRenderer from './JBrowseRenderer';
import MultiQCRenderer from './MultiQCRenderer';
import VolcanoRenderer from './advanced_viz/VolcanoRenderer';
import EmbeddingRenderer from './advanced_viz/EmbeddingRenderer';
import ManhattanRenderer from './advanced_viz/ManhattanRenderer';
import StackedTaxonomyRenderer from './advanced_viz/StackedTaxonomyRenderer';
import PhylogeneticRenderer from './advanced_viz/PhylogeneticRenderer';
import RarefactionRenderer from './advanced_viz/RarefactionRenderer';
import DaBarplotRenderer from './advanced_viz/DaBarplotRenderer';
import EnrichmentRenderer from './advanced_viz/EnrichmentRenderer';
import ComplexHeatmapRenderer from './advanced_viz/ComplexHeatmapRenderer';
import UpsetRenderer from './advanced_viz/UpsetRenderer';
import MARenderer from './advanced_viz/MARenderer';
import DotPlotRenderer from './advanced_viz/DotPlotRenderer';
import LollipopRenderer from './advanced_viz/LollipopRenderer';
import QQRenderer from './advanced_viz/QQRenderer';
import SunburstRenderer from './advanced_viz/SunburstRenderer';
import OncoplotRenderer from './advanced_viz/OncoplotRenderer';
import CoverageTrackRenderer from './advanced_viz/CoverageTrackRenderer';
import SankeyRenderer from './advanced_viz/SankeyRenderer';
import { AdvancedVizExtrasProvider } from './advanced_viz/AdvancedVizExtras';
import MultiSelectRenderer from './interactive/MultiSelectRenderer';
import RangeSliderRenderer from './interactive/RangeSliderRenderer';
import SliderRenderer from './interactive/SliderRenderer';
import DatePickerRenderer from './interactive/DatePickerRenderer';
import CheckboxSwitchRenderer from './interactive/CheckboxSwitchRenderer';
import SegmentedControlRenderer from './interactive/SegmentedControlRenderer';
import TimelineRenderer from './interactive/TimelineRenderer';
import SecondaryMetrics from './card/SecondaryMetrics';
import { wrapWithChrome } from './chrome';

interface ComponentRendererProps {
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Computed value from bulk compute endpoint. Parent manages the state. */
  cardValue?: unknown;
  /** Secondary aggregations for multi-metric cards (keyed by aggregation name). */
  cardSecondaryValues?: Record<string, unknown>;
  /** True while the parent's bulk compute is in flight. */
  cardLoading?: boolean;
  /** Required for figure/table fetches. */
  dashboardId?: string;
  /** Counter to invalidate data-fetching effects on realtime updates. */
  refreshTick?: number;
  /** Extra action-icon nodes appended to the chrome row. Editor uses this to inject the per-cell "..." edit menu. */
  extraActions?: React.ReactNode;
  /** Show the drag handle (3×3 grip) on the chrome — typically only in editor mode. */
  showDragHandle?: boolean;
  /** Compact rendering — used by InteractiveGroupCard so grouped slider /
   *  rangeslider / timeline children drop their own Paper and tighten internal
   *  spacing. Marks default to hidden unless the metadata sets show_marks=true. */
  compact?: boolean;
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
  cardSecondaryValues,
  cardLoading,
  dashboardId,
  refreshTick,
  extraActions,
  showDragHandle,
  compact,
}) => {
  if (metadata.component_type === 'card') {
    return wrapWithChrome(
      'card',
      metadata,
      undefined,
      <CardRenderer
        metadata={metadata}
        value={cardValue}
        secondaryValues={cardSecondaryValues}
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
        <RangeSliderRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
          compact={compact}
        />
      );
    } else if (subType === 'Slider') {
      inner = (
        <SliderRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
          compact={compact}
        />
      );
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
    } else if (subType === 'Timeline') {
      inner = (
        <TimelineRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
          compact={compact}
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
    // Only scatter / scatter_3d traces carry the per-row customdata we need
    // for meaningful cross-filter selection. Aggregated visus (histogram,
    // box, bar, pie, …) would emit per-bin envelopes — hide the reset
    // affordance there too so chrome stays clean.
    const isScatterLikeForSelection =
      metadata.visu_type === 'scatter' || metadata.visu_type === 'scatter_3d';
    const selectionEnabled =
      Boolean(metadata.selection_enabled) && !!onFilterChange && isScatterLikeForSelection;
    const onResetSelection =
      selectionEnabled && onFilterChange
        ? () =>
            onFilterChange({
              index: metadata.index,
              value: [],
              source: 'scatter_selection',
            })
        : undefined;
    const sourceFilterActive = isSourceFilterActive(filters, metadata.index, 'scatter_selection');
    return wrapWithChrome(
      'figure',
      metadata,
      undefined,
      <FigureRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
      />,
      { onResetFilter: onResetSelection, extraActions, showDragHandle, sourceFilterActive },
    );
  }

  if (metadata.component_type === 'table' && dashboardId) {
    return (
      <TableBlock
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
        extraActions={extraActions}
        showDragHandle={showDragHandle}
      />
    );
  }

  if (metadata.component_type === 'image' && dashboardId) {
    const selectionEnabled = !!metadata.image_column && !!onFilterChange;
    const onResetSelection =
      selectionEnabled && onFilterChange
        ? () =>
            onFilterChange({
              index: metadata.index,
              value: [],
              source: 'image_selection',
            })
        : undefined;
    const sourceFilterActive = isSourceFilterActive(filters, metadata.index, 'image_selection');
    return wrapWithChrome(
      'image',
      metadata,
      undefined,
      <ImageRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
      />,
      { onResetFilter: onResetSelection, extraActions, showDragHandle, sourceFilterActive },
    );
  }

  if (metadata.component_type === 'map' && dashboardId) {
    const mapType = (metadata.map_type as string) || 'scatter_map';
    const selectionEnabled =
      Boolean(metadata.selection_enabled) &&
      mapType !== 'choropleth_map' &&
      !!onFilterChange;
    const onResetSelection =
      selectionEnabled && onFilterChange
        ? () =>
            onFilterChange({
              index: metadata.index,
              value: [],
              source: 'map_selection',
            })
        : undefined;
    const sourceFilterActive = isSourceFilterActive(filters, metadata.index, 'map_selection');
    return wrapWithChrome(
      'map',
      metadata,
      undefined,
      <MapRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
      />,
      { onResetFilter: onResetSelection, extraActions, showDragHandle, sourceFilterActive },
    );
  }

  if (metadata.component_type === 'jbrowse' && dashboardId) {
    return wrapWithChrome(
      'jbrowse',
      metadata,
      undefined,
      <JBrowseRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        refreshTick={refreshTick}
      />,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'text') {
    return wrapWithChrome(
      'text',
      metadata,
      undefined,
      <TextRenderer metadata={metadata} />,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'multiqc' && dashboardId) {
    return wrapWithChrome(
      'multiqc',
      metadata,
      undefined,
      <MultiQCRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        refreshTick={refreshTick}
      />,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'advanced_viz') {
    return (
      <AdvancedVizDispatch
        metadata={metadata}
        filters={filters}
        refreshTick={refreshTick}
        extraActions={extraActions}
        showDragHandle={showDragHandle}
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
// Per-type wrappers that own refs locally — keeps hooks-rules-of-hooks happy
// (no useRef inside a switch).

const TableBlock: React.FC<{
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  refreshTick?: number;
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
}> = ({
  dashboardId,
  metadata,
  filters,
  onFilterChange,
  refreshTick,
  extraActions,
  showDragHandle,
}) => {
  const agGridApiRef = useRef<GridApi | null>(null);
  const selectionEnabled = Boolean(metadata.row_selection_enabled) && !!onFilterChange;
  const onResetSelection =
    selectionEnabled && onFilterChange
      ? () => {
          agGridApiRef.current?.deselectAll();
          onFilterChange({
            index: metadata.index,
            value: [],
            source: 'table_selection',
          });
        }
      : undefined;
  const sourceFilterActive = isSourceFilterActive(filters, metadata.index, 'table_selection');
  return wrapWithChrome(
    'table',
    metadata,
    undefined,
    <TableRenderer
      dashboardId={dashboardId}
      metadata={metadata}
      filters={filters}
      agGridApiRef={agGridApiRef}
      onFilterChange={onFilterChange}
      refreshTick={refreshTick}
    />,
    {
      agGridApiRef,
      onResetFilter: onResetSelection,
      extraActions,
      showDragHandle,
      sourceFilterActive,
    },
  );
};

/** A filter is "source-active" for this component when an entry exists with
 *  matching `index`, the expected `source` discriminator, and a non-empty
 *  value (avoid false-positives for filters that were emitted then cleared
 *  but kept in the array with `value: []`). */
function isSourceFilterActive(
  filters: InteractiveFilter[],
  componentIndex: string,
  expectedSource: InteractiveFilter['source'],
): boolean {
  for (const f of filters) {
    if (f.index !== componentIndex) continue;
    if (f.source !== expectedSource) continue;
    const v = f.value;
    if (v == null) continue;
    if (Array.isArray(v) && v.length === 0) continue;
    return true;
  }
  return false;
}

const CardRenderer: React.FC<{
  metadata: StoredMetadata;
  value?: unknown;
  secondaryValues?: Record<string, unknown>;
  loading?: boolean;
  filterApplied: boolean;
}> = ({ metadata, value, secondaryValues, loading, filterApplied }) => {
  const displayValue =
    loading && value == null
      ? '…'
      : value != null
      ? formatValue(value)
      : '—';

  // Preserve the YAML-declared order; fall back to the keys returned by the
  // server. Drop the hero aggregation if it appears in the list (the API
  // already strips it but defend in depth).
  const aggregationOrder = (metadata.aggregations || Object.keys(secondaryValues || {})).filter(
    (a) => a && a !== metadata.aggregation,
  );
  const orderedSecondary = aggregationOrder
    .map((a) => ({ name: a, value: secondaryValues?.[a] }))
    .filter((row) => row.value !== undefined);

  // ``top_n`` / ``concentration`` layouts read their payload from the
  // synthetic ``__breakdown__`` key (server-populated when ``breakdown_col``
  // is bound). Inject it into the rows array — the renderer dispatches on
  // the row name, not on aggregation order.
  const breakdown = secondaryValues?.['__breakdown__'] as
    | {
        column: string;
        total: number;
        top: { name: string; count: number; percent: number }[];
        top_share: number;
        unique_values: number;
      }
    | undefined;
  if (breakdown !== undefined) {
    orderedSecondary.push({ name: '__breakdown__', value: breakdown });
  }

  // Aggregation description line — sits in the existing card slot just below
  // the hero value. We enrich it with breakdown info when available so the
  // "(Count)" line carries useful context (top-N share) without needing its
  // own dedicated row inside the secondary strip. Restructures vertical
  // density: instead of stacking ``(Count) / Top 3 cover 83% of N / bar 1 / …``
  // we get ``(Count · Top 3 = 83%) / bar 1 / …``.
  const aggDesc = (() => {
    if (!metadata.aggregation) return undefined;
    const base = `(${capitalize(metadata.aggregation)})`;
    const layout = metadata.secondary_layout;
    if (
      (layout === 'top_n' || layout === 'concentration') &&
      breakdown &&
      Array.isArray(breakdown.top) &&
      breakdown.top.length > 0
    ) {
      const share = Math.round((breakdown.top_share || 0) * 100);
      return `${base} · Top ${breakdown.top.length} = ${share}%`;
    }
    if (
      layout === 'coverage' &&
      typeof metadata.coverage_max === 'number' &&
      typeof value === 'number' &&
      metadata.coverage_max > 0
    ) {
      const pct = Math.round((value / (metadata.coverage_max as number)) * 100);
      return `${base} · ${pct}% of ${metadata.coverage_max}`;
    }
    return base;
  })();

  // While the next bulk-compute is in flight we keep the previous value
  // visible (App.tsx no longer clears `cardValues`), but slightly dim the
  // card to signal "refreshing". 0.6 opacity is enough to read as stale
  // without flicker. Brief transitions smooth out the dim/restore swing.
  const dimming = loading && value != null;
  return (
    <div
      style={{
        opacity: dimming ? 0.6 : 1,
        transition: 'opacity 120ms ease-out',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <DepictioCard
        title={metadata.title || inferCardTitle(metadata)}
        value={displayValue}
        icon_name={metadata.icon_name}
        icon_color={metadata.icon_color}
        title_color={metadata.title_color}
        background_color={metadata.background_color}
        title_font_size={metadata.title_font_size || 'md'}
        value_font_size={metadata.value_font_size || 'xl'}
        aggregation_description={aggDesc}
        filter_applied={filterApplied}
        secondaryStrip={
          // ``coverage`` layout doesn't rely on the secondary aggregations
          // array — it reads the card's hero ``value`` + the YAML-declared
          // ``coverage_max``. So even with empty ``orderedSecondary`` we
          // still render the strip when the coverage inputs are present.
          orderedSecondary.length > 0 ||
          (metadata.secondary_layout === 'coverage' &&
            typeof metadata.coverage_max === 'number') ? (
            <SecondaryMetrics
              rows={orderedSecondary}
              layout={
                (metadata.secondary_layout as
                  | 'vertical'
                  | 'compact'
                  | 'box_plot'
                  | 'top_n'
                  | 'coverage'
                  | 'concentration'
                  | undefined) || 'vertical'
              }
              color={
                (metadata.icon_color as string | undefined) ||
                (metadata.title_color as string | undefined) ||
                null
              }
              coverageValue={typeof value === 'number' ? value : null}
              coverageMax={
                typeof metadata.coverage_max === 'number'
                  ? (metadata.coverage_max as number)
                  : null
              }
            />
          ) : undefined
        }
      />
    </div>
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

interface AdvancedVizDispatchProps {
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  refreshTick?: number;
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
}

/**
 * Per-component sub-renderer for the advanced_viz family.
 *
 * Holds a useState for the Settings + Show-data popovers the framed renderer
 * publishes via AdvancedVizExtrasContext. The published JSX is appended to
 * the standard chrome icons (metadata + fullscreen + reset) via the
 * `extraActions` slot so all the action icons land in the same hover-revealed
 * row with matching Mantine styling.
 */
const AdvancedVizDispatch: React.FC<AdvancedVizDispatchProps> = ({
  metadata,
  filters,
  refreshTick,
  extraActions,
  showDragHandle,
}) => {
  const [publishedExtras, setPublishedExtras] = React.useState<React.ReactNode>(null);

  const vizKind = (metadata.viz_kind as string) || '';
  const advProps = { metadata, filters, refreshTick };
  let inner: React.ReactNode;
  if (vizKind === 'volcano') {
    inner = <VolcanoRenderer {...(advProps as any)} />;
  } else if (vizKind === 'embedding') {
    inner = <EmbeddingRenderer {...(advProps as any)} />;
  } else if (vizKind === 'manhattan') {
    inner = <ManhattanRenderer {...(advProps as any)} />;
  } else if (vizKind === 'stacked_taxonomy') {
    inner = <StackedTaxonomyRenderer {...(advProps as any)} />;
  } else if (vizKind === 'phylogenetic') {
    inner = <PhylogeneticRenderer {...(advProps as any)} />;
  } else if (vizKind === 'rarefaction') {
    inner = <RarefactionRenderer {...(advProps as any)} />;
  } else if (vizKind === 'da_barplot' || vizKind === 'ancombc_differentials') {
    // ancombc_differentials was collapsed into da_barplot — legacy persisted
    // dashboards still carry the old kind string and need the same renderer.
    inner = <DaBarplotRenderer {...(advProps as any)} />;
  } else if (vizKind === 'enrichment') {
    inner = <EnrichmentRenderer {...(advProps as any)} />;
  } else if (vizKind === 'complex_heatmap') {
    inner = <ComplexHeatmapRenderer {...(advProps as any)} />;
  } else if (vizKind === 'upset_plot') {
    inner = <UpsetRenderer {...(advProps as any)} />;
  } else if (vizKind === 'ma') {
    inner = <MARenderer {...(advProps as any)} />;
  } else if (vizKind === 'dot_plot') {
    inner = <DotPlotRenderer {...(advProps as any)} />;
  } else if (vizKind === 'lollipop') {
    inner = <LollipopRenderer {...(advProps as any)} />;
  } else if (vizKind === 'qq') {
    inner = <QQRenderer {...(advProps as any)} />;
  } else if (vizKind === 'sunburst') {
    inner = <SunburstRenderer {...(advProps as any)} />;
  } else if (vizKind === 'oncoplot') {
    inner = <OncoplotRenderer {...(advProps as any)} />;
  } else if (vizKind === 'coverage_track') {
    inner = <CoverageTrackRenderer {...(advProps as any)} />;
  } else if (vizKind === 'sankey') {
    inner = <SankeyRenderer {...(advProps as any)} />;
  } else {
    inner = (
      <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
        Unknown advanced viz kind: "{vizKind}"
      </div>
    );
  }

  const combinedExtras = publishedExtras || extraActions ? (
    <>
      {publishedExtras}
      {extraActions}
    </>
  ) : undefined;

  return wrapWithChrome(
    'advanced_viz',
    metadata,
    undefined,
    <AdvancedVizExtrasProvider onChange={setPublishedExtras}>{inner}</AdvancedVizExtrasProvider>,
    { extraActions: combinedExtras, showDragHandle },
  );
};
