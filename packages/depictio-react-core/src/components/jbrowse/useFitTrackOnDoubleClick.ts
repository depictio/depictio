import { useEffect } from 'react';
import { isAlive } from '@jbrowse/mobx-state-tree';

/** The tallest a double click fits a track to, pixels. */
export const FIT_TRACK_MAX_PX = 1200;

const CONTAINER_PREFIX = 'trackRenderingContainer-';

/**
 * The track id a rendering container belongs to, read off its test id
 * (`trackRenderingContainer-<viewId>-<trackId>`), or null.
 */
export function trackIdOfContainer(testId: string | undefined, viewId: string): string | null {
  const prefix = `${CONTAINER_PREFIX}${viewId}-`;
  return testId?.startsWith(prefix) ? testId.slice(prefix.length) || null : null;
}

/** The height that shows all of a track's content (`scrollHeight`), capped;
 *  null when it already does. */
export function fittedHeight(
  contentPx: number,
  height: number,
  maxPx: number = FIT_TRACK_MAX_PX,
): number | null {
  const target = Math.min(Math.ceil(contentPx), maxPx);
  return Math.abs(target - height) > 1 ? target : null;
}

interface Display {
  height: number;
  setHeight: (px: number) => unknown;
  layoutFeatures?: { values: () => Iterable<unknown> };
}

/** Room under the lowest feature for its name label, pixels. */
export const LABEL_PX = 16;

/** The bottom (px) of a feature track's lowest laid-out feature and its
 *  label, or 0 for a track without a layout (coverage, reads). */
export function layoutBottom(records: Iterable<unknown>): number {
  let bottom = 0;
  for (const r of records) {
    if (Array.isArray(r) && typeof r[3] === 'number') bottom = Math.max(bottom, r[3]);
  }
  return bottom > 0 ? bottom + LABEL_PX : 0;
}

/** How far above a track's bottom edge a double click still counts as on
 *  the handle, pixels. */
export const EDGE_PX = 8;
/** How far below it: the handle and the gap to the next track. */
export const BELOW_PX = 12;

/** The index of the box whose bottom edge `y` sits on (from `EDGE_PX` above
 *  it to `BELOW_PX` under it) and whose span holds `x`, nearest first; -1. */
export function edgeHit(
  boxes: ReadonlyArray<{ left: number; right: number; bottom: number }>,
  x: number,
  y: number,
): number {
  let best = -1;
  let bestGap = Infinity;
  boxes.forEach((b, i) => {
    if (x < b.left || x > b.right) return;
    const gap = y - b.bottom;
    if (gap < -EDGE_PX || gap > BELOW_PX) return;
    if (Math.abs(gap) < bestGap) {
      bestGap = Math.abs(gap);
      best = i;
    }
  });
  return best;
}

/** The rendering container of view `viewId` whose bottom edge (its handle,
 *  the last `EDGE_PX` of the track, or the gap under it) the double click
 *  hit, or null. Read off the geometry, not the target: the handle's inner
 *  elements and the gap between tracks are not the container's siblings. */
function containerOfEdge(event: MouseEvent, viewId: string): HTMLElement | null {
  const containers = Array.from(
    document.querySelectorAll<HTMLElement>(`[data-testid^="${CONTAINER_PREFIX}${viewId}-"]`),
  );
  const hit = edgeHit(
    containers.map((c) => c.getBoundingClientRect()),
    event.clientX,
    event.clientY,
  );
  return hit >= 0 ? containers[hit] : null;
}

/**
 * A double click on the resize handle under a track fits the track to its
 * content, as a double click on a column border does in a spreadsheet. The
 * handle sits under the track's rendering container; the last few pixels of
 * the track and the gap to the next one count too. JBrowse's own double
 * click (a zoom) is stopped there.
 */
export function useFitTrackOnDoubleClick(view: unknown): void {
  useEffect(() => {
    if (!view) return undefined;
    const onDoubleClick = (event: MouseEvent) => {
      if (!isAlive(view as Parameters<typeof isAlive>[0])) return;
      const viewId = String((view as { id?: string }).id ?? '');
      // Only this view's containers: another tile's view has its own hook.
      const container = viewId ? containerOfEdge(event, viewId) : null;
      if (!container) return;
      const trackId = trackIdOfContainer(container.dataset.testid, viewId);
      if (!trackId) return;
      const track = (view as { tracks: Array<{ configuration?: { trackId?: string }; displays?: unknown[] }> }).tracks.find(
        (t) => t.configuration?.trackId === trackId,
      );
      const display = track?.displays?.[0] as Display | undefined;
      if (!display || typeof display.setHeight !== 'function') return;
      // The layout says how tall the features stack; the DOM's scroll height
      // can lag it (or stand at the track's own height).
      const laidOut = display.layoutFeatures ? layoutBottom(display.layoutFeatures.values()) : 0;
      const target = fittedHeight(Math.max(laidOut, container.scrollHeight), display.height);
      // JBrowse zooms in on a double click in the view: the handle's is ours.
      event.preventDefault();
      event.stopPropagation();
      if (target != null) display.setHeight(target);
    };
    // On the document, capture phase: the view's box may mount after the
    // view, and the view's own double click (a zoom) must never see it.
    document.addEventListener('dblclick', onDoubleClick, true);
    return () => document.removeEventListener('dblclick', onDoubleClick, true);
  }, [view]);
}
