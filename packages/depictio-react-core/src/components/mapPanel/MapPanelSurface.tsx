import React, { useMemo } from 'react';
import { Paper } from '@mantine/core';
import { useViewportSize } from '@mantine/hooks';

import type { InteractiveFilter } from '../../api';
import { Z_LAYERS } from '../../zLayers';
import MapPanelBody from './MapPanelBody';
import { PANEL_KINDS, type PanelKindSpec } from './panelKinds';
import { useCardResize } from './useCardResize';
import { clampToViewport, useDraggable, type Position } from './useDraggable';
import type { MapPanel } from './useMapPanel';

/** Compact is deliberately small enough to leave the dashboard readable behind
 *  it (its footprint is the kind's: `PANEL_KINDS`); expanded takes most of the
 *  viewport but stays capped so it never fills a large screen edge to edge. */
const EXPANDED_MAX_WIDTH = 920;
const EXPANDED_VIEWPORT_FRACTION = { width: 0.78, height: 0.72 };

/** Both sizes resolve to plain pixel numbers rather than CSS lengths, so the
 *  drag clamp can work with the same values the card is styled with instead of
 *  parsing `min(...)` / `vh` expressions back into pixels. */
function cardSize(
  size: 'compact' | 'expanded',
  viewport: { width: number; height: number },
  spec: PanelKindSpec,
): { width: number; height: number } {
  if (size === 'compact') return spec.compact;
  return {
    width: Math.min(
      EXPANDED_MAX_WIDTH,
      Math.round(viewport.width * EXPANDED_VIEWPORT_FRACTION.width),
    ),
    height: Math.round(viewport.height * EXPANDED_VIEWPORT_FRACTION.height),
  };
}

export interface MapPanelSurfaceProps {
  panel: MapPanel;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  refreshTick?: number;
  /** Editor chrome for the component on screen, see `MapPanelBodyProps`. */
  renderEditActions?: (componentId: string, ownerDashboardId: string) => React.ReactNode;
}

/**
 * A floating panel (the map's, or the 3D structure's) as a draggable card over
 * the dashboard.
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
  const { kind, components, state, setPosition, setCardDims } = panel;
  const spec = PANEL_KINDS[kind];
  const { nodeRef, livePosition, dragging, handleProps } = useDraggable((pos: Position) =>
    setPosition(pos.x, pos.y),
  );
  const {
    liveSize,
    resizing,
    handleProps: resizeHandleProps,
  } = useCardResize(nodeRef, (next) => setCardDims(next.width, next.height));

  // `useViewportSize` reports 0×0 until its mount effect runs; fall back to the
  // window so the first paint is already the right size.
  const viewport = useViewportSize();
  const preset = cardSize(
    state.cardSize,
    {
      width: viewport.width || window.innerWidth,
      height: viewport.height || window.innerHeight,
    },
    spec,
  );
  // A freely dragged size beats the preset; the in-flight drag value beats
  // both. The presets stay reachable because choosing one clears the stored
  // size (see `setCardSize`).
  const size = liveSize ?? {
    width: state.cardWidth ?? preset.width,
    height: state.cardHeight ?? preset.height,
  };

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
        zIndex: Z_LAYERS.mapPanel,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        width: size.width,
        height: size.height,
        ...(anchored
          ? { left: anchored.x, top: anchored.y }
          : spec.anchor),
        // Deliberately no width/height transition. An animated resize leaves
        // the map lagging a box it no longer fills, and the map inside has to
        // be told to re-fit anyway (see the resize effect in MapPanelBody) —
        // which is only correct once the box has settled.
      }}
      data-testid={`${spec.testId}-surface`}
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
      {/* Corner resize handle. A drawn grip rather than a bare hot zone —
          without a visible affordance nobody discovers the card resizes at
          all. `data-no-drag` keeps the header's move-drag from swallowing the
          gesture when the card is small enough for the two to overlap. */}
      <div
        {...resizeHandleProps}
        data-no-drag
        aria-label={`Resize ${spec.noun} panel`}
        style={{
          position: 'absolute',
          right: 0,
          bottom: 0,
          width: 18,
          height: 18,
          cursor: 'nwse-resize',
          touchAction: 'none',
          zIndex: 2,
          // Two short diagonal strokes, the browser-native resize-grip idiom.
          background:
            'linear-gradient(135deg, transparent 0 50%, var(--mantine-color-dimmed) 50% 57%, transparent 57% 68%, var(--mantine-color-dimmed) 68% 75%, transparent 75%) no-repeat',
          opacity: resizing ? 0.9 : 0.55,
        }}
      />
    </Paper>
  );
};

export default MapPanelSurface;
