import React, { Suspense, lazy, useEffect, useState } from 'react';
import { ActionIcon, Badge, Box, Center, Group, Loader, Tabs, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter } from '../../api';
import { isMapSelectionEnabled, mapSelectionValues } from '../../selection';
import MapDataButton from '../map/MapDataButton';
import type { DragHandleProps } from './useDraggable';
import type { MapPanel } from './useMapPanel';

// Both shells are imported eagerly by the viewer and the editor — they have to
// be, since each decides for itself whether to render — so a static import here
// would put plotly (~1.4MB gzipped) on the boot path of every dashboard,
// including the ones with no map at all. Every other plotly renderer is behind
// `lazy()` in `ComponentRenderer` for exactly this reason. The chunk resolves
// when a panel first shows a map, and never on a dashboard without one.
const MapRenderer = lazy(() => import('../MapRenderer'));

/**
 * When to nudge Plotly after a mode or size change.
 *
 * Docking, undocking or resizing the card changes the map's container without
 * a window resize, and Plotly's `useResizeHandler` listens to the WINDOW —
 * so without this the map keeps its previous pixel size and sits clipped in
 * its new box. The layout also re-fits a frame or two after the box itself
 * settles, hence a short series rather than a single nudge. `DashboardGrid`
 * does the same during the sidebar slide. (Dragging the dock's edge nudges
 * Plotly per frame of its own — see `useDockResize`.)
 *
 * Plain timers rather than `requestAnimationFrame`: rAF is suspended while the
 * browser tab is not painting, which would leave a docked map blank until the
 * next unrelated resize.
 */
const PANEL_SETTLE_STEPS_MS = [0, 60, 140, 220];

/** One size and one glyph size for every action in the header, matching the
 *  component chrome (`ComponentChrome`) so the panel's controls read as the
 *  same family of buttons as the ones on a grid-placed component. */
const ACTION_SIZE = 'sm' as const;
const GLYPH = 16;

export interface MapPanelBodyProps {
  panel: MapPanel;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  refreshTick?: number;
  /** Which shell is hosting this body. Only affects presentation: the docked
   *  shell has nowhere to be dragged to, and sizes its map differently. */
  variant: 'floating' | 'docked';
  /** Drag handle props from `useDraggable`, for the floating shell's header. */
  dragHandleProps?: DragHandleProps;
  dragging?: boolean;
  /**
   * Editor chrome for the map currently on screen — omit outside the editor.
   *
   * A render prop rather than a node, because only the panel knows which of a
   * family's maps is showing, and only the host knows what editing one means:
   * this package has no business knowing the editor's routes or its save path.
   * Same shape as `DashboardGrid`'s `renderItemOverlay`, which is where a
   * grid-placed component gets the identical menu.
   *
   * `ownerDashboardId` is the tab the map was authored on, which is not always
   * the tab being edited — a floating map is shown from all of them.
   */
  renderEditActions?: (componentId: string, ownerDashboardId: string) => React.ReactNode;
}

/**
 * Everything inside the map panel that is not positioning.
 *
 * The panel has two shells — a draggable card over the dashboard
 * (`MapPanelSurface`) and a column pinned under the filter panel
 * (`MapPanelDock`) — and they show exactly the same thing: a header, a tab
 * strip when the dashboard has more than one floating map, the map, and a
 * selection footer. Keeping that here is what stops the two shells drifting
 * apart.
 */
const MapPanelBody: React.FC<MapPanelBodyProps> = ({
  panel,
  filters,
  onFilterChange,
  refreshTick,
  variant,
  dragHandleProps,
  dragging = false,
  renderEditActions,
}) => {
  const {
    components,
    state,
    setMode,
    setCardSize,
    setDockCollapsed,
    setLegendHidden,
    activeIndex,
    setActiveIndex,
  } = panel;
  const docked = variant === 'docked';
  // Folded down to the title bar. Docked only: the floating card can be put
  // away with Hide, and a title bar floating over the dashboard on its own
  // would be a scrap of chrome with nothing under it.
  const collapsed = docked && state.dockCollapsed;

  // Whether this map's figure has a legend or colour bar at all. Reported by
  // the renderer, which is the only thing that has seen the figure — a map with
  // a single undifferentiated trace has nothing to toggle, and an inert button
  // is worse than no button on a header this narrow.
  const [legendPresent, setLegendPresent] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const timers = PANEL_SETTLE_STEPS_MS.map((delay) =>
      window.setTimeout(() => window.dispatchEvent(new Event('resize')), delay),
    );
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [state.mode, state.cardSize, collapsed]);

  const active = components.find((c) => c.metadata.index === activeIndex) ?? components[0];
  if (!active) return null;

  const selected = mapSelectionValues(filters, active.metadata.index);
  const selectionEnabled = isMapSelectionEnabled(active.metadata, Boolean(onFilterChange));

  const clearSelection = () =>
    onFilterChange?.({ index: active.metadata.index, value: [], source: 'map_selection' });

  return (
    <>
      <Group
        // The docked panel has nowhere to be dragged to, so its header is a
        // plain title bar.
        {...(docked ? {} : dragHandleProps)}
        gap="xs"
        wrap="nowrap"
        px="xs"
        py={6}
        style={{
          cursor: docked ? 'default' : dragging ? 'grabbing' : 'grab',
          // Collapsed, this row *is* the dock and sits flush with the bottom of
          // the filter panel, so its underline would double the Paper's border.
          borderBottom: collapsed ? undefined : '1px solid var(--mantine-color-default-border)',
          touchAction: 'none',
          userSelect: 'none',
          flexShrink: 0,
        }}
      >
        {/* The floating card needs to say what it is; the dock is already
            unmistakably a map sitting under the filters, and its header is the
            narrowest thing on the page — every pixel goes to the title. Folded
            down, though, the row has to carry that on its own. */}
        {(!docked || collapsed) && <Icon icon="mdi:map-marker-multiple" width={GLYPH} />}
        <Text size="sm" fw={600} truncate style={{ flex: 1, minWidth: 0 }}>
          {(active.metadata.title as string) || 'Map'}
        </Text>
        {selected.length > 0 && (
          <Group gap={4} wrap="nowrap" data-no-drag>
            <Badge size="sm" variant="light" color="orange">
              {selected.length} selected
            </Badge>
            {/* Sits with the count rather than in a footer: the count is what
                tells you a filter is live, so the way out belongs beside it. */}
            <Tooltip label="Clear map selection" withinPortal>
              <ActionIcon
                variant="filled"
                color="orange"
                size="xs"
                aria-label="Clear map selection"
                onClick={clearSelection}
              >
                <Icon icon="bx:reset" width={12} />
              </ActionIcon>
            </Tooltip>
          </Group>
        )}
        <Group gap={4} wrap="nowrap" data-no-drag>
          {/* First, and set apart from the rest: everything after it changes how
              the panel is presented to *you*, while this edits or deletes the
              component itself. Lifting a map into the panel takes it out of the
              grid, and the grid overlay is otherwise the only way to reach
              those actions. */}
          {!collapsed && renderEditActions?.(active.metadata.index, active.dashboard_id)}
          {/* Folded down, the row keeps only what still acts on something: the
              map's own controls would be operating on a map nobody can see. */}
          {!collapsed && (
            /* The owning tab's id, not the one on screen — a floating map is
               authored on one tab and shown on all of them. */
            <MapDataButton
              dashboardId={active.dashboard_id}
              metadata={active.metadata}
              filters={filters}
              onFilterChange={onFilterChange}
            />
          )}
          {legendPresent && !collapsed && (
            <Tooltip label={state.legendHidden ? 'Show legend' : 'Hide legend'} withinPortal>
              <ActionIcon
                variant={state.legendHidden ? 'subtle' : 'light'}
                color="teal"
                size={ACTION_SIZE}
                aria-label={state.legendHidden ? 'Show map legend' : 'Hide map legend'}
                aria-pressed={!state.legendHidden}
                onClick={() => setLegendHidden(!state.legendHidden)}
              >
                <Icon icon="mdi:map-legend" width={GLYPH} height={GLYPH} />
              </ActionIcon>
            </Tooltip>
          )}
          {/* Only the floating card gets the preset sizes. The dock is resized
              by dragging its top edge, which is both finer-grained and the only
              gesture that can weigh the map against the filter list above it. */}
          {!docked && (
            <Tooltip label={state.cardSize === 'expanded' ? 'Compact' : 'Expand'} withinPortal>
              <ActionIcon
                variant="light"
                color="indigo"
                size={ACTION_SIZE}
                aria-label={
                  state.cardSize === 'expanded' ? 'Compact map panel' : 'Expand map panel'
                }
                onClick={() =>
                  setCardSize(state.cardSize === 'expanded' ? 'compact' : 'expanded')
                }
              >
                {/* Tabler rather than `mdi:arrow-expand-all`: mdi draws it as
                    four solid arrowheads, which next to the outline glyphs
                    either side of it reads as a different, louder kind of
                    button. */}
                <Icon
                  icon={
                    state.cardSize === 'expanded'
                      ? 'tabler:arrows-diagonal-minimize-2'
                      : 'tabler:arrows-diagonal'
                  }
                  width={GLYPH}
                  height={GLYPH}
                />
              </ActionIcon>
            </Tooltip>
          )}
          {/* The dock's counterpart to Hide: keep the panel where it is and
              give its room back to the filter list. Chevron direction is
              literal — unfolding moves the dock's top edge up. */}
          {docked && (
            <Tooltip label={collapsed ? 'Show the map' : 'Collapse to the title'} withinPortal>
              <ActionIcon
                variant="light"
                color="gray"
                size={ACTION_SIZE}
                aria-label={collapsed ? 'Show the map' : 'Collapse the map panel'}
                aria-expanded={!collapsed}
                onClick={() => setDockCollapsed(!collapsed)}
              >
                <Icon
                  icon={collapsed ? 'tabler:chevron-up' : 'tabler:chevron-down'}
                  width={GLYPH}
                  height={GLYPH}
                />
              </ActionIcon>
            </Tooltip>
          )}
          <Tooltip label={docked ? 'Float' : 'Dock in the filter panel'} withinPortal>
            <ActionIcon
              variant="light"
              color="gray"
              size={ACTION_SIZE}
              aria-label={docked ? 'Float map panel' : 'Dock map panel in the filter panel'}
              onClick={() => setMode(docked ? 'floating' : 'docked')}
            >
              {/* Tabler here too: `mdi:dock-bottom` is a solid block, and it
                  was the other glyph in this row carrying more ink than the
                  buttons around it. The menu in the app header keeps its own
                  mdi set — that is a different, internally consistent surface. */}
              <Icon
                icon={docked ? 'tabler:picture-in-picture' : 'tabler:layout-bottombar'}
                width={GLYPH}
                height={GLYPH}
              />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Hide" withinPortal>
            <ActionIcon
              variant="light"
              color="gray"
              size={ACTION_SIZE}
              aria-label="Hide map panel"
              onClick={() => setMode('hidden')}
            >
              <Icon icon="mdi:close" width={GLYPH} height={GLYPH} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>

      {components.length > 1 && !collapsed && (
        <Tabs
          value={active.metadata.index}
          onChange={(v) => v && setActiveIndex(v)}
          variant="outline"
          style={{ flexShrink: 0 }}
        >
          <Tabs.List>
            {components.map((c) => (
              <Tabs.Tab key={c.metadata.index} value={c.metadata.index}>
                <Text size="xs" truncate maw={120}>
                  {(c.metadata.title as string) || c.tab_title || 'Map'}
                </Text>
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
      )}

      {/* Unmounted rather than hidden while collapsed: a Plotly map in a
          zero-height box is not cheaper than a fresh one, and a dock that was
          left folded should cost the page nothing at all on load. The selection
          it made survives regardless — it lives in the dashboard's filters. */}
      {!collapsed && (
        <Box style={{ flex: 1, minHeight: 0, display: 'flex' }}>
          <Suspense
            fallback={
              <Center style={{ flex: 1 }}>
                <Loader size="sm" />
              </Center>
            }
          >
            {/* Keyed by index so switching maps remounts rather than feeding a new
                component's metadata into the previous map's in-flight fetch. */}
            <MapRenderer
              key={active.metadata.index}
              dashboardId={active.dashboard_id}
              metadata={active.metadata}
              filters={filters}
              onFilterChange={onFilterChange}
              refreshTick={refreshTick}
              onLegendPresence={setLegendPresent}
              presentation={{ bare: true, showLegend: !state.legendHidden }}
            />
          </Suspense>
        </Box>
      )}

      {/* Discoverability only. Once something *is* selected the header carries
          both the count and the way to clear it, so restating that down here
          would just cost the map a strip of height. */}
      {selectionEnabled && selected.length === 0 && !collapsed && (
        <Box
          px="xs"
          py={4}
          style={{
            borderTop: '1px solid var(--mantine-color-default-border)',
            flexShrink: 0,
          }}
        >
          <Text size="xs" c="dimmed" truncate>
            Click or lasso to filter the dashboard
          </Text>
        </Box>
      )}
    </>
  );
};

export default MapPanelBody;
