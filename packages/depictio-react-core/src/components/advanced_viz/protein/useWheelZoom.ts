/**
 * Ctrl / Cmd + wheel zoom for the panels that scroll a canvas horizontally
 * (the MSA and the HMM logo). A plain wheel is left alone so the page and the
 * panel keep scrolling; a trackpad pinch arrives as a wheel event with
 * `ctrlKey` set, so it zooms the same way. The panels show the shared zoom
 * hint on first hover (components/zoomGate.ts).
 */

import { useCallback, useEffect, useLayoutEffect, useRef, type MutableRefObject, type RefObject } from 'react';

import { followsWindow, type ZoomSyncHandle, type ZoomWindow } from '../../../highlight/zoomSync';
import { isZoomWheel } from '../../zoomGate';
import { useZoomGate } from '../../zoomGateDom';
import { followerWidth, type ZoomAxis } from './zoomAxis';

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
  /** Zoom sync with the view's other residue tiles; null or omitted: none. */
  sync?: WheelZoomSync | null;
}

/** A panel's side of zoom sync (see highlight/zoomSync.ts). */
export interface WheelZoomSync extends ZoomSyncHandle {
  /** The panel's axis at the width now drawn. */
  axis: ZoomAxis;
  /** The width the panel fits at (what its slider's 0 draws). */
  fit: number;
  /** The width the caller asked for; 0 is fit. */
  requested: number;
  /** The panel has data and a width, so its axis means something. */
  ready: boolean;
  /** Px at the right of the viewport that hold no residue (a length label). */
  trailing?: number;
}

/**
 * Attach a non-passive wheel listener to `scrollRef`'s element that zooms the
 * column width on Ctrl / Cmd + wheel, about the column under the cursor.
 */
export function useModifierWheelZoom(
  scrollRef: RefObject<HTMLElement | null>,
  { value, setValue, min, max, gutter = 0, sync = null }: ModifierWheelZoomOptions,
): void {
  const opts = useRef<WheelZoomOptionsNow>({ value, setValue, min, max, gutter, sync });
  opts.current = { value, setValue, min, max, gutter, sync };
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

  // Declared after the wheel's layout effect, so a zoom's anchor scroll is in
  // place before the window it shows goes out.
  useResidueZoomSync(scrollRef, opts);
}

type WheelZoomOptionsNow = Required<Omit<ModifierWheelZoomOptions, 'setValue'>> &
  Pick<ModifierWheelZoomOptions, 'setValue'>;

/** Widths closer than this are the same width (followers round to 0.01 px). */
const WIDTH_EPS = 0.005;

/**
 * Zoom sync for one panel. The reader's moves go out (a width change from the
 * wheel or the slider, a horizontal scroll), and other tiles' windows come in
 * and are fitted to this panel's width. What this hook writes itself (a width
 * asked for to show a window, the scroll that follows it) never goes out, so
 * two tiles cannot chase each other's rounding.
 */
function useResidueZoomSync(
  scrollRef: RefObject<HTMLElement | null>,
  opts: MutableRefObject<WheelZoomOptionsNow>,
): void {
  const sync = opts.current.sync;
  const store = sync?.store ?? null;
  const requested = sync?.requested ?? 0;
  const ready = sync?.ready ?? false;
  const entity = sync?.peer.entity ?? null;
  const positionColumn = sync?.peer.positionColumn ?? null;
  const value = opts.current.value;
  // The scrollLeft last seen, written or published: a scroll event that
  // leaves it there (this hook's own write, a vertical scroll) is not the
  // reader's move.
  const lastLeft = useRef<number | null>(null);
  // A width asked for to show a window, and that window's left edge (null:
  // the source fits its axis, so scroll home).
  const applying = useRef<{ cw: number; start: number | null } | null>(null);
  const lastRequested = useRef(requested);

  const writeLeft = useCallback(
    (x: number) => {
      const el = scrollRef.current;
      if (!el) return;
      el.scrollLeft = Math.max(0, x);
      lastLeft.current = el.scrollLeft;
    },
    [scrollRef],
  );

  const publish = useCallback(
    (scrollOnly = false) => {
      const s = opts.current.sync;
      const el = scrollRef.current;
      if (!s || !el || !s.ready || !s.store.isEnabled()) return;
      const gridW = el.clientWidth - opts.current.gutter - (s.trailing ?? 0);
      if (!(gridW > 0)) return;
      const x0 = el.scrollLeft;
      lastLeft.current = x0;
      const start = s.axis.posAt(x0);
      // A scroll keeps the span in force on this axis. Measured instead, an
      // alignment's span would change as gap columns slide in and out of
      // view, and every follower would re-fit on a plain scroll.
      const held = s.store.current();
      const keep =
        scrollOnly &&
        held !== null &&
        !held.fit &&
        held.end > held.start &&
        (held.sourceIndex === s.peer.index || followsWindow(held, s.peer));
      s.store.publish({
        sourceIndex: s.peer.index,
        entity: s.peer.entity ?? undefined,
        positionColumn: s.peer.positionColumn ?? undefined,
        start,
        end: keep ? start + (held.end - held.start) : s.axis.posAt(x0 + gridW),
        // A fitted panel that still scrolls (a long alignment at its narrowest
        // column) shows a window, not its whole axis.
        fit: !(s.requested > 0) && el.scrollWidth <= el.clientWidth + 1,
        scrollOnly: keep,
      });
    },
    [scrollRef, opts],
  );

  // `join`: a tile arriving under a window fits it whole, scroll or not.
  const apply = useCallback(
    (w: ZoomWindow, join = false) => {
      const o = opts.current;
      const s = o.sync;
      const el = scrollRef.current;
      if (!s || !el || !s.ready || !o.setValue) return;
      if (w.scrollOnly && !join && !w.fit) {
        applying.current = null;
        writeLeft(s.axis.xOf(w.start, o.value));
        return;
      }
      const gridW = el.clientWidth - o.gutter - (s.trailing ?? 0);
      if (!(gridW > 0)) return;
      const target = w.fit ? 0 : followerWidth(s.axis, w.start, w.end, gridW, s.fit, o.max);
      if (target === null) return;
      const start = w.fit ? null : w.start;
      if (Math.abs(target - s.requested) < WIDTH_EPS) {
        applying.current = null;
        writeLeft(start === null ? 0 : s.axis.xOf(start, o.value));
        return;
      }
      applying.current = { cw: target, start };
      o.setValue(target);
    },
    [scrollRef, opts, writeLeft],
  );

  // A width landed: the one asked for to show a window (scroll to it), or the
  // reader's own (send it out).
  useLayoutEffect(() => {
    const s = opts.current.sync;
    if (!s) return;
    const a = applying.current;
    if (a && Math.abs(s.requested - a.cw) < WIDTH_EPS) {
      applying.current = null;
      lastRequested.current = s.requested;
      writeLeft(a.start === null ? 0 : s.axis.xOf(a.start, opts.current.value));
      return;
    }
    if (s.requested !== lastRequested.current) {
      lastRequested.current = s.requested;
      applying.current = null;
      publish();
    }
  }, [requested, value, opts, publish, writeLeft]);

  // The reader's horizontal scroll, once per frame.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !store) return undefined;
    let frame = 0;
    lastLeft.current = el.scrollLeft;
    const onScroll = () => {
      if (lastLeft.current !== null && Math.abs(el.scrollLeft - lastLeft.current) < 0.5) return;
      lastLeft.current = el.scrollLeft;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        publish(true);
      });
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      el.removeEventListener('scroll', onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [scrollRef, store, ready, publish]);

  // Other tiles' windows; the tile whose switch turned sync on sends its own.
  useEffect(() => {
    if (!store) return undefined;
    let wasOn = store.isEnabled();
    let seen = store.current();
    return store.subscribe(() => {
      const on = store.isEnabled();
      const turnedOn = on && !wasOn;
      wasOn = on;
      if (!on) return;
      const s = opts.current.sync;
      if (!s) return;
      if (turnedOn && store.leader() === s.peer.index) {
        publish();
        return;
      }
      const w = store.current();
      if (w === seen) return;
      seen = w;
      if (followsWindow(w, s.peer)) apply(w);
    });
  }, [store, opts, publish, apply]);

  // A tile that mounts, gets its data or changes entity while a window is in
  // force joins it.
  useEffect(() => {
    if (!store || !ready || !store.isEnabled()) return;
    const s = opts.current.sync;
    const w = store.current();
    if (s && followsWindow(w, s.peer)) apply(w, true);
  }, [store, ready, entity, positionColumn, opts, apply]);
}
