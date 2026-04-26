import React, { useEffect, useRef, useState } from 'react';
import GridLayout, { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

import { StoredMetadata, InteractiveFilter } from '../api';
import ComponentRenderer from './ComponentRenderer';

interface DashboardGridProps {
  dashboardId: string;
  metadataList: StoredMetadata[];
  layoutData?: unknown;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Precomputed card values keyed by component index. */
  cardValues?: Record<string, unknown>;
  /** True while the bulk compute is pending. */
  cardValuesLoading?: boolean;
  /** Allow users to drag grid items. Defaults to false (viewer-safe). */
  isDraggable?: boolean;
  /** Allow users to resize grid items. Defaults to false (viewer-safe). */
  isResizable?: boolean;
  /** Whether the grid is being used in edit mode. Drives overlay rendering. */
  editMode?: boolean;
  /**
   * Fired on every drag/resize end. Only meaningful when `isDraggable` or
   * `isResizable` is true. We forward whatever react-grid-layout emits.
   */
  onLayoutChange?: (newLayout: Layout[]) => void;
  /**
   * Optional per-cell overlay renderer. When `editMode` is true and this
   * callback is provided, the returned node is rendered absolutely positioned
   * in the top-right of each grid cell (above the component content).
   */
  renderItemOverlay?: (
    componentId: string,
    metadata: StoredMetadata,
  ) => React.ReactNode;
}

/**
 * Renders the dashboard component tree inside react-grid-layout. Depictio's
 * stored_layout_data uses dash-dynamic-grid-layout's format, which is a thin
 * wrapper over react-grid-layout — same {i, x, y, w, h} shape works directly.
 *
 * When stored_layout_data is absent, components are auto-placed in a 2-column
 * flow to give the viewer SOMETHING reasonable (matches Dash's fallback).
 *
 * By default the grid is purely read-only (no drag, no resize, no overlay).
 * Editor callers opt in via `isDraggable` / `isResizable` / `editMode` /
 * `renderItemOverlay`.
 */
const DashboardGrid: React.FC<DashboardGridProps> = ({
  dashboardId,
  metadataList,
  layoutData,
  filters,
  onFilterChange,
  cardValues,
  cardValuesLoading,
  isDraggable = false,
  isResizable = false,
  editMode = false,
  onLayoutChange,
  renderItemOverlay,
}) => {
  const layouts = normalizeLayout(metadataList, layoutData, isDraggable || isResizable);

  // Measure our own container so the grid never overflows the parent pane.
  // Falls back to viewport width on first render before the ResizeObserver
  // fires (single frame, harmless).
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState<number>(() =>
    typeof window !== 'undefined' ? window.innerWidth - 40 : 1200,
  );
  useEffect(() => {
    if (!wrapperRef.current || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (next && next > 0) setContainerWidth(Math.floor(next));
    });
    ro.observe(wrapperRef.current);
    return () => ro.disconnect();
  }, []);

  const showOverlays = editMode && typeof renderItemOverlay === 'function';
  const rootClass =
    'depictio-dashboard-grid' + (editMode ? ' depictio-edit-mode' : '');

  return (
    <div
      ref={wrapperRef}
      className={rootClass}
      style={{ width: '100%', overflowX: 'hidden' }}
    >
    <GridLayout
      className="layout"
      layout={layouts}
      cols={8}
      rowHeight={100}
      width={containerWidth}
      margin={[12, 12]}
      containerPadding={[0, 0]}
      isDraggable={isDraggable}
      isResizable={isResizable}
      compactType="vertical"
      onLayoutChange={onLayoutChange}
      // Drag is gated to a dedicated handle (see ComponentChrome's
      // `react-grid-dragHandle` action). Cells themselves are NOT draggable
      // — the user can interact with content (Plotly modebar, AG Grid
      // selectors, etc.) without accidentally starting a drag.
      draggableHandle=".react-grid-dragHandle"
      resizeHandles={['s', 'e', 'w', 'n', 'sw', 'se', 'nw', 'ne']}
    >
      {metadataList.map((m) => (
        <div
          key={m.index}
          style={{
            overflow: 'hidden',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <ComponentRenderer
            dashboardId={dashboardId}
            metadata={m}
            filters={filters}
            onFilterChange={onFilterChange}
            cardValue={cardValues?.[m.index]}
            cardLoading={cardValuesLoading}
            extraActions={showOverlays ? renderItemOverlay!(m.index, m) : undefined}
            showDragHandle={editMode && isDraggable}
          />
        </div>
      ))}
    </GridLayout>
    </div>
  );
};

export default DashboardGrid;

function normalizeLayout(
  metadataList: StoredMetadata[],
  layoutData: unknown,
  interactive: boolean,
): Layout[] {
  // Dash stores layouts as a list of { i: "box-<index>", x, y, w, h } OR as
  // { breakpoint: [...] } keyed dict. Try both shapes.
  const items = extractLayoutItems(layoutData);
  const indexSet = new Set(metadataList.map((m) => m.index));
  // Always override `static` based on the interactive flag — legacy
  // dash-dynamic-grid-layout entries can have static:true baked in, which
  // would lock items even when the editor caller asked for drag/resize.
  // Also clamp w/x into the 8-col grid: positions saved by an earlier React
  // editor pass (when we briefly used cols=12) would be off-grid otherwise
  // and react-grid-layout would stack everything at y=0.
  const COLS = 8;
  const matched = items
    .map((it) => {
      const w = Math.max(1, Math.min(it.w ?? 1, COLS));
      const x = Math.max(0, Math.min(it.x ?? 0, COLS - w));
      const h = Math.max(1, it.h ?? 1);
      const y = Math.max(0, it.y ?? 0);
      return {
        ...it,
        i: stripBoxPrefix(it.i),
        x,
        y,
        w,
        h,
        static: !interactive,
      };
    })
    .filter((it) => indexSet.has(it.i));
  const matchedIds = new Set(matched.map((it) => it.i));

  // Place missing items (e.g. cards never recorded in right_panel_layout_data)
  // immediately below the lowest existing row in a 2-column auto-flow. We
  // never mark items `static: true` when the grid is interactive — that would
  // lock them in place even though the caller asked for editing.
  const baselineY = matched.reduce(
    (max, it) => Math.max(max, (it.y ?? 0) + (it.h ?? 4)),
    0,
  );
  const missing = metadataList.filter((m) => !matchedIds.has(m.index));
  const missingLayout = missing.map((m, idx) => {
    // Defaults mirror depictio/dash/component_metadata.py:DUAL_PANEL_DIMENSIONS
    // (8-col grid, rowHeight=100). Card 25% width, figure 50%, table/map/image
    // full row.
    const dims = defaultDimsFor(m.component_type);
    const colsPerRow = Math.max(1, Math.floor(8 / dims.w));
    return {
      i: m.index,
      x: (idx % colsPerRow) * dims.w,
      y: baselineY + Math.floor(idx / colsPerRow) * dims.h,
      w: dims.w,
      h: dims.h,
      static: !interactive,
    };
  });

  if (matched.length === 0 && missingLayout.length === 0) return [];
  return [...matched, ...missingLayout];
}

/** Default w/h per component_type — mirrors Dash's DUAL_PANEL_DIMENSIONS. */
function defaultDimsFor(componentType: string | undefined): { w: number; h: number } {
  switch (componentType) {
    case 'card':
      return { w: 2, h: 2 };
    case 'figure':
    case 'multiqc':
      return { w: 4, h: 4 };
    case 'table':
      return { w: 8, h: 6 };
    case 'map':
      return { w: 8, h: 6 };
    case 'image':
      return { w: 8, h: 7 };
    case 'jbrowse':
      return { w: 8, h: 6 };
    default:
      return { w: 4, h: 4 };
  }
}

function extractLayoutItems(layoutData: unknown): Layout[] {
  if (!layoutData) return [];
  if (Array.isArray(layoutData)) {
    return layoutData.filter(
      (i): i is Layout =>
        i && typeof i === 'object' && 'i' in i && 'x' in i && 'y' in i,
    );
  }
  if (typeof layoutData === 'object') {
    // dict keyed by breakpoint — take 'lg' or the first key
    const obj = layoutData as Record<string, unknown>;
    const candidateKey =
      'lg' in obj
        ? 'lg'
        : Object.keys(obj).find((k) => Array.isArray(obj[k])) || '';
    if (candidateKey && Array.isArray(obj[candidateKey])) {
      return (obj[candidateKey] as Layout[]).filter(
        (i) => i && typeof i === 'object' && 'i' in i,
      );
    }
  }
  return [];
}

function stripBoxPrefix(id: string): string {
  return id.startsWith('box-') ? id.slice(4) : id;
}
