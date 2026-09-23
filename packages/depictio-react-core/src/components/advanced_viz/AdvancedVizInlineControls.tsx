import React, { createContext, useContext } from 'react';
import { ActionIcon, Group, ScrollArea, Stack } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  RAIL_WIDTH_PX,
  isControlsPlacement,
  nextPlacement,
  type ControlsPlacement,
  type InlineLayout,
} from './controlsPlacement';

/**
 * The React half of the controls-placement feature: the contexts the dispatch
 * publishes and the frame reads, the two inline surfaces, and the chrome pin.
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
 * a column in the rail, and as a settings list in the popover. Compact sizes
 * (`size="xs"`, an explicit `w`) are the renderer's to set: Mantine sizes are
 * per component and cannot be cascaded from a wrapper.
 */
export const InlineControlsStrip: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Group gap="xs" wrap="wrap" align="flex-end" data-testid="advanced-viz-controls-strip">
    {children}
  </Group>
);

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
}> = ({ layout, children }) => (
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
    <Stack gap={8} pr={6} pl={layout === 'rail-side' ? 8 : 0}>
      {children}
    </Stack>
  </ScrollArea>
);

const PLACEMENT_ICON: Record<ControlsPlacement, string> = {
  popover: 'tabler:pinned-off',
  header: 'tabler:layout-navbar',
  rail: 'tabler:layout-sidebar-right-expand',
};

const PLACEMENT_LABEL: Record<ControlsPlacement, string> = {
  popover: 'Controls in the popover',
  header: 'Controls under the title',
  rail: 'Controls in a side rail',
};

/**
 * Chrome ActionIcon that pins this tile's controls out of the popover, cycling
 * popover to header to rail. Filled while the controls are pinned, so a tile
 * that is showing them reads as such from the action row.
 */
export const ControlsPlacementToggle: React.FC<{ state: ControlsPlacementState }> = ({
  state,
}) => {
  const { placement, setPlacement } = state;
  if (!setPlacement) return null;
  const next = nextPlacement(placement);
  return (
    <ActionIcon
      variant={placement === 'popover' ? 'subtle' : 'filled'}
      color="teal"
      size="sm"
      aria-label="Controls placement"
      title={`${PLACEMENT_LABEL[placement]} (click for: ${PLACEMENT_LABEL[next].toLowerCase()})`}
      data-testid="advanced-viz-placement-toggle"
      data-placement={placement}
      onClick={() => setPlacement(next)}
    >
      <Icon icon={PLACEMENT_ICON[placement]} width={16} height={16} />
    </ActionIcon>
  );
};
