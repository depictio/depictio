import React, { useEffect, useMemo, useRef, useState } from 'react';
import GridLayout, { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { Paper, Title, Stack, Text } from '@mantine/core';

import { ComponentRenderer } from 'depictio-react-core';
import type {
  StoredMetadata,
  InteractiveFilter,
} from 'depictio-react-core';

import GridItemEditOverlay from './GridItemEditOverlay';

/**
 * Renders the dashboard's interactive components inside a single-column
 * `react-grid-layout` so the user can re-order them. Resizing is disabled —
 * filters always span the full panel width.
 *
 * Layout source-of-truth is `DashboardData.left_panel_layout_data`. On any
 * drag, we hand the new layout array back to the parent via
 * `onLeftLayoutChange` so it can persist via /save/{id}.
 */
interface LeftFilterPanelProps {
  dashboardId: string;
  interactiveComponents: StoredMetadata[];
  layoutData: unknown;
  filters: InteractiveFilter[];
  onFilterChange: (filter: InteractiveFilter) => void;
  onLeftLayoutChange: (newLayout: Layout[]) => void;
  editMode: boolean;
  onDeleteComponent: (componentId: string) => void;
  onDuplicateComponent?: (componentId: string) => void;
  /** Width to render the grid at — typically the panel's measured width. */
  width?: number;
}

// Compact filter rows: rowHeight=40, h=2 → 80 px per filter. Tighter than
// Dash's default 100 px so more filters fit without scrolling. All
// interactive components — including DateRangePicker — share the same
// height for visual uniformity in the panel.
const ROW_HEIGHT = 40;
const DEFAULT_H = 2;

function normalizeLeftLayout(
  components: StoredMetadata[],
  layoutData: unknown,
): Layout[] {
  const items = extractLayoutItems(layoutData);
  const indexSet = new Set(components.map((c) => c.index));
  const matched = items
    .map((it) => ({ ...it, i: stripBoxPrefix(it.i), w: 1, h: DEFAULT_H }))
    .filter((it) => indexSet.has(it.i));

  const seen = new Set(matched.map((it) => it.i));
  const fallback = components
    .filter((c) => !seen.has(c.index))
    .map((c, idx) => ({
      i: c.index,
      x: 0,
      y: (matched.length + idx) * DEFAULT_H,
      w: 1,
      h: DEFAULT_H,
    }));
  return [...matched, ...fallback];
}

function extractLayoutItems(layoutData: unknown): Layout[] {
  if (!layoutData) return [];
  if (Array.isArray(layoutData)) {
    return layoutData.filter(
      (i): i is Layout =>
        Boolean(i) && typeof i === 'object' && 'i' in i && 'x' in i && 'y' in i,
    );
  }
  if (typeof layoutData === 'object') {
    const obj = layoutData as Record<string, unknown>;
    const candidateKey =
      'lg' in obj
        ? 'lg'
        : Object.keys(obj).find((k) => Array.isArray(obj[k])) || '';
    if (candidateKey && Array.isArray(obj[candidateKey])) {
      return (obj[candidateKey] as Layout[]).filter(
        (i) => Boolean(i) && typeof i === 'object' && 'i' in i,
      );
    }
  }
  return [];
}

function stripBoxPrefix(id: string): string {
  return id.startsWith('box-') ? id.slice(4) : id;
}

const LeftFilterPanel: React.FC<LeftFilterPanelProps> = ({
  dashboardId,
  interactiveComponents,
  layoutData,
  filters,
  onFilterChange,
  onLeftLayoutChange,
  editMode,
  onDeleteComponent,
  onDuplicateComponent,
  width,
}) => {
  const layout = useMemo(
    () => normalizeLeftLayout(interactiveComponents, layoutData),
    [interactiveComponents, layoutData],
  );

  // Self-measure to avoid horizontal overflow into the right panel when the
  // pane is narrower than `window.innerWidth * 0.28`.
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [measuredWidth, setMeasuredWidth] = useState<number>(() =>
    width && width > 0 ? width : 280,
  );
  useEffect(() => {
    if (!wrapperRef.current || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (next && next > 0) setMeasuredWidth(Math.floor(next));
    });
    ro.observe(wrapperRef.current);
    return () => ro.disconnect();
  }, []);

  return (
    <Paper
      p="md"
      withBorder
      radius="md"
      style={{ height: '100%', overflow: 'hidden' }}
      data-tour-id="filter-panel"
    >
      <Title order={5} mb="sm">
        Filters
      </Title>
      {interactiveComponents.length === 0 ? (
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            No interactive components.
          </Text>
        </Stack>
      ) : (
        <div ref={wrapperRef} style={{ width: '100%', overflowX: 'hidden' }}>
        <GridLayout
          className="layout left-filter-grid"
          layout={layout}
          cols={1}
          rowHeight={ROW_HEIGHT}
          width={measuredWidth}
          margin={[8, 8]}
          containerPadding={[0, 0]}
          isDraggable={editMode}
          isResizable={false}
          compactType="vertical"
          onLayoutChange={(newLayout) => onLeftLayoutChange(newLayout)}
          draggableHandle=".react-grid-dragHandle"
        >
          {interactiveComponents.map((m) => (
            <div
              key={m.index}
              data-component-id={m.index}
              style={{ overflow: 'hidden', height: '100%', display: 'flex', flexDirection: 'column' }}
            >
              <ComponentRenderer
                metadata={m}
                filters={filters}
                onFilterChange={onFilterChange}
                showDragHandle={editMode}
                extraActions={
                  editMode ? (
                    <GridItemEditOverlay
                      dashboardId={dashboardId}
                      componentId={m.index}
                      editMode={editMode}
                      onDelete={onDeleteComponent}
                      onDuplicate={onDuplicateComponent}
                      componentType={m.component_type}
                    />
                  ) : undefined
                }
              />
            </div>
          ))}
        </GridLayout>
        </div>
      )}
    </Paper>
  );
};

export default LeftFilterPanel;
