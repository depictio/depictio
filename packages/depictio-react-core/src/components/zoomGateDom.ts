/**
 * Mounts the zoom rule (see zoomGate.ts) on an element: a plain wheel over it
 * never reaches the zoom code of the library drawn inside, and a small hint
 * says how to zoom (`shouldShowZoomHint`): on the first figure the pointer
 * rests on in a page load, and when a plain wheel lands on a figure the
 * pointer rests on, until the reader has zoomed once.
 *
 * The wheel listener sits on the figure's container, in the capture phase. A
 * capture listener on an ancestor runs before every listener of the target
 * below it (Plotly's drag layer, 3Dmol's canvas, a map's canvas), so stopping
 * propagation there keeps the event from all of them. It never calls
 * `preventDefault`, so the page still scrolls, and it is passive, so it never
 * delays that scroll. A zoom wheel goes through untouched: the library zooms
 * and calls `preventDefault` itself, which keeps the browser from zooming the
 * page.
 */

import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';

import { Z_LAYERS } from '../zLayers';
import './zoomGate.css';
import {
  createOnceFlag,
  shouldShowZoomHint,
  visibleCenter,
  wheelVerdict,
  zoomHintDelayMs,
  zoomHintText,
  ZOOM_LEARNED_STORAGE_KEY,
  ZOOM_HINT_VISIBLE_MS,
  type ZoomHintState,
} from './zoomGate';

export interface ZoomGateOptions {
  /**
   * Plain wheels that land inside an element matching this selector still
   * reach the library: a part that scrolls on its own (Plotly's legend).
   */
  passThrough?: string;
  /**
   * Keep plain wheels away from the library (default true). Pass false for a
   * surface that already ignores them and only wants the hint.
   */
  block?: boolean;
  /**
   * Whether the surface zooms with the given input (`touch`: a pinch, else a
   * wheel). The hint stays quiet when it does not, so it is not spent on a
   * figure that cannot zoom. Defaults to always.
   */
  canZoom?: (touch: boolean) => boolean;
  /**
   * The hover hint shows on this figure's first hover of every page load,
   * even when another figure had it already or the zoom is learned, and
   * stays `visibleMs`. For a figure whose gestures a reader must learn (a
   * genome axis, a genome browser).
   */
  ownHint?: { visibleMs?: number; extra?: string };
}

/** Fade length; keep in step with zoomGate.css. */
const FADE_MS = 180;

/** Set once the reader zooms a figure with the modifier: the hints end there. */
const learned = createOnceFlag(ZOOM_LEARNED_STORAGE_KEY, () =>
  typeof window === 'undefined' ? null : window.localStorage,
);
/** This page load's share of the hint state (see `shouldShowZoomHint`). */
let hoverShown = false;
let lastShownAt: number | null = null;

function hintState(): ZoomHintState {
  return { learned: learned.seen(), hoverShown, lastShownAt };
}

let hintEl: HTMLElement | null = null;
let hideTimer: ReturnType<typeof setTimeout> | undefined;
let clearTimer: ReturnType<typeof setTimeout> | undefined;

/**
 * The one hint element, created on first need. It sits in the page (empty)
 * before its text first changes, so a screen reader announces the change, and
 * moves into the fullscreen element when a tile is fullscreen, since nothing
 * outside that element is drawn then.
 */
function hintElement(): HTMLElement | null {
  if (typeof document === 'undefined') return null;
  if (!hintEl) {
    const el = document.createElement('div');
    el.className = 'depictio-zoom-hint';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.setAttribute('aria-atomic', 'true');
    el.style.zIndex = String(Z_LAYERS.tooltip);
    hintEl = el;
  }
  const host = document.fullscreenElement ?? document.body;
  if (hintEl.parentElement !== host) host.appendChild(hintEl);
  return hintEl;
}

/** Fades the hint out, then empties it so a stale message is not left for a screen reader. */
function dismissHint(): void {
  clearTimeout(hideTimer);
  const el = hintEl;
  if (!el || !el.hasAttribute('data-visible')) return;
  el.removeAttribute('data-visible');
  clearTimeout(clearTimer);
  clearTimer = setTimeout(() => {
    if (!el.hasAttribute('data-visible')) el.textContent = '';
  }, FADE_MS + 40);
}

function showHint(target: Element, touch: boolean, visibleMs = ZOOM_HINT_VISIBLE_MS, extra?: string): void {
  const el = hintElement();
  if (!el) return;
  const at = visibleCenter(target.getBoundingClientRect(), {
    width: window.innerWidth,
    height: window.innerHeight,
  });
  if (!at) return;
  clearTimeout(clearTimer);
  clearTimeout(hideTimer);
  el.style.left = `${at.x}px`;
  el.style.top = `${at.y}px`;
  el.textContent = extra ? `${zoomHintText(touch)} \u00b7 ${extra}` : zoomHintText(touch);
  // Flush the idle (transparent) style first, or a hint that was just added to
  // the page appears without fading in.
  void el.offsetWidth;
  el.setAttribute('data-visible', '');
  lastShownAt = Date.now();
  hideTimer = setTimeout(dismissHint, visibleMs);
}

function insideSelector(target: EventTarget | null, selector: string | undefined): boolean {
  if (!selector || typeof Element === 'undefined' || !(target instanceof Element)) return false;
  return target.closest(selector) !== null;
}

/** Mounts the gate on `el`; returns the function that removes it. */
export function attachZoomGate(el: HTMLElement, options: ZoomGateOptions = {}): () => void {
  if (typeof el.addEventListener !== 'function') return () => {};
  const { passThrough, block = true, canZoom, ownHint } = options;
  // With `ownHint`, this figure keeps its own "hover hint shown" flag and
  // shows it on every page load, as its gestures (drag, pan) are its own.
  let shownHere = false;
  const state = (): ZoomHintState =>
    ownHint ? { ...hintState(), learned: false, hoverShown: shownHere } : hintState();
  const show = (touch: boolean) => showHint(el, touch, ownHint?.visibleMs, ownHint?.extra);
  const zooms = (touch: boolean) => !canZoom || canZoom(touch);
  let dwell: ReturnType<typeof setTimeout> | undefined;
  // Since when the pointer rests on the figure; null while it is elsewhere.
  // Also set by a move, as a page scrolled under a still pointer may bring a
  // figure under it without an enter.
  let restingSince: number | null = null;

  const onWheel = (e: WheelEvent) => {
    const verdict = wheelVerdict(e, insideSelector(e.target, passThrough));
    if (verdict === 'zoom') {
      dismissHint();
      if (zooms(false)) learned.mark();
      return;
    }
    if (verdict === 'block' && block) e.stopPropagation();
    const now = Date.now();
    const rested = restingSince === null ? 0 : now - restingSince;
    if (shouldShowZoomHint('wheel', state(), now, rested) && zooms(false)) show(false);
  };

  const onEnter = (e: PointerEvent) => {
    const touch = e.pointerType === 'touch';
    restingSince = Date.now();
    if (!shouldShowZoomHint('hover', state(), restingSince) || !zooms(touch)) return;
    hintElement();
    clearTimeout(dwell);
    dwell = setTimeout(() => {
      if (!shouldShowZoomHint('hover', state(), Date.now()) || !zooms(touch)) return;
      hoverShown = true;
      shownHere = true;
      show(touch);
    }, zoomHintDelayMs(touch));
  };
  const onMove = () => {
    if (restingSince === null) restingSince = Date.now();
  };
  const onLeave = () => {
    clearTimeout(dwell);
    restingSince = null;
  };

  el.addEventListener('wheel', onWheel, { capture: true, passive: true });
  el.addEventListener('pointerenter', onEnter);
  el.addEventListener('pointermove', onMove, { passive: true });
  el.addEventListener('pointerleave', onLeave);
  return () => {
    clearTimeout(dwell);
    el.removeEventListener('wheel', onWheel, { capture: true });
    el.removeEventListener('pointerenter', onEnter);
    el.removeEventListener('pointermove', onMove);
    el.removeEventListener('pointerleave', onLeave);
  };
}

/**
 * {@link attachZoomGate} for a React-owned element. `canZoom` is read at hover
 * time, so a closure that changes between renders is fine; `passThrough` and
 * `block` are read when the element mounts.
 *
 * Checked after every render rather than once: a panel often draws a
 * placeholder first and its scrolling element only once the data is in, and
 * a gate attached on mount alone never found that element.
 */
export function useZoomGate(
  ref: RefObject<HTMLElement | null>,
  options: ZoomGateOptions = {},
): void {
  const latest = useRef(options);
  latest.current = options;
  const attached = useRef<{ el: HTMLElement; off: () => void } | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (attached.current?.el === el) return;
    attached.current?.off();
    attached.current = el
      ? {
          el,
          off: attachZoomGate(el, {
            passThrough: latest.current.passThrough,
            block: latest.current.block,
            canZoom: (touch) => latest.current.canZoom?.(touch) ?? true,
          }),
        }
      : null;
  });
  useEffect(
    () => () => {
      attached.current?.off();
      attached.current = null;
    },
    [],
  );
}
