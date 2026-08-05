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
export const INSPECTOR_TOGGLE_EVENT = 'depictio:inspector-toggle';

/** Every event name `DashboardGrid` reacts to. Add a panel here, not a listener. */
export const PANEL_TOGGLE_EVENTS = [
  SIDEBAR_TOGGLE_EVENT,
  FILTER_PANEL_TOGGLE_EVENT,
  INSPECTOR_TOGGLE_EVENT,
] as const;

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

/**
 * The other half of the contract: a panel being *dragged* rather than toggled.
 *
 * A toggle animates to a width known in advance, so `DashboardGrid` can jump
 * to it and let CSS do the rest. A drag has no known destination and produces
 * a width change per pointermove — measuring and re-laying out every grid on
 * each one is work proportional to how much of the dashboard is open, which is
 * exactly why the drag got heavier the more sections the user expanded.
 *
 * So the drag freezes instead: while this class is on `<body>`, anything that
 * sizes itself from a ResizeObserver holds its last measurement, and re-reads
 * it once on `PANEL_RESIZE_END_EVENT`. The panel itself still follows the
 * pointer — it moves through a CSS variable, which costs no React render.
 */
export const PANEL_RESIZING_CLASS = 'depictio-panel-resizing';
export const PANEL_RESIZE_END_EVENT = 'depictio:panel-resize-end';

export function beginPanelResize(): void {
  if (typeof document === 'undefined') return;
  document.body.classList.add(PANEL_RESIZING_CLASS);
}

/** Callers dispatch their own final `resize` after this, once the committed
 *  width is in the DOM. */
export function endPanelResize(): void {
  if (typeof document === 'undefined') return;
  document.body.classList.remove(PANEL_RESIZING_CLASS);
  window.dispatchEvent(new Event(PANEL_RESIZE_END_EVENT));
}

/** True while a panel drag is in flight. Read by ResizeObserver callbacks. */
export function isPanelResizing(): boolean {
  return typeof document !== 'undefined' && document.body.classList.contains(PANEL_RESIZING_CLASS);
}
