import React, { useEffect, useMemo, useRef, useState } from 'react';
import GridLayout, { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { Box, Paper, Title, Stack, Text, Group, Button } from '@mantine/core';
import { Icon } from '@iconify/react';

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
  /** Clears every active filter. Header button is disabled when no filters exist. */
  onResetAllFilters?: () => void;
  onLeftLayoutChange: (newLayout: Layout[]) => void;
  editMode: boolean;
  onDeleteComponent: (componentId: string) => void;
  onDuplicateComponent?: (componentId: string) => void;
  /** Width to render the grid at — typically the panel's measured width. */
  width?: number;
  /** Pinned below the filter list, outside the scroll area. Deliberately an
   *  opaque node: the editor puts the docked map panel here, and this
   *  component has no business knowing that. */
  footer?: React.ReactNode;
}

// Compact filter rows: rowHeight=40 + 8px margin, so h=2 is 88 px per filter.
// Tighter than Dash's default 100 px so more filters fit without scrolling.
const ROW_HEIGHT = 40;
const DEFAULT_H = 2;

/** Rows a control needs.
 *
 *  Heights are forced here rather than read from the saved layout (the panel is
 *  not resizable), so this is the one place that decides how tall a filter is.
 *  Two rows fit a title plus an input; a slider showing tick marks needs a
 *  third, because its labels hang below the track and the grid item clips
 *  anything past its own height — which is why sliders used to lose their
 *  scale in the panel while the same control looked fine in the grid. */
function rowsFor(component: StoredMetadata): number {
  const type = component.interactive_component_type;
  if (type !== 'Slider' && type !== 'RangeSlider') return DEFAULT_H;
  return component.show_marks === false ? DEFAULT_H : DEFAULT_H + 1;
}

function normalizeLeftLayout(
  components: StoredMetadata[],
  layoutData: unknown,
): Layout[] {
  const items = extractLayoutItems(layoutData);
  const byIndex = new Map(components.map((c) => [c.index, c]));
  const matched = items
    .map((it) => ({ ...it, i: stripBoxPrefix(it.i) }))
    .filter((it) => byIndex.has(it.i))
    .map((it) => ({ ...it, w: 1, h: rowsFor(byIndex.get(it.i)!) }));

  const seen = new Set(matched.map((it) => it.i));
  // Stack the unplaced ones below everything already positioned. `y` only has
  // to order them — `compactType: 'vertical'` closes the gaps left by the
  // varying heights above.
  const usedRows = matched.reduce((sum, it) => sum + it.h, 0);
  let cursor = usedRows;
  const fallback = components
    .filter((c) => !seen.has(c.index))
    .map((c) => {
      const h = rowsFor(c);
      const item = { i: c.index, x: 0, y: cursor, w: 1, h };
      cursor += h;
      return item;
    });
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
  onResetAllFilters,
  onLeftLayoutChange,
  editMode,
  onDeleteComponent,
  onDuplicateComponent,
  width,
  footer,
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
    // Flex column, and the scroll boundary sits on the filter list inside it
    // rather than on the caller's wrapper — that is what lets `footer` stay
    // pinned to the bottom while a long filter list scrolls past it.
    <Paper
      p="md"
      withBorder
      radius="md"
      style={{
        height: '100%',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
      data-tour-id="filter-panel"
    >
      <Group
        justify="space-between"
        align="center"
        mb="sm"
        wrap="nowrap"
        style={{ flexShrink: 0 }}
      >
        <Title order={5}>Filters</Title>
        {onResetAllFilters && (
          <Button
            leftSection={<Icon icon="bx:reset" width={12} />}
            color="orange"
            // Filled only while there is something to reset, mirroring the
            // per-component ResetButton in the chrome: a permanently filled
            // orange button reads as an alert on a panel that is otherwise
            // quiet, which is most of the time.
            variant={filters.length > 0 ? 'filled' : 'light'}
            size="xs"
            onClick={onResetAllFilters}
            disabled={filters.length === 0}
          >
            Reset all
          </Button>
        )}
      </Group>
      <Box
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          overflowX: 'hidden',
          // Reserve the scrollbar's width. Without it, the scrollbar
          // appearing changes the content width, which feeds the
          // ResizeObserver below → grid reflow → height change → scrollbar
          // toggles again.
          scrollbarGutter: 'stable',
        }}
      >
      {interactiveComponents.length === 0 ? (
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            No interactive components.
          </Text>
        </Stack>
      ) : (
        <div
          ref={wrapperRef}
          // Mirror the marker classes DashboardGrid sets on its own root so
          // the global edit-mode CSS rules (visible Paper border in editor,
          // borderless in viewer — see styles/app.css) apply here too. The
          // left panel uses its own GridLayout, not DashboardGrid, so we
          // have to opt in manually.
          className={
            'depictio-dashboard-grid' + (editMode ? ' depictio-edit-mode' : '')
          }
          style={{ width: '100%', overflowX: 'hidden' }}
        >
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
      </Box>
      {footer}
    </Paper>
  );
};

export default LeftFilterPanel;
