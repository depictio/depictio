import { useCallback, useMemo, useState } from 'react';

import { type FloatingComponent, type InteractiveFilter } from '../../api';
import { PANEL_KINDS, type FloatingPanelKind } from './panelKinds';
import { clearSelectionFilters, selectionCount } from './panelSelection';
import {
  useMapPanelState,
  type MapPanelCardSize,
  type MapPanelMode,
  type MapPanelState,
} from './useMapPanelState';

export interface MapPanel {
  /** What this panel holds: the dashboard's floating maps, or its floating 3D
   *  structures. The shells read it for the glyph, the labels and the body. */
  kind: FloatingPanelKind;
  /** The family's floating components of this kind, in tab order. */
  components: FloatingComponent[];
  /** Parent dashboard id — the family key the panel state is stored under. */
  familyId: string | null;
  state: MapPanelState;
  setMode: (mode: MapPanelMode) => void;
  setCardSize: (size: MapPanelCardSize) => void;
  /** Committed corner-resize size in pixels; `null`s restore the preset. */
  setCardDims: (width: number | null, height: number | null) => void;
  setPosition: (x: number, y: number) => void;
  /** Committed dock height in pixels; `null` restores the default. */
  setDockHeight: (height: number | null) => void;
  /** Fold the dock down to its title bar, or bring it back. */
  setDockCollapsed: (collapsed: boolean) => void;
  setLegendHidden: (hidden: boolean) => void;
  /** Which map the panel is showing, when the family has more than one. */
  activeIndex: string | null;
  setActiveIndex: (index: string) => void;
  /** Values selected across every component of this panel. Drives the header
   *  badge, which for a map is often the only sign that a filter set on another
   *  tab is still live. For a structure it is the count of residue picks (one
   *  per pick: a range is a single selection), and a pick does not outlive a
   *  tab switch, so the badge there only reports the tab on screen. */
  totalSelected: number;
  /** Clear every component's selection at once. */
  clearSelection: () => void;
  /** True when the panel is pinned under the filter panel. The dock renders in
   *  flow, so nothing on the page has to reserve space for it. */
  docked: boolean;
  /** False when this dashboard has no floating component of this kind at all:
   *  the shells render neither the header control nor the panel. */
  available: boolean;
}

export interface UseMapPanelOptions {
  /** Which panel this is. Defaults to the map panel, which is what every caller
   *  was before the 3D structure panel existed. */
  kind?: FloatingPanelKind;
  /** The family's floating components of `kind`, in tab order. Resolved by
   *  `useCrossTabComponents` (the shell owns the single family request per
   *  page load) and split with `partitionFloating`. */
  components: FloatingComponent[];
  /** Parent dashboard id — the family key the panel state is stored under. */
  familyId: string | null;
  /** Instant filters, not the debounced copy: the badge and the selection
   *  summary should not lag behind the click that set them. */
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * Everything the map panel needs, in one place.
 *
 * A floating component is authored on one tab but belongs to the whole
 * dashboard, so this receives the tab family's floating components rather than
 * reading the current tab's `stored_metadata`. Each component keeps its owning
 * tab's id, which is what the renderer fetches against.
 *
 * The shell calls this once per kind and hands the result to both the header
 * control and the panel surface, so the two always agree on mode and selection.
 */
export function useMapPanel({
  kind = 'map',
  components,
  familyId,
  filters,
  onFilterChange,
}: UseMapPanelOptions): MapPanel {
  const [activeIndex, setActiveIndex] = useState<string | null>(null);

  const authorDefault = components[0]?.metadata.floating_initial_state;
  const {
    state,
    setMode,
    setCardSize,
    setCardDims,
    setPosition,
    setDockHeight,
    setDockCollapsed,
    setLegendHidden,
  } = useMapPanelState(familyId, authorDefault, PANEL_KINDS[kind].storagePrefix);

  const totalSelected = useMemo(
    () => components.reduce((sum, c) => sum + selectionCount(kind, filters, c.metadata.index), 0),
    [kind, components, filters],
  );

  const clearSelection = useCallback(() => {
    if (!onFilterChange) return;
    for (const c of components) {
      for (const cleared of clearSelectionFilters(kind, filters, c.metadata.index)) {
        onFilterChange(cleared);
      }
    }
  }, [kind, components, filters, onFilterChange]);

  const available = components.length > 0;

  return {
    kind,
    components,
    familyId,
    state,
    setMode,
    setCardSize,
    setCardDims,
    setPosition,
    setDockHeight,
    setDockCollapsed,
    setLegendHidden,
    activeIndex:
      components.find((c) => c.metadata.index === activeIndex)?.metadata.index ??
      components[0]?.metadata.index ??
      null,
    setActiveIndex,
    totalSelected,
    clearSelection,
    docked: available && state.mode === 'docked',
    available,
  };
}
