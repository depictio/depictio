/**
 * Wheel scrolling for the lanes of a `genome_view` whose lanes scroll inside
 * the embed (fixed `lane_height`, see `BuiltGenomeSpec.scrolls`).
 *
 * GenomeSpy's scrollable viewport has a scrollbar thumb you can drag and
 * nothing else: no wheel, no keys. The tile's zoom gate also keeps a plain
 * wheel from the canvas (it is the page's to scroll), so over many lanes the
 * only way to move was the thumb, a few pixels wide. A plain wheel now moves
 * the lanes, and hands over to the page once they are at their end, so the
 * page never gets stuck under the pointer; Ctrl / Cmd + wheel still zooms.
 *
 * It reaches the thumb through `api.debug.getViewRoot()`, the embed's
 * developer hook for the internal view tree (the public API has no scroll
 * handle). Every access is guarded: a build without it just leaves the
 * scrollbar as the only way, as before.
 */
import type { EmbedResult } from '@genome-spy/core/types/embedApi.js';

/** The slice of GenomeSpy's `Scrollbar` view this reads and sets. */
export interface ScrollbarLike {
  name?: string;
  viewportOffset: number;
  setViewportOffset: (value: number, options?: { notify?: boolean; syncSmoother?: boolean }) => void;
  context?: { animator?: { requestRender?: () => void } };
}

/** Pixels a wheel delta means: `deltaMode` 1 is lines, 2 is pages. */
export function wheelPixels(deltaY: number, deltaMode = 0, pageHeight = 400): number {
  if (!Number.isFinite(deltaY)) return 0;
  if (deltaMode === 1) return deltaY * 16;
  if (deltaMode === 2) return deltaY * pageHeight;
  return deltaY;
}

/** The vertical scrollbars of the embed's views (none when nothing scrolls). */
export function verticalScrollbars(api: EmbedResult | null | undefined): ScrollbarLike[] {
  const found: ScrollbarLike[] = [];
  try {
    const root = api?.debug?.getViewRoot?.() as
      | { visit?: (cb: (view: unknown) => unknown) => void }
      | undefined;
    root?.visit?.((view) => {
      const v = view as Partial<ScrollbarLike> | null;
      if (v && v.name === 'scrollbar-vertical' && typeof v.setViewportOffset === 'function') {
        found.push(v as ScrollbarLike);
      }
    });
  } catch {
    return [];
  }
  return found;
}

/**
 * Scroll the lanes by `pixels` (positive: down). True when they moved, false
 * when there is nothing to scroll or they sit at the end in that direction,
 * the caller's cue to let the page have the wheel.
 */
export function scrollLanesBy(api: EmbedResult | null | undefined, pixels: number): boolean {
  if (!pixels) return false;
  let moved = false;
  for (const bar of verticalScrollbars(api)) {
    try {
      const before = bar.viewportOffset;
      // Clamped to the content by the scrollbar itself; the smoother is synced
      // so a drag of the thumb afterwards starts from here.
      bar.setViewportOffset(before + pixels, { notify: true, syncSmoother: true });
      if (bar.viewportOffset !== before) {
        moved = true;
        bar.context?.animator?.requestRender?.();
      }
    } catch {
      // A scrollbar this build lays out differently: leave it.
    }
  }
  return moved;
}
