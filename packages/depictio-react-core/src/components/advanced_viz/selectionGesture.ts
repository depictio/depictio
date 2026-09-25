/**
 * Only a gesture may empty a selection.
 *
 * Each `Plotly.react` re-applies the drawn box or lasso to the new traces and
 * emits `plotly_selected` again. On WebGL traces, and whenever the traces are
 * handed over as a fresh array, that re-selection comes back with no points:
 * unguarded, the filter a gesture just set is cleared by the very re-render it
 * caused, about a second later. `plotly_selecting` fires while a box or lasso
 * is being dragged and never on a re-render, so it tells the two apart.
 *
 * A gesture that catches nothing still clears (an empty box is a deliberate
 * "select nothing"), and `plotly_deselect` (a double click) is untouched.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export interface SelectionEventLike {
  points?: unknown[];
}

/** Whether `event` should reach the renderer's selection handler. */
export function acceptSelectionEvent(
  event: SelectionEventLike | null | undefined,
  fromGesture: boolean,
): boolean {
  const n = event?.points?.length ?? 0;
  return n > 0 || fromGesture;
}

/**
 * Wrap a `plotly_selected` handler so that a zero-point event with no gesture
 * behind it is dropped. Returns the `onSelecting` / `onSelected` pair to hand
 * to the Plot; the pair is stable for the life of the component.
 */
export function useGestureGuardedSelection<E extends SelectionEventLike>(
  onSelected: ((event: E) => void) | undefined,
): { onSelecting: (() => void) | undefined; onSelected: ((event: E) => void) | undefined } {
  const gestureInProgress = useRef(false);
  const latest = useRef(onSelected);
  latest.current = onSelected;

  const onSelecting = useCallback(() => {
    gestureInProgress.current = true;
  }, []);
  const guarded = useCallback((event: E) => {
    const fromGesture = gestureInProgress.current;
    gestureInProgress.current = false;
    if (!acceptSelectionEvent(event, fromGesture)) return;
    latest.current?.(event);
  }, []);

  return onSelected
    ? { onSelecting, onSelected: guarded }
    : { onSelecting: undefined, onSelected: undefined };
}

/**
 * The revision Plotly keys its selected points on, bumped when the dashboard
 * drops this component's selection from outside the plot.
 *
 * Plotly keeps `selectedpoints` (and the dimming of everything else) across
 * `Plotly.react` for as long as `layout.selectionrevision` is unchanged, which
 * is what lets a lasso survive the re-render it causes. It also means that
 * saving the selection as a group, or clearing it from the filter summary,
 * leaves the plot dimmed to its last lasso with nothing selected any more. A
 * true-to-false step on `active` (the selection was in the filters, now it is
 * not) is that outside clear: the revision moves and Plotly forgets the
 * points. Zoom is keyed on `uirevision`, so it is untouched.
 */
export function nextSelectionRevision(revision: number, wasActive: boolean, active: boolean): number {
  return wasActive && !active ? revision + 1 : revision;
}

export function useSelectionRevision(active: boolean): number {
  const [revision, setRevision] = useState(0);
  const wasActive = useRef(active);
  useEffect(() => {
    setRevision((r) => nextSelectionRevision(r, wasActive.current, active));
    wasActive.current = active;
  }, [active]);
  return revision;
}
