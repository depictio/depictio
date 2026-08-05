import React, { useMemo } from 'react';
import { Paper } from '@mantine/core';
import { useViewportSize } from '@mantine/hooks';

import type { InteractiveFilter } from '../../api';
import MapPanelBody from './MapPanelBody';
import { clampToViewport, useDraggable, type Position } from './useDraggable';
import type { MapPanel } from './useMapPanel';

/** Compact is deliberately small enough to leave the dashboard readable behind
 *  it; expanded takes most of the viewport but stays capped so it never fills a
 *  large screen edge to edge. */
const COMPACT_SIZE = { width: 360, height: 280 };
const EXPANDED_MAX_WIDTH = 920;
const EXPANDED_VIEWPORT_FRACTION = { width: 0.78, height: 0.72 };

/** Both sizes resolve to plain pixel numbers rather than CSS lengths, so the
 *  drag clamp can work with the same values the card is styled with instead of
 *  parsing `min(...)` / `vh` expressions back into pixels. */
function cardSize(
  size: 'compact' | 'expanded',
  viewport: { width: number; height: number },
): { width: number; height: number } {
  if (size === 'compact') return COMPACT_SIZE;
  return {
    width: Math.min(
      EXPANDED_MAX_WIDTH,
      Math.round(viewport.width * EXPANDED_VIEWPORT_FRACTION.width),
    ),
    height: Math.round(viewport.height * EXPANDED_VIEWPORT_FRACTION.height),
  };
}

/** Default anchor for the floating card: bottom-right, clear of the Notes FAB. */
const DEFAULT_ANCHOR = { right: 16, bottom: 72 };

/** Above the Notes FAB (200) and banners, below the boot splash (400) and the
 *  walkthrough overlay (1000/1100) so neither gets occluded by a stray card. */
const Z_INDEX = 250;

export interface MapPanelSurfaceProps {
  panel: MapPanel;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  refreshTick?: number;
  /** Editor chrome for the map on screen — see `MapPanelBodyProps`. */
  renderEditActions?: (componentId: string, ownerDashboardId: string) => React.ReactNode;
}

/**
 * The map panel as a draggable card floating over the dashboard.
 *
 * This is the positioning half only — everything the viewer actually interacts
 * with lives in `MapPanelBody`, which the docked shell (`MapPanelDock`) renders
 * too. Mount both shells unconditionally; each returns `null` unless the panel
 * is in its mode.
 */
const MapPanelSurface: React.FC<MapPanelSurfaceProps> = ({
  panel,
  filters,
  onFilterChange,
  refreshTick,
  renderEditActions,
}) => {
  const { components, state, setPosition } = panel;
  const { nodeRef, livePosition, dragging, handleProps } = useDraggable((pos: Position) =>
    setPosition(pos.x, pos.y),
  );

  // `useViewportSize` reports 0×0 until its mount effect runs; fall back to the
  // window so the first paint is already the right size.
  const viewport = useViewportSize();
  const size = cardSize(state.cardSize, {
    width: viewport.width || window.innerWidth,
    height: viewport.height || window.innerHeight,
  });

  // A saved position can fall outside the viewport after a resize or on a
  // smaller screen, so re-clamp before use rather than trusting storage.
  const anchored = useMemo(() => {
    const raw =
      livePosition ?? (state.x != null && state.y != null ? { x: state.x, y: state.y } : null);
    if (!raw) return null;
    return clampToViewport(raw, size.width, size.height);
  }, [livePosition, state.x, state.y, size.width, size.height]);

  if (state.mode !== 'floating' || components.length === 0) return null;

  return (
    <Paper
      ref={nodeRef}
      withBorder
      shadow="md"
      radius="md"
      style={{
        position: 'fixed',
        zIndex: Z_INDEX,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        width: size.width,
        height: size.height,
        ...(anchored
          ? { left: anchored.x, top: anchored.y }
          : { right: DEFAULT_ANCHOR.right, bottom: DEFAULT_ANCHOR.bottom }),
        // Deliberately no width/height transition. An animated resize leaves
        // the map lagging a box it no longer fills, and the map inside has to
        // be told to re-fit anyway (see the resize effect in MapPanelBody) —
        // which is only correct once the box has settled.
      }}
      data-testid="map-panel-surface"
      data-mode={state.mode}
    >
      <MapPanelBody
        panel={panel}
        filters={filters}
        onFilterChange={onFilterChange}
        refreshTick={refreshTick}
        variant="floating"
        dragHandleProps={handleProps}
        dragging={dragging}
        renderEditActions={renderEditActions}
      />
    </Paper>
  );
};

export default MapPanelSurface;
