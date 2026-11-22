/**
 * Whether the catalog preview draws a figure's automatic marks (on by
 * default, like a dashboard tile). The offline shim's `renderFigure` reads it
 * and takes the marks off with the payload's `marks_off` patch; the output
 * view's switch writes it and remounts the figure.
 */
import { useSyncExternalStore } from 'react';

let marksOn = true;
const listeners = new Set<() => void>();

export function previewMarksOn(): boolean {
  return marksOn;
}

export function setPreviewMarks(on: boolean): void {
  if (on === marksOn) return;
  marksOn = on;
  listeners.forEach((l) => l());
}

export function usePreviewMarks(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    previewMarksOn,
  );
}

/** Whether the figure of component `index` in the loaded payload has marks to take off. */
export function figureHasMarks(index: string | undefined): boolean {
  if (!index) return false;
  const figures = (
    window.__CATALOG_PREVIEW__ as { data?: { figures?: Record<string, { marks_off?: unknown }> } } | undefined
  )?.data?.figures;
  return Boolean(figures?.[index]?.marks_off);
}
