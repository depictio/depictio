import React, { useCallback, useEffect, useRef, useState } from 'react';
import { beginPanelResize, endPanelResize } from 'depictio-react-core';

/**
 * Persisted, drag-adjustable width for the left filter panel. Scoped per
 * dashboard family, like `useFilterPanelOpen` — a width dragged on one tab
 * carries to its siblings.
 *
 * Hand-rolled rather than built on `react-resizable`: that package ships with
 * react-grid-layout but carries no `@types` entry here, and a one-axis splitter
 * is a dozen lines of pointer events either way.
 */
const STORAGE_KEY_PREFIX = 'filter-panel-width:';

/** Below this the MultiSelect labels wrap to uselessness. */
export const FILTER_PANEL_MIN_WIDTH = 220;
/** Hard ceiling on a very wide display, where half the window is more panel
 *  than any filter list needs. */
export const FILTER_PANEL_MAX_WIDTH = 900;
/** Floor for the ceiling: even on a narrow window the panel can reach this,
 *  which is what a date-range picker or a long sample id needs. */
const MIN_MAX_WIDTH = 480;
/** Share of the window the panel may claim. Past this it stops being a side
 *  panel and starts competing with the content column. */
const MAX_WIDTH_FRACTION = 0.5;
/** Roughly the old hard-coded `20vw` on a typical laptop. */
const DEFAULT_WIDTH = 300;
/** Arrow-key increment, so the handle is usable without a pointer. */
export const FILTER_PANEL_KEYBOARD_STEP = 16;
/**
 * The variable the layout's `grid-template-columns` reads for the panel track.
 *
 * A drag writes it straight onto the layout element, so the panel follows the
 * pointer without a React render: at 60Hz, re-rendering the dashboard to move
 * a splitter means the splitter moves as fast as the dashboard renders, which
 * on a fully expanded dashboard is not fast. State catches up once, on release.
 */
export const FILTER_PANEL_WIDTH_VAR = '--depictio-filter-panel-width';

function storageKey(dashboardId: string | null): string {
  return `${STORAGE_KEY_PREFIX}${dashboardId ?? 'unknown'}`;
}

/** Widest the panel may get right now — viewport-relative, so a big display
 *  gets a genuinely wide panel and a laptop still keeps its content column. */
function maxWidth(): number {
  const viewport = typeof window === 'undefined' ? 0 : window.innerWidth;
  return Math.round(
    Math.min(FILTER_PANEL_MAX_WIDTH, Math.max(MIN_MAX_WIDTH, viewport * MAX_WIDTH_FRACTION)),
  );
}

function clampWidth(px: number): number {
  return Math.min(maxWidth(), Math.max(FILTER_PANEL_MIN_WIDTH, Math.round(px)));
}

function readWidth(dashboardId: string | null): number {
  try {
    const raw = localStorage.getItem(storageKey(dashboardId));
    if (raw == null) return DEFAULT_WIDTH;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? clampWidth(parsed) : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

function writeWidth(dashboardId: string | null, width: number): void {
  try {
    localStorage.setItem(storageKey(dashboardId), String(width));
  } catch {
    // ignore quota / disabled storage
  }
}

export interface FilterPanelWidth {
  width: number;
  /**
   * True while a drag is in flight. The layout keys its column transition off
   * this: that transition exists for the collapse toggle, and leaving it on
   * during a drag means every pointermove starts a fresh 300ms ease, so the
   * panel trails the pointer instead of following it.
   */
  resizing: boolean;
  /**
   * Attach to the element whose `grid-template-columns` reads
   * `FILTER_PANEL_WIDTH_VAR`. That element is what a drag writes to directly.
   */
  layoutRef: React.MutableRefObject<HTMLDivElement | null>;
  /** Attach to the drag handle's `onPointerDown`. */
  beginResize: (event: React.PointerEvent<HTMLElement>) => void;
  /** Keyboard path for the same handle. */
  nudge: (deltaPx: number) => void;
}

export function useFilterPanelWidth(dashboardId: string | null): FilterPanelWidth {
  const [width, setWidth] = useState<number>(() => readWidth(dashboardId));
  const [resizing, setResizing] = useState(false);
  const widthRef = useRef(width);
  const layoutRef = useRef<HTMLDivElement | null>(null);

  // Switching dashboards swaps the storage key under a mounted panel.
  const dashboardRef = useRef(dashboardId);
  useEffect(() => {
    if (dashboardRef.current === dashboardId) return;
    dashboardRef.current = dashboardId;
    const next = readWidth(dashboardId);
    widthRef.current = next;
    setWidth(next);
  }, [dashboardId]);

  // Unmounting mid-drag would otherwise leave window listeners and a
  // `col-resize` cursor behind for the rest of the session.
  const endDragRef = useRef<(() => void) | null>(null);
  useEffect(() => () => endDragRef.current?.(), []);

  /**
   * `live` is the drag path: write the CSS variable and nothing else, so the
   * panel edge moves at the browser's pace rather than React's. Every other
   * caller (keyboard, window re-clamp, dashboard switch) goes through state.
   */
  const apply = useCallback((next: number, live = false) => {
    const clamped = clampWidth(next);
    if (clamped === widthRef.current) return;
    widthRef.current = clamped;
    if (live) {
      layoutRef.current?.style.setProperty(FILTER_PANEL_WIDTH_VAR, `${clamped}px`);
    } else {
      setWidth(clamped);
    }
  }, []);

  const commit = useCallback(() => {
    writeWidth(dashboardRef.current, widthRef.current);
  }, []);

  // The ceiling is viewport-relative, so shrinking the window can leave the
  // panel wider than it is now allowed to be. Re-clamp rather than persist:
  // widening the window again should give the user their width back.
  useEffect(() => {
    const onWindowResize = () => apply(widthRef.current);
    window.addEventListener('resize', onWindowResize);
    return () => window.removeEventListener('resize', onWindowResize);
  }, [apply]);

  const beginResize = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      event.preventDefault();
      endDragRef.current?.(); // defensive: never stack two drags

      const startX = event.clientX;
      const startWidth = widthRef.current;

      // Nothing is told to reflow during the drag. Plotly and AG Grid only
      // reflow on a window resize, and each one costs more the more of the
      // dashboard is expanded — pumping those mid-drag is what made a fully
      // expanded dashboard drag badly. They keep their pre-drag size while the
      // panel moves and are told once, below, about the width that stuck.
      const onMove = (e: PointerEvent) => {
        apply(startWidth + (e.clientX - startX), true);
      };

      const endDrag = () => {
        endDragRef.current = null;
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', endDrag);
        window.removeEventListener('pointercancel', endDrag);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        setResizing(false);
        // Order matters: state first, so React has written the committed width
        // before anything measures. `endPanelResize` releases the observers
        // frozen for the drag, and the resize event covers what watches the
        // window instead.
        setWidth(widthRef.current);
        endPanelResize();
        window.dispatchEvent(new Event('resize'));
        commit();
      };

      endDragRef.current = endDrag;
      setResizing(true);
      beginPanelResize();
      // Suppress the text selection a horizontal drag would otherwise sweep
      // across the dashboard, and keep the resize cursor while off the handle.
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'col-resize';
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', endDrag);
      window.addEventListener('pointercancel', endDrag);
    },
    [apply, commit],
  );

  const nudge = useCallback(
    (deltaPx: number) => {
      apply(widthRef.current + deltaPx);
      commit();
      window.dispatchEvent(new Event('resize'));
    },
    [apply, commit],
  );

  return { width, resizing, layoutRef, beginResize, nudge };
}

export default useFilterPanelWidth;
