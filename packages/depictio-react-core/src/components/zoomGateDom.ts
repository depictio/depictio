/**
 * Mounts the zoom rule (see zoomGate.ts) on an element: a plain wheel over it
 * never reaches the zoom code of the library drawn inside, and the first time
 * a reader rests the pointer on it a small hint says how to zoom.
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
  visibleCenter,
  wheelVerdict,
  zoomHintDelayMs,
  zoomHintText,
  ZOOM_HINT_STORAGE_KEY,
  ZOOM_HINT_VISIBLE_MS,
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
}

/** Fade length; keep in step with zoomGate.css. */
const FADE_MS = 180;

/** The hint is shown once per browser. */
const hintSeen = createOnceFlag(ZOOM_HINT_STORAGE_KEY, () =>
  typeof window === 'undefined' ? null : window.localStorage,
);

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

function showHint(target: Element, touch: boolean): void {
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
  el.textContent = zoomHintText(touch);
  // Flush the idle (transparent) style first, or a hint that was just added to
  // the page appears without fading in.
  void el.offsetWidth;
  el.setAttribute('data-visible', '');
  hintSeen.mark();
  hideTimer = setTimeout(dismissHint, ZOOM_HINT_VISIBLE_MS);
}

function insideSelector(target: EventTarget | null, selector: string | undefined): boolean {
  if (!selector || typeof Element === 'undefined' || !(target instanceof Element)) return false;
  return target.closest(selector) !== null;
}

/** Mounts the gate on `el`; returns the function that removes it. */
export function attachZoomGate(el: HTMLElement, options: ZoomGateOptions = {}): () => void {
  if (typeof el.addEventListener !== 'function') return () => {};
  const { passThrough, block = true, canZoom } = options;
  let dwell: ReturnType<typeof setTimeout> | undefined;

  const onWheel = (e: WheelEvent) => {
    const verdict = wheelVerdict(e, insideSelector(e.target, passThrough));
    if (verdict === 'zoom') dismissHint();
    else if (verdict === 'block' && block) e.stopPropagation();
  };

  const onEnter = (e: PointerEvent) => {
    if (hintSeen.seen()) return;
    const touch = e.pointerType === 'touch';
    if (canZoom && !canZoom(touch)) return;
    hintElement();
    clearTimeout(dwell);
    dwell = setTimeout(() => {
      if (hintSeen.seen() || (canZoom && !canZoom(touch))) return;
      showHint(el, touch);
    }, zoomHintDelayMs(touch));
  };
  const onLeave = () => clearTimeout(dwell);

  el.addEventListener('wheel', onWheel, { capture: true, passive: true });
  el.addEventListener('pointerenter', onEnter);
  el.addEventListener('pointerleave', onLeave);
  return () => {
    clearTimeout(dwell);
    el.removeEventListener('wheel', onWheel, { capture: true });
    el.removeEventListener('pointerenter', onEnter);
    el.removeEventListener('pointerleave', onLeave);
  };
}

/**
 * {@link attachZoomGate} for a React-owned element. `canZoom` is read at hover
 * time, so a closure that changes between renders is fine; `passThrough` and
 * `block` are read when the element mounts.
 */
export function useZoomGate(
  ref: RefObject<HTMLElement | null>,
  options: ZoomGateOptions = {},
): void {
  const latest = useRef(options);
  latest.current = options;
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    return attachZoomGate(el, {
      passThrough: latest.current.passThrough,
      block: latest.current.block,
      canZoom: (touch) => latest.current.canZoom?.(touch) ?? true,
    });
  }, [ref]);
}
