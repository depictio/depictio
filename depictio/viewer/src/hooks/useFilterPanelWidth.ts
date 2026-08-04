import React, { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Persisted, drag-adjustable width for the left filter panel.
 *
 * Hand-rolled rather than built on `react-resizable`: that package ships with
 * react-grid-layout but carries no `@types` entry here, and a one-axis splitter
 * is a dozen lines of pointer events either way.
 */
const STORAGE_KEY_PREFIX = 'filter-panel-width:';

/** Below this the MultiSelect labels wrap to uselessness. */
export const FILTER_PANEL_MIN_WIDTH = 220;
/** Above this the panel starts competing with the content column. */
export const FILTER_PANEL_MAX_WIDTH = 480;
/** Roughly the old hard-coded `20vw` on a typical laptop. */
const DEFAULT_WIDTH = 300;
/** Arrow-key increment, so the handle is usable without a pointer. */
export const FILTER_PANEL_KEYBOARD_STEP = 16;

function storageKey(dashboardId: string | null): string {
  return `${STORAGE_KEY_PREFIX}${dashboardId ?? 'unknown'}`;
}

function clampWidth(px: number): number {
  return Math.min(FILTER_PANEL_MAX_WIDTH, Math.max(FILTER_PANEL_MIN_WIDTH, Math.round(px)));
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
  /** Attach to the drag handle's `onPointerDown`. */
  beginResize: (event: React.PointerEvent<HTMLElement>) => void;
  /** Keyboard path for the same handle. */
  nudge: (deltaPx: number) => void;
}

export function useFilterPanelWidth(dashboardId: string | null): FilterPanelWidth {
  const [width, setWidth] = useState<number>(() => readWidth(dashboardId));
  const widthRef = useRef(width);

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

  const apply = useCallback((next: number) => {
    const clamped = clampWidth(next);
    if (clamped === widthRef.current) return;
    widthRef.current = clamped;
    setWidth(clamped);
  }, []);

  const commit = useCallback(() => {
    writeWidth(dashboardRef.current, widthRef.current);
  }, []);

  const beginResize = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      event.preventDefault();
      endDragRef.current?.(); // defensive: never stack two drags

      const startX = event.clientX;
      const startWidth = widthRef.current;
      let rafId: number | null = null;

      // The grid's own ResizeObserver keeps react-grid-layout in step, but
      // Plotly's `useResizeHandler` and AG Grid only reflow on a WINDOW resize
      // event. Pump one per frame while dragging — no width lock here, since
      // the panel follows the pointer rather than running a timed transition.
      const pumpResize = () => {
        rafId = null;
        window.dispatchEvent(new Event('resize'));
      };

      const onMove = (e: PointerEvent) => {
        apply(startWidth + (e.clientX - startX));
        if (rafId == null) rafId = requestAnimationFrame(pumpResize);
      };

      const endDrag = () => {
        endDragRef.current = null;
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', endDrag);
        window.removeEventListener('pointercancel', endDrag);
        if (rafId != null) cancelAnimationFrame(rafId);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        window.dispatchEvent(new Event('resize'));
        commit();
      };

      endDragRef.current = endDrag;
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

  return { width, beginResize, nudge };
}

export default useFilterPanelWidth;
