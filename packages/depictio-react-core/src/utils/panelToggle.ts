/**
 * Shared contract for the chrome panels that steal horizontal space from the
 * dashboard content column: the tab sidebar, the left filter panel, and (from
 * phase 4) the inspector.
 *
 * Each of them animates its width over a few hundred milliseconds. Plotly's
 * `useResizeHandler` and AG Grid both listen to the WINDOW resize event rather
 * than a per-cell ResizeObserver, so without help their canvas stays pinned at
 * its pre-toggle pixel size for the whole transition. `DashboardGrid` owns the
 * one implementation that fixes this — it predicts the final width, suppresses
 * its ResizeObserver while the transition is in flight, and pumps synthetic
 * resize events. This module is what lets every panel drive that one
 * implementation instead of growing its own copy.
 */

export const SIDEBAR_TOGGLE_EVENT = 'depictio:sidebar-toggle';
export const FILTER_PANEL_TOGGLE_EVENT = 'depictio:filter-panel-toggle';

/** Every event name `DashboardGrid` reacts to. Add a panel here, not a listener. */
export const PANEL_TOGGLE_EVENTS = [SIDEBAR_TOGGLE_EVENT, FILTER_PANEL_TOGGLE_EVENT] as const;

export interface PanelToggleDetail {
  /** Destination state of the panel, not its current one. */
  willBeOpen: boolean;
  /**
   * Width the content column gains when this panel closes (and loses when it
   * opens). Constant for the sidebar (its full width, since it collapses to
   * nothing); for the filter panel it is `panelWidth - railWidth`, because a
   * collapsed filter panel still occupies its icon rail.
   */
  swingPx: number;
  /** Must match the CSS transition actually animating the panel. */
  durationMs: number;
}

export function dispatchPanelToggle(eventName: string, detail: PanelToggleDetail): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(eventName, { detail }));
}
