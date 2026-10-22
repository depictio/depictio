/**
 * What a wheel event over the genome browser should do.
 *
 * JBrowse handles the wheel itself: Ctrl + wheel (and a trackpad pinch, which
 * the browser reports as Ctrl + wheel) zooms, a horizontal swipe pans, and a
 * vertical one scrolls the track area, then each track's own rows. Inside a
 * dashboard that last case traps the reader: moving down the page over the
 * tile scrolls tracks instead. With the guard on:
 *
 * - `native`: Ctrl + wheel and horizontal swipes, left to JBrowse;
 * - `zoom`: Cmd + wheel, which JBrowse ignores, zooms like Ctrl + wheel;
 * - `page`: a plain vertical wheel scrolls the dashboard, never the tracks.
 *
 * With the guard off, only `zoom` is taken over and the rest stays JBrowse's.
 */
export type WheelIntent = 'native' | 'zoom' | 'page';

export interface WheelLike {
  deltaX: number;
  deltaY: number;
  deltaMode: number;
  ctrlKey: boolean;
  metaKey: boolean;
}

export function wheelIntent(event: WheelLike, guard: boolean): WheelIntent {
  if (event.ctrlKey) return 'native';
  if (event.metaKey) return 'zoom';
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return 'native';
  return guard ? 'page' : 'native';
}

const LINE_PX = 16;

/** `deltaY` in pixels: Firefox reports mouse wheels in lines (`deltaMode` 1)
 *  and paging devices in pages (2). */
export function wheelPixels(event: WheelLike, pagePx: number): number {
  if (event.deltaMode === 1) return event.deltaY * LINE_PX;
  if (event.deltaMode === 2) return event.deltaY * pagePx;
  return event.deltaY;
}

/** The bpPerPx multiplier for a wheel distance in pixels: positive (wheel
 *  down) zooms out, as JBrowse's own Ctrl + wheel does. One notch of a mouse
 *  wheel (~100 px) is about a 1.2x step. */
export function zoomFactor(pixels: number): number {
  return Math.exp(pixels * 0.002);
}
