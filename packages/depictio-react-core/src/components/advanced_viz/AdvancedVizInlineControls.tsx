import React, { createContext, useContext } from 'react';
import { Center, ScrollArea, SegmentedControl, Tooltip, VisuallyHidden } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  RAIL_WIDTH_PX,
  CONTROLS_PLACEMENTS,
  isControlsPlacement,
  type ControlsPlacement,
  type InlineLayout,
} from './controlsPlacement';
import { VIZ_SEGMENTED_STYLES, VizControlsGrid } from './controls/VizControls';

/**
 * The React half of the controls-placement feature: the contexts the dispatch
 * publishes and the frame reads, the two inline surfaces, and the placement
 * picker drawn in the header of every controls block.
 *
 * The rules themselves (resolution order, rail-vs-below threshold, the echo
 * strings) live in `controlsPlacement.ts` so the node-environment vitest can
 * cover them without React or Mantine. Re-exported here so a caller only needs
 * one import.
 */
export * from './controlsPlacement';

/** Dashboard-level default, provided by the app from the dashboard document. */
export const AdvancedVizPlacementDefaultContext = createContext<ControlsPlacement>('popover');

export const AdvancedVizPlacementDefaultProvider: React.FC<{
  /** Raw dashboard field; anything unrecognised falls back to `popover`. */
  value?: unknown;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <AdvancedVizPlacementDefaultContext.Provider
    value={isControlsPlacement(value) ? value : 'popover'}
  >
    {children}
  </AdvancedVizPlacementDefaultContext.Provider>
);

export function useAdvancedVizPlacementDefault(): ControlsPlacement {
  return useContext(AdvancedVizPlacementDefaultContext);
}

export interface ControlsPlacementState {
  placement: ControlsPlacement;
  /** Moves this tile's controls. Local to the session on a read-only surface,
   *  persisted wherever a viz-config sink is mounted (the editor, the builder
   *  preview), which is the same rule every other Tier-2 control follows. */
  setPlacement?: (next: ControlsPlacement) => void;
}

/**
 * Published by `AdvancedVizDispatch` (which holds the metadata and the config
 * sink) and read by `AdvancedVizFrame` (which draws the inline area) and by the
 * dispatch itself (which decides what is left for the popover). One resolution,
 * two consumers, so the strip and the popover can never disagree about which
 * tier lives where.
 */
export const ControlsPlacementContext = createContext<ControlsPlacementState | null>(null);

export function useControlsPlacement(): ControlsPlacementState {
  return useContext(ControlsPlacementContext) ?? { placement: 'popover' };
}

/** Region echo published by the dispatch, which is the only place that sees
 *  the dashboard's filters. Null when no region filter reached the tile. */
export const AdvancedVizRegionEchoContext = createContext<string | null>(null);

export function useRegionEcho(): string | null {
  return useContext(AdvancedVizRegionEchoContext);
}

/**
 * The encoding tier laid out as a horizontal strip under the title.
 *
 * Renderers pass `primaryControls` as a *fragment of individual controls*
 * rather than a pre-arranged Stack, so the same node reads as a strip here, as
 * a column in the rail, and as a settings list in the popover. The controls
 * themselves are the `Viz*` wrappers from `controls/VizControls`, which fix
 * size and height; the grid here fixes the arrangement.
 */
export const InlineControlsStrip: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const state = useControlsPlacement();
  return (
    <VizControlsGrid
      layout="strip"
      framed
      headerAction={<ControlsPlacementPicker state={state} />}
      data-testid="advanced-viz-controls-strip"
    >
      {children}
    </VizControlsGrid>
  );
};

/**
 * Both tiers in a column, beside the plot or under it.
 *
 * Scrolled rather than clipped: a renderer with a dozen controls (sashimi's
 * region, zoom and per-track heights) would otherwise push the figure out of
 * the tile entirely.
 */
export const InlineControlsRail: React.FC<{
  layout: Extract<InlineLayout, 'rail-side' | 'rail-below'>;
  children: React.ReactNode;
}> = ({ layout, children }) => {
  const state = useControlsPlacement();
  return (
    <ScrollArea
      type="auto"
      data-testid="advanced-viz-controls-rail"
      data-rail-layout={layout}
      style={
        layout === 'rail-side'
          ? { width: RAIL_WIDTH_PX, flex: `0 0 ${RAIL_WIDTH_PX}px`, minHeight: 0 }
          : { width: '100%', maxHeight: 220 }
      }
    >
      <div style={{ paddingRight: 6, paddingLeft: layout === 'rail-side' ? 8 : 0 }}>
        <VizControlsGrid
          layout="column"
          framed
          headerAction={<ControlsPlacementPicker state={state} />}
        >
          {children}
        </VizControlsGrid>
      </div>
    </ScrollArea>
  );
};

const PLACEMENT_ICON: Record<ControlsPlacement, string> = {
  popover: 'tabler:adjustments-horizontal',
  rail: 'tabler:layout-sidebar-right',
  header: 'tabler:layout-navbar',
};

const PLACEMENT_LABEL: Record<ControlsPlacement, string> = {
  popover: 'In the settings popover',
  rail: 'In a side rail',
  header: 'Under the title',
};

/**
 * Where this tile's controls live, picked from the header of the controls
 * block itself (the popover's, the strip's or the rail's), so the way back to
 * the popover is always on the block that is showing. Icons only, each with a
 * tooltip and a visually hidden name; the current placement is the selected
 * segment. Renders nothing where the placement cannot be changed.
 */
export const ControlsPlacementPicker: React.FC<{ state: ControlsPlacementState }> = ({
  state,
}) => {
  const { placement, setPlacement } = state;
  if (!setPlacement) return null;
  return (
    <SegmentedControl
      size="xs"
      aria-label="Controls placement"
      data-testid="advanced-viz-placement-picker"
      data-placement={placement}
      value={placement}
      onChange={(v) => {
        if (isControlsPlacement(v)) setPlacement(v);
      }}
      styles={VIZ_SEGMENTED_STYLES}
      data={CONTROLS_PLACEMENTS.map((p) => ({
        value: p,
        label: (
          <Tooltip label={PLACEMENT_LABEL[p]} withArrow openDelay={300}>
            <Center>
              <Icon icon={PLACEMENT_ICON[p]} width={14} height={14} />
              <VisuallyHidden>{PLACEMENT_LABEL[p]}</VisuallyHidden>
            </Center>
          </Tooltip>
        ),
      }))}
    />
  );
};
