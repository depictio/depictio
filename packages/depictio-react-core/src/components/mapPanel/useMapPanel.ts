import { useCallback, useEffect, useMemo, useState } from 'react';

import { fetchFloatingComponents, type FloatingComponent, type InteractiveFilter } from '../../api';
import { mapSelectionValues } from '../../selection';
import {
  useMapPanelState,
  type MapPanelCardSize,
  type MapPanelMode,
  type MapPanelState,
} from './useMapPanelState';

export interface MapPanel {
  /** Floating maps across the whole tab family, in tab order. */
  components: FloatingComponent[];
  /** Parent dashboard id — the family key the panel state is stored under. */
  familyId: string | null;
  state: MapPanelState;
  setMode: (mode: MapPanelMode) => void;
  setCardSize: (size: MapPanelCardSize) => void;
  setPosition: (x: number, y: number) => void;
  /** Committed dock height in pixels; `null` restores the default. */
  setDockHeight: (height: number | null) => void;
  /** Fold the dock down to its title bar, or bring it back. */
  setDockCollapsed: (collapsed: boolean) => void;
  setLegendHidden: (hidden: boolean) => void;
  /** Which map the panel is showing, when the family has more than one. */
  activeIndex: string | null;
  setActiveIndex: (index: string) => void;
  /** Values selected across every floating map. Drives the header badge, which
   *  is often the only sign that a filter set on another tab is still live. */
  totalSelected: number;
  /** Clear every floating map's selection at once. */
  clearSelection: () => void;
  /** True when the panel is pinned under the filter panel. The dock renders in
   *  flow, so nothing on the page has to reserve space for it. */
  docked: boolean;
  /** False when this dashboard has no floating map at all — the shells render
   *  neither the header control nor the panel. */
  available: boolean;
}

export interface UseMapPanelOptions {
  /** The tab currently being viewed. The family is resolved server-side. */
  dashboardId: string;
  /** Instant filters, not the debounced copy: the badge and the selection
   *  summary should not lag behind the click that set them. */
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /**
   * Fires once the family's floating components are known. The shell uses this
   * to decide which persisted cross-tab filters are still valid — a map that
   * was deleted or moved back into the grid must not keep filtering from
   * storage forever.
   */
  onComponentsResolved?: (familyId: string | null, components: FloatingComponent[]) => void;
}

/**
 * Everything the map panel needs, in one place.
 *
 * A floating map is authored on one tab but belongs to the whole dashboard, so
 * this fetches the tab family's floating components rather than reading the
 * current tab's `stored_metadata`. Each component keeps its owning tab's id,
 * which is what `MapRenderer` fetches against.
 *
 * The shell calls this once and hands the result to both the header control
 * and the panel surface, so the two always agree on mode and selection.
 */
export function useMapPanel({
  dashboardId,
  filters,
  onFilterChange,
  onComponentsResolved,
}: UseMapPanelOptions): MapPanel {
  const [components, setComponents] = useState<FloatingComponent[]>([]);
  const [familyId, setFamilyId] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState<string | null>(null);

  const authorDefault = components[0]?.metadata.floating_initial_state;
  const {
    state,
    setMode,
    setCardSize,
    setPosition,
    setDockHeight,
    setDockCollapsed,
    setLegendHidden,
  } = useMapPanelState(familyId, authorDefault);

  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchFloatingComponents(dashboardId).then((res) => {
      if (cancelled) return;
      setComponents(res.components);
      setFamilyId(res.parent_dashboard_id);
      onComponentsResolved?.(res.parent_dashboard_id, res.components);
    });
    return () => {
      cancelled = true;
    };
    // `onComponentsResolved` is intentionally excluded: it is a shell callback
    // that changes identity on every filter change, and re-fetching on that
    // would defeat the point of a single request per page load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId]);

  const totalSelected = useMemo(
    () =>
      components.reduce(
        (sum, c) => sum + mapSelectionValues(filters, c.metadata.index).length,
        0,
      ),
    [components, filters],
  );

  const clearSelection = useCallback(() => {
    if (!onFilterChange) return;
    for (const c of components) {
      if (mapSelectionValues(filters, c.metadata.index).length === 0) continue;
      onFilterChange({ index: c.metadata.index, value: [], source: 'map_selection' });
    }
  }, [components, filters, onFilterChange]);

  const available = components.length > 0;

  return {
    components,
    familyId,
    state,
    setMode,
    setCardSize,
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
