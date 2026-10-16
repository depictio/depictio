/**
 * The zoom rule every figure follows: Ctrl / Cmd + wheel zooms, a plain wheel
 * scrolls the page, a two-finger pinch zooms on a touch screen. A trackpad
 * pinch reaches the browser as a wheel event with `ctrlKey` set, so it counts
 * as a zoom wheel without any special case.
 *
 * This file is the pure part: the decisions and the hint's bookkeeping, with
 * no DOM access, so they run in the node test environment. `zoomGateDom.ts`
 * wires them to elements.
 */

/** The slice of a wheel event the zoom test reads. */
export interface WheelLike {
  ctrlKey?: boolean;
  metaKey?: boolean;
}

/** Whether a wheel event is a zoom gesture (Ctrl / Cmd held, or a trackpad pinch). */
export function isZoomWheel(e: WheelLike): boolean {
  return Boolean(e.ctrlKey || e.metaKey);
}

export type WheelVerdict = 'zoom' | 'block' | 'pass';

/**
 * What the gate does with a wheel event: a zoom wheel goes through to the
 * library unchanged, a plain one is kept from it (`block`) unless it landed on
 * a part that scrolls by itself (`pass`, e.g. a long Plotly legend).
 */
export function wheelVerdict(e: WheelLike, onScrollablePart: boolean): WheelVerdict {
  if (isZoomWheel(e)) return 'zoom';
  return onScrollablePart ? 'pass' : 'block';
}

/** The slice of `navigator` the platform check reads. */
export interface PlatformInfo {
  platform?: string;
  userAgent?: string;
}

/** Whether the platform is a Mac (iPadOS reports a Mac platform too). */
export function isApplePlatform(nav?: PlatformInfo): boolean {
  const n = nav ?? (typeof navigator === 'undefined' ? undefined : navigator);
  if (!n) return false;
  return /mac|iphone|ipad|ipod/i.test(`${n.platform ?? ''} ${n.userAgent ?? ''}`);
}

/**
 * The name of the key that turns the wheel into a zoom on this platform:
 * the Command symbol on a Mac, `Ctrl` elsewhere. (Both work everywhere; the
 * hint shows the one the user's keyboard has.)
 */
export function zoomModifierLabel(nav?: PlatformInfo): string {
  return isApplePlatform(nav) ? '⌘' : 'Ctrl';
}

/** The hint's text: a pinch on a touch screen, the modifier + scroll otherwise. */
export function zoomHintText(touch: boolean, nav?: PlatformInfo): string {
  return touch ? 'Pinch to zoom' : `${zoomModifierLabel(nav)} + scroll to zoom`;
}

/** How long the hint stays up before it fades. */
export const ZOOM_HINT_VISIBLE_MS = 2500;

/**
 * How long the pointer rests on a figure before the hover hint shows. A mouse
 * sweeps over figures while the page scrolls under it, and that must not use
 * up the page's hint; a touch has no hover, so the first contact shows it at
 * once.
 */
export function zoomHintDelayMs(touch: boolean): number {
  return touch ? 0 : 300;
}

/**
 * After resting this long on a figure, a plain wheel over it reads as an
 * attempt to zoom rather than as the page scrolling past: the hint shows then
 * too. Shorter, and every figure the page scrolls under the pointer would
 * flash it.
 */
export const ZOOM_HINT_WHEEL_DWELL_MS = 600;

/** The wheel hint shows at most this often. */
export const ZOOM_HINT_REPEAT_MS = 4000;

/** What the hint policy knows when a trigger comes. */
export interface ZoomHintState {
  /** The reader has zoomed a figure with the modifier (or a pinch) in this browser. */
  learned: boolean;
  /** The hover hint has shown on this page load. */
  hoverShown: boolean;
  /** When the hint last showed (ms, any clock), null when it has not. */
  lastShownAt: number | null;
}

/**
 * Whether the hint shows now. Nothing once the reader has zoomed: they know.
 * Before that, it shows on the first figure the pointer rests on in each page
 * load (`hover`), and again whenever a plain wheel lands on a figure the
 * pointer has rested on (`wheel`, `restedMs` since it entered), at most every
 * `ZOOM_HINT_REPEAT_MS`: a reader who wheels on a figure and sees the page
 * scroll is told why at the moment they try.
 */
export function shouldShowZoomHint(
  trigger: 'hover' | 'wheel',
  state: ZoomHintState,
  now: number,
  restedMs = 0,
): boolean {
  if (state.learned) return false;
  if (trigger === 'hover') return !state.hoverShown;
  if (restedMs < ZOOM_HINT_WHEEL_DWELL_MS) return false;
  return state.lastShownAt === null || now - state.lastShownAt >= ZOOM_HINT_REPEAT_MS;
}

/** The viewport-space point to centre the hint on: the middle of the visible part. */
export function visibleCenter(
  rect: { left: number; top: number; right: number; bottom: number },
  viewport: { width: number; height: number },
): { x: number; y: number } | null {
  const left = Math.max(rect.left, 0);
  const right = Math.min(rect.right, viewport.width);
  const top = Math.max(rect.top, 0);
  const bottom = Math.min(rect.bottom, viewport.height);
  if (right <= left || bottom <= top) return null;
  return { x: (left + right) / 2, y: (top + bottom) / 2 };
}

/** The slice of `Storage` the once flag uses. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** localStorage key of the "reader has zoomed with the modifier" flag, which ends the hints. */
export const ZOOM_LEARNED_STORAGE_KEY = 'depictio.zoom.learned';

export interface OnceFlag {
  seen(): boolean;
  mark(): void;
}

/**
 * A flag kept in storage so it holds for the browser, with a copy in memory so
 * it still holds for the page when storage throws (a blocked or private
 * window).
 * `getStorage` is called on every access, because merely reading
 * `window.localStorage` can throw.
 */
export function createOnceFlag(
  key: string,
  getStorage: () => StorageLike | null | undefined,
): OnceFlag {
  let memory = false;
  return {
    seen() {
      if (memory) return true;
      try {
        if (getStorage()?.getItem(key) === '1') memory = true;
      } catch {
        /* storage unavailable: the in-memory copy is all there is */
      }
      return memory;
    },
    mark() {
      memory = true;
      try {
        getStorage()?.setItem(key, '1');
      } catch {
        /* quota, blocked or private window: the in-memory copy still holds */
      }
    },
  };
}

/**
 * What a drawn Plotly graph div exposes of itself, as far as the zoom hint
 * cares. Typed structurally so this file stays free of the plotly.js import.
 */
export interface PlotlyZoomProbe {
  _fullLayout?: ({ _has?: (type: string) => boolean } & Record<string, unknown>) | null;
  _context?: { scrollZoom?: unknown; staticPlot?: boolean } | null;
}

/** Whether `flag` is on in Plotly's `scrollZoom` config (a boolean or a `'a+b'` flaglist). */
function scrollZoomOn(scrollZoom: unknown, flag: string): boolean {
  if (scrollZoom === true) return true;
  return typeof scrollZoom === 'string' && scrollZoom.split('+').includes(flag);
}

/** Whether any cartesian axis of a drawn figure can still be zoomed (`fixedrange` off). */
function hasZoomableAxis(fullLayout: Record<string, unknown>): boolean {
  return Object.keys(fullLayout).some((k) => {
    if (!/^[xy]axis\d*$/.test(k)) return false;
    const axis = fullLayout[k] as { fixedrange?: boolean } | null;
    return Boolean(axis) && !axis?.fixedrange;
  });
}

/**
 * Whether a drawn Plotly figure zooms the way the hint says, so the hint is not
 * spent on a pie or a Sankey. A wheel zooms
 * a cartesian figure with a free axis and the 3D, geo and map subplots, when
 * the config's `scrollZoom` allows it. A pinch is only handled by the 3D, geo
 * and map subplots: Plotly draws a zoom box from a one-finger drag on a
 * cartesian figure and has no pinch of its own there.
 */
export function plotlyCanZoom(gd: PlotlyZoomProbe, touch: boolean): boolean {
  const fl = gd._fullLayout;
  const ctx = gd._context;
  if (!fl || !ctx || ctx.staticPlot || typeof fl._has !== 'function') return false;
  const has = (type: string) => Boolean(fl._has?.(type));
  const spatial = ['gl3d', 'geo', 'mapbox', 'map'].filter(has);
  if (touch) return spatial.length > 0;
  if (spatial.some((kind) => scrollZoomOn(ctx.scrollZoom, kind))) return true;
  return (
    (has('cartesian') || has('gl2d')) &&
    scrollZoomOn(ctx.scrollZoom, 'cartesian') &&
    hasZoomableAxis(fl)
  );
}
