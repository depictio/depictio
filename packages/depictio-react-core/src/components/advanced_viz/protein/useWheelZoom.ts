/**
 * Ctrl / Cmd + wheel zoom for the panels that scroll a canvas horizontally
 * (the MSA and the HMM logo). A plain wheel is left alone so the page and the
 * panel keep scrolling; a trackpad pinch arrives as a wheel event with
 * `ctrlKey` set, so it zooms the same way. The panels show the shared zoom
 * hint on first hover (components/zoomGate.ts).
 */

import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react';

import { isZoomWheel } from '../../zoomGate';
import { useZoomGate } from '../../zoomGateDom';

// The platform helpers live with the zoom gate now; kept importable from here.
export { isApplePlatform, zoomModifierLabel } from '../../zoomGate';

/** Wheel `deltaMode` 1 reports lines, not pixels. */
const LINE_PX = 16;
/** Zoom factor per wheel pixel: exp(-deltaY * K). */
const WHEEL_ZOOM_RATE = 0.0015;

/**
 * The column width after one wheel event: multiplicative, so a notch feels
 * the same at 2 px and at 30 px. Scrolling up (negative deltaY) zooms in.
 * `current` may be fractional; the result is clamped to `[min, max]`.
 */
export function zoomStep(
  current: number,
  deltaY: number,
  min: number,
  max: number,
  deltaMode = 0,
): number {
  const px = deltaMode === 1 ? deltaY * LINE_PX : deltaY;
  const next = current * Math.exp(-px * WHEEL_ZOOM_RATE);
  return Math.min(max, Math.max(min, next));
}

/**
 * The scrollLeft that keeps the column under the cursor where it was.
 * `scrollLeft` and `oldCw` describe the view before the zoom, `newCw` after.
 * `cursorX` is the pointer's offset in the scroll viewport; `gutter` is the
 * sticky label column on the left, which holds no scrolling content (a cursor
 * over it anchors on the first grid column instead).
 */
export function scrollLeftAfterZoom(
  scrollLeft: number,
  cursorX: number,
  gutter: number,
  oldCw: number,
  newCw: number,
): number {
  if (!(oldCw > 0) || !(newCw > 0)) return scrollLeft;
  const anchorX = Math.max(cursorX, gutter);
  const col = (scrollLeft + anchorX - gutter) / oldCw;
  return Math.max(0, col * newCw + gutter - anchorX);
}

export interface ModifierWheelZoomOptions {
  /** The column width now rendered, in px (the fitted width when the slider is at 0). */
  value: number;
  /** Receives a whole-pixel width. Omit to disable the zoom. */
  setValue?: (px: number) => void;
  min: number;
  max: number;
  /** Width of the sticky left gutter inside the scroll viewport, in px. */
  gutter?: number;
}

/**
 * Attach a non-passive wheel listener to `scrollRef`'s element that zooms the
 * column width on Ctrl / Cmd + wheel, about the column under the cursor.
 */
export function useModifierWheelZoom(
  scrollRef: RefObject<HTMLElement | null>,
  { value, setValue, min, max, gutter = 0 }: ModifierWheelZoomOptions,
): void {
  const opts = useRef({ value, setValue, min, max, gutter });
  opts.current = { value, setValue, min, max, gutter };
  // The fractional width a run of wheel events is accumulating, so small
  // deltas are not lost to rounding; re-synced when the width changes elsewhere.
  const acc = useRef(value);
  const lastEmitted = useRef(value);
  // The view before a run of wheel events (scroll, width) and the latest cursor
  // offset, applied once the new width has rendered.
  const pending = useRef<{ scrollLeft: number; cw: number; x: number } | null>(null);

  useLayoutEffect(() => {
    if (Math.round(acc.current) !== value) acc.current = value;
    lastEmitted.current = value;
    const el = scrollRef.current;
    const p = pending.current;
    if (!el || !p) return;
    pending.current = null;
    el.scrollLeft = scrollLeftAfterZoom(p.scrollLeft, p.x, opts.current.gutter, p.cw, value);
  }, [value, scrollRef]);

  // Only the hint: a plain wheel already scrolls the panel and the page here,
  // and a touch screen has no pinch on this canvas (the width slider is its zoom).
  useZoomGate(scrollRef, {
    block: false,
    canZoom: (touch) => !touch && Boolean(opts.current.setValue),
  });

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const o = opts.current;
      if (!o.setValue || !isZoomWheel(e)) return;
      // Only now: a plain wheel must keep scrolling, and a ctrl-wheel must not
      // zoom the whole page.
      e.preventDefault();
      acc.current = zoomStep(acc.current, e.deltaY, o.min, o.max, e.deltaMode);
      const next = Math.round(acc.current);
      if (next === lastEmitted.current) return;
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      if (!pending.current) {
        pending.current = { scrollLeft: el.scrollLeft, cw: lastEmitted.current, x };
      } else {
        pending.current.x = x;
      }
      lastEmitted.current = next;
      o.setValue(next);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [scrollRef]);
}
