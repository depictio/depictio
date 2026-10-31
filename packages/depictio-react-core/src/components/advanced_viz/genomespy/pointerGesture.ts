/**
 * Telling a click from a drag on a `genome_view`'s axis.
 *
 * GenomeSpy emits its `click` event after any press and release on the canvas,
 * a drag included: it works out `clickWasDrag` (3 px or more) but only to skip
 * its own interaction, not the event. So a pan, or a brush drawn over a mark,
 * ended with a "click" on whatever mark lay under the pointer, which the tile
 * read as a pick: a selection filter and a new "open in browser" locus, in the
 * middle of a gesture that meant neither. And the brush's `commit` delivery
 * reports a plain click as an emptied (or zero-width) interval, which cleared
 * the region filter and zoomed the axis back out.
 *
 * Pure decisions here; `attachDragTracker` is the DOM side.
 */

/** Movement between press and release at or above which it was a drag. Same
 *  threshold as GenomeSpy's own `clickWasDrag`. */
export const DRAG_PX = 3;

/** A brush narrower than this share of the visible domain is a click that
 *  jittered, not a region (a few pixels on a normal axis). */
export const MIN_BRUSH_FRACTION = 0.005;

/** Whether a press at `down` and a release at `up` was a drag. */
export function isDrag(
  down: { x: number; y: number } | null,
  up: { x: number; y: number } | null,
  threshold = DRAG_PX,
): boolean {
  if (!down || !up) return false;
  return Math.hypot(up.x - down.x, up.y - down.y) >= threshold;
}

/**
 * The brushed interval worth publishing as a region filter, or `null` for
 * everything that is not a deliberate drag: an emptied brush (a click, or a
 * programmatic `clear()`), a zero-width one, one too narrow against the visible
 * `domain` (linearised, as {@link readScaleDomain} returns it; unknown means
 * any width above zero passes). Clearing a region is the tile's own business:
 * double-click, Escape, the badge's x.
 */
export function brushToPublish(
  interval: readonly number[] | null | undefined,
  domain: readonly [number, number] | null,
  minFraction = MIN_BRUSH_FRACTION,
): [number, number] | null {
  if (!interval || interval.length < 2) return null;
  const [a, b] = [Number(interval[0]), Number(interval[1])];
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const width = Math.abs(b - a);
  if (width <= 0) return null;
  if (domain) {
    const span = Math.abs(domain[1] - domain[0]);
    if (span > 0 && width / span < minFraction) return null;
  }
  return [Math.min(a, b), Math.max(a, b)];
}

/** The slice of the container the tracker listens on. */
export interface DragTarget {
  ownerDocument: {
    addEventListener: (type: string, fn: (e: MouseEvent) => void, capture: boolean) => void;
    removeEventListener: (type: string, fn: (e: MouseEvent) => void, capture: boolean) => void;
  };
  addEventListener: (type: string, fn: (e: MouseEvent) => void, options: { capture: boolean }) => void;
  removeEventListener: (type: string, fn: (e: MouseEvent) => void, options: { capture: boolean }) => void;
}

export interface DragTracker {
  /** True when the press-and-release that is ending (or just ended) moved. A
   *  `click` is dispatched after its `mouseup`, so this is current by then. */
  wasDrag: () => boolean;
  detach: () => void;
}

/**
 * Track whether the last primary-button press on `el` was a drag. The press is
 * read on the element, the release on the document, so a drag that ends outside
 * the canvas still counts.
 */
export function attachDragTracker(el: DragTarget): DragTracker {
  const doc = el.ownerDocument;
  let down: { x: number; y: number } | null = null;
  let dragged = false;
  const onDown = (e: MouseEvent) => {
    if (e.button !== 0) return;
    down = { x: e.clientX, y: e.clientY };
    dragged = false;
  };
  const onUp = (e: MouseEvent) => {
    if (!down) return;
    dragged = isDrag(down, { x: e.clientX, y: e.clientY });
    down = null;
  };
  el.addEventListener('mousedown', onDown, { capture: true });
  doc.addEventListener('mouseup', onUp, true);
  return {
    wasDrag: () => dragged,
    detach: () => {
      el.removeEventListener('mousedown', onDown, { capture: true });
      doc.removeEventListener('mouseup', onUp, true);
    },
  };
}
