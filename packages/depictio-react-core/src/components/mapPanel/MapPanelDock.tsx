import React from 'react';
import { Box, Tooltip } from '@mantine/core';

import type { InteractiveFilter } from '../../api';
import MapPanelBody from './MapPanelBody';
import { MAX_DOCK_SHARE, useDockResize } from './useDockResize';
import type { MapPanel } from './useMapPanel';

/** Starting height, until the viewer drags the top edge somewhere else. Tall
 *  enough that a basemap reads as a map rather than a strip. */
const DEFAULT_DOCK_HEIGHT = 260;

/** Never let a stored height swallow the column — the window it was dragged in
 *  may have been much taller than the one it is restored into. The drag clamps
 *  to the same share, so the two never disagree mid-gesture. */
const DOCK_MAX_SHARE = `${MAX_DOCK_SHARE * 100}%`;

export interface MapPanelDockProps {
  panel: MapPanel;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  refreshTick?: number;
  /** Editor chrome for the map on screen — see `MapPanelBodyProps`. */
  renderEditActions?: (componentId: string, ownerDashboardId: string) => React.ReactNode;
}

/**
 * The map panel pinned to the bottom of the filter panel.
 *
 * Unlike the floating shell this renders *in flow*, as the last child of the
 * filter panel's `Paper` — so it reserves no dashboard width and needs no
 * offsetting from anything else on the page. The host is expected to be a flex
 * column whose filter list scrolls; the dock is the non-shrinking footer under
 * it, and its top edge is the split between the two.
 *
 * Mount it unconditionally: it renders nothing unless the panel is docked.
 */
const MapPanelDock: React.FC<MapPanelDockProps> = ({
  panel,
  filters,
  onFilterChange,
  refreshTick,
  renderEditActions,
}) => {
  const { nodeRef, liveHeight, resizing, handleProps } = useDockResize(panel.setDockHeight);

  if (!panel.docked) return null;

  const collapsed = panel.state.dockCollapsed;
  const height = liveHeight ?? panel.state.dockHeight ?? DEFAULT_DOCK_HEIGHT;

  return (
    <Box
      ref={nodeRef}
      style={{
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        // Collapsed, the dock is exactly its title bar — let the content say
        // how tall that is rather than pinning a second magic number to it.
        height: collapsed ? undefined : `min(${height}px, ${DOCK_MAX_SHARE})`,
        // The grip carries this border when there is something to resize.
        borderTop: collapsed ? '1px solid var(--mantine-color-default-border)' : undefined,
        // Span the host Paper's padding so the dock reads as its own section
        // rather than a card floating inside the filter list.
        marginInline: 'calc(var(--mantine-spacing-md) * -1)',
        marginBottom: 'calc(var(--mantine-spacing-md) * -1)',
        marginTop: 'var(--mantine-spacing-xs)',
        overflow: 'hidden',
      }}
      data-testid="map-panel-dock"
      data-mode={panel.state.mode}
      data-collapsed={collapsed || undefined}
    >
      {/* The dock's top border doubles as its resize handle. It replaces the
          floating card's Compact/Expand preset: a dragged edge says what the
          preset only approximated, and the filter panel is the one place where
          how much room the map may take is a per-viewer judgement call. */}
      {!collapsed && (
        <Tooltip label="Drag to resize the map" withinPortal openDelay={400}>
          <Box
            {...handleProps}
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize the map panel"
            style={{
              flexShrink: 0,
              // Comfortably grabbable: a hairline splitter is a pixel-hunt, and
              // this one sits directly above a row of buttons.
              height: 12,
              cursor: 'ns-resize',
              touchAction: 'none',
              borderTop: '1px solid var(--mantine-color-default-border)',
              background: resizing ? 'var(--mantine-color-default-hover)' : undefined,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {/* Grip: without something to aim at, an invisible 9px strip is not
                an affordance anyone finds. */}
            <Box
              style={{
                width: 28,
                height: 3,
                borderRadius: 2,
                background: 'var(--mantine-color-default-border)',
              }}
            />
          </Box>
        </Tooltip>
      )}
      <MapPanelBody
        panel={panel}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
        variant="docked"
        renderEditActions={renderEditActions}
      />
    </Box>
  );
};

export default MapPanelDock;
