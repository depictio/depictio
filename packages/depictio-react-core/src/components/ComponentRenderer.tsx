import React, { lazy, Suspense, useRef } from 'react';
import { DepictioCard } from 'depictio-components';
import type { GridApi } from 'ag-grid-community';

import { InteractiveFilter, StoredMetadata } from '../api';
import ImageRenderer from './ImageRenderer';
import TextRenderer from './TextRenderer';
import LazyMount, { CellPlaceholder } from './LazyMount';
import MultiSelectRenderer from './interactive/MultiSelectRenderer';
import RangeSliderRenderer from './interactive/RangeSliderRenderer';
import SliderRenderer from './interactive/SliderRenderer';
import DatePickerRenderer from './interactive/DatePickerRenderer';
import CheckboxSwitchRenderer from './interactive/CheckboxSwitchRenderer';
import SegmentedControlRenderer from './interactive/SegmentedControlRenderer';
import TimelineRenderer from './interactive/TimelineRenderer';
import SecondaryMetrics, {
  NUMERIC_LAYOUTS,
  type SecondaryLayout,
} from './card/SecondaryMetrics';
import { wrapWithChrome } from './chrome';
import LoadAllButton, { LoadAllState } from './chrome/LoadAllButton';
import MapDataButton from './map/MapDataButton';
import { isMapSelectionEnabled } from '../selection';
import { ActiveHighlight } from '../highlight';

// Heavy renderers are lazy-loaded so plotly / ag-grid / jbrowse resolve into
// their own async chunks (see `manualChunks` in depictio/viewer/vite.config.ts)
// instead of the entry bundle. A dashboard that uses none of them never parses
// them, and first paint no longer blocks on the whole visualisation stack.
// `figure` / `table` / `multiqc` already gate their own data fetch via an
// internal `useInView`, so they just need the Suspense chunk boundary; the
// branches that fetch on mount (`advanced_viz`, `jbrowse`) are additionally
// viewport-gated with `LazyMount`. The whole advanced_viz family (its ~17
// renderers + the ag-grid its data popover pulls in) collapses into one chunk
// behind `AdvancedVizDispatch`.
const FigureRenderer = lazy(() => import('./FigureRenderer'));
const TableRenderer = lazy(() => import('./TableRenderer'));
const MapRenderer = lazy(() => import('./MapRenderer'));
const JBrowseRenderer = lazy(() => import('./JBrowseRenderer'));
const MultiQCRenderer = lazy(() => import('./MultiQCRenderer'));
const AdvancedVizDispatch = lazy(() => import('./advanced_viz/AdvancedVizDispatch'));

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
  /** Batch currently highlighted; renderers glow its rows when the DC matches. */
  activeHighlight?: ActiveHighlight | null;
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
  activeHighlight,
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
        <MultiSelectRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
          compact={compact}
        />
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
        <DatePickerRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
          compact={compact}
        />
      );
    } else if (subType === 'Checkbox' || subType === 'Switch') {
      inner = (
        <CheckboxSwitchRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
          compact={compact}
        />
      );
    } else if (subType === 'SegmentedControl') {
      inner = (
        <SegmentedControlRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
          compact={compact}
        />
      );
    } else if (subType === 'Timeline') {
      inner = (
        <TimelineRenderer
          metadata={metadata}
          filters={filters}
          onChange={onFilterChange}
          compact={compact}
          refreshTick={refreshTick}
        />
      );
    } else {
      inner = (
        <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
          Interactive type "{subType}" not yet ported to the React viewer.
        </div>
      );
    }
    // Reset button is "active" (enabled, filled orange) when THIS interactive
    // component has sourced a non-empty filter. Interactive components emit
    // with no `source` discriminator (only chart/table selections use one),
    // so the active check matches on `index` + empty-value semantics.
    const sourceFilterActive = isSourceFilterActive(filters, metadata.index, undefined);
    return wrapWithChrome('interactive', metadata, undefined, inner, { onResetFilter, extraActions, showDragHandle, sourceFilterActive });
  }

  if (metadata.component_type === 'figure' && dashboardId) {
    return (
      <FigureBlock
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
        activeHighlight={activeHighlight}
        extraActions={extraActions}
        showDragHandle={showDragHandle}
      />
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
        activeHighlight={activeHighlight}
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
        activeHighlight={activeHighlight}
      />,
      { onResetFilter: onResetSelection, extraActions, showDragHandle, sourceFilterActive },
    );
  }

  if (metadata.component_type === 'map' && dashboardId) {
    const selectionEnabled = isMapSelectionEnabled(metadata, !!onFilterChange);
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
    // Same "show underlying data" affordance advanced_viz has, riding the same
    // `extraActions` slot — so `actionsFor('map')` needs no change.
    const mapExtras = (
      <>
        {extraActions}
        <MapDataButton
          dashboardId={dashboardId}
          metadata={metadata}
          filters={filters}
          onFilterChange={onFilterChange}
        />
      </>
    );
    return wrapWithChrome(
      'map',
      metadata,
      undefined,
      <Suspense fallback={<CellPlaceholder />}>
        <MapRenderer
          dashboardId={dashboardId}
          metadata={metadata}
          filters={filters}
          onFilterChange={onFilterChange}
          refreshTick={refreshTick}
        />
      </Suspense>,
      {
        onResetFilter: onResetSelection,
        extraActions: mapExtras,
        showDragHandle,
        sourceFilterActive,
      },
    );
  }

  if (metadata.component_type === 'jbrowse' && dashboardId) {
    // JBrowse fetches its session on mount and pulls a heavy chunk, so gate the
    // whole thing on the viewport — off-screen tracks neither fetch nor load
    // their code until scrolled near. Chrome stays *outside* the gate (as for
    // multiqc) so a deferred panel still shows its card border and title rather
    // than a bare unframed shimmer.
    return wrapWithChrome(
      'jbrowse',
      metadata,
      undefined,
      <LazyMount>
        <JBrowseRenderer
          dashboardId={dashboardId}
          metadata={metadata}
          filters={filters}
          refreshTick={refreshTick}
        />
      </LazyMount>,
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
    // LazyMount (viewport gate + Suspense boundary) so far-below-the-fold MultiQC
    // panels defer their chunk load + mount until nearly visible — matching
    // advanced_viz/jbrowse. The renderer also gates its own fetch via useInView,
    // but LazyMount additionally spares the eager react-plotly chunk mount on a
    // dense (e.g. 42-panel) dashboard.
    return wrapWithChrome(
      'multiqc',
      metadata,
      undefined,
      <LazyMount>
        <MultiQCRenderer
          dashboardId={dashboardId}
          metadata={metadata}
          filters={filters}
          refreshTick={refreshTick}
        />
      </LazyMount>,
      { extraActions, showDragHandle },
    );
  }

  if (metadata.component_type === 'advanced_viz') {
    // Every advanced_viz renderer fires its data fetch on mount. Gate on the
    // viewport so a 25–30 component dashboard doesn't enqueue all ~30 at once
    // (and never fetches for panels the user scrolls past). LazyMount also
    // supplies the Suspense boundary for the lazily-loaded dispatch chunk.
    // Unlike jbrowse/multiqc the chrome can't be hoisted outside the gate here:
    // AdvancedVizDispatch owns the wrapWithChrome call because the chrome's
    // extraActions come from the renderer's own popovers, and that whole module
    // is the lazy chunk. A deferred panel therefore shows a bare skeleton.
    return (
      <LazyMount>
        <AdvancedVizDispatch
          metadata={metadata}
          filters={filters}
          refreshTick={refreshTick}
          extraActions={extraActions}
          showDragHandle={showDragHandle}
        />
      </LazyMount>
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
  activeHighlight?: ActiveHighlight | null;
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
}> = ({
  dashboardId,
  metadata,
  filters,
  onFilterChange,
  refreshTick,
  activeHighlight,
  extraActions,
  showDragHandle,
}) => {
  const agGridApiRef = useRef<GridApi | null>(null);
  const [loadAllState, setLoadAllState] = React.useState<LoadAllState | null>(null);
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
  const combinedExtras =
    loadAllState || extraActions ? (
      <>
        {loadAllState && <LoadAllButton state={loadAllState} />}
        {extraActions}
      </>
    ) : undefined;
  return wrapWithChrome(
    'table',
    metadata,
    undefined,
    <Suspense fallback={<CellPlaceholder variant="table" />}>
      <TableRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        agGridApiRef={agGridApiRef}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
        activeHighlight={activeHighlight}
        onLoadAllState={setLoadAllState}
      />
    </Suspense>,
    {
      agGridApiRef,
      onResetFilter: onResetSelection,
      extraActions: combinedExtras,
      showDragHandle,
      sourceFilterActive,
    },
  );
};

const FigureBlock: React.FC<{
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  refreshTick?: number;
  activeHighlight?: ActiveHighlight | null;
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
}> = ({
  dashboardId,
  metadata,
  filters,
  onFilterChange,
  refreshTick,
  activeHighlight,
  extraActions,
  showDragHandle,
}) => {
  const [loadAllState, setLoadAllState] = React.useState<LoadAllState | null>(null);
  // Only scatter / scatter_3d traces carry the per-row customdata we need for
  // meaningful cross-filter selection. Aggregated visus (histogram, box, bar,
  // pie, …) would emit per-bin envelopes — hide the reset affordance there so
  // chrome stays clean.
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
  const combinedExtras =
    loadAllState || extraActions ? (
      <>
        {loadAllState && <LoadAllButton state={loadAllState} />}
        {extraActions}
      </>
    ) : undefined;
  return wrapWithChrome(
    'figure',
    metadata,
    undefined,
    <Suspense fallback={<CellPlaceholder />}>
      <FigureRenderer
        dashboardId={dashboardId}
        metadata={metadata}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
        activeHighlight={activeHighlight}
        onLoadAllState={setLoadAllState}
      />
    </Suspense>,
    { onResetFilter: onResetSelection, extraActions: combinedExtras, showDragHandle, sourceFilterActive },
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

  // Numeric / QC layouts read their own ``__<layout>__`` key, populated by the
  // same bulk-compute pass. Injected the same way, since the strip dispatches
  // on the row name rather than on aggregation order.
  for (const key of NUMERIC_LAYOUTS) {
    const payload = secondaryValues?.[`__${key}__`];
    if (payload !== undefined && payload !== null) {
      orderedSecondary.push({ name: `__${key}__`, value: payload });
    }
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
      (layout === 'coverage' || layout === 'gauge') &&
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
          // ``coverage`` and ``gauge`` don't rely on the secondary aggregations
          // array — they read the card's hero ``value`` + the YAML-declared
          // ``coverage_max``. So even with empty ``orderedSecondary`` we
          // still render the strip when those inputs are present.
          orderedSecondary.length > 0 ||
          ((metadata.secondary_layout === 'coverage' ||
            metadata.secondary_layout === 'gauge') &&
            typeof metadata.coverage_max === 'number') ? (
            <SecondaryMetrics
              rows={orderedSecondary}
              layout={
                // Cast through the renderer's own exported union rather than
                // respelling it here — an inline copy silently drops any layout
                // added later, which is how a new one renders as `vertical`.
                (metadata.secondary_layout as SecondaryLayout | undefined) || 'vertical'
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

/** Exported so the dashboard grid can label a collapsed section's summary
 *  chips exactly the way the cards themselves are labelled. */
export function inferCardTitle(m: StoredMetadata): string {
  if (m.aggregation && m.column_name) {
    return `${capitalize(String(m.aggregation))} of ${m.column_name}`;
  }
  return String(m.column_name || 'Metric');
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Exported alongside `inferCardTitle`, and for the same reason. */
export function formatValue(v: unknown): string | number {
  if (typeof v === 'number') {
    if (!Number.isInteger(v)) return v.toFixed(4).replace(/\.?0+$/, '');
    return v;
  }
  return String(v);
}
