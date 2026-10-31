import { useEffect, useRef, useState, type RefObject } from 'react';

import { useAutofitValue, useTileChrome } from '../autofit';

/**
 * Let a genome browser tile's height follow its open tracks (`auto_height`).
 *
 * The view inside the host box is as tall as its tracks make it (the ruler, the
 * tracks at their heights, the resize handles): that natural height is what the
 * tile is asked to offer, plus what the tile spends around the host box (the
 * header, the density strip, the status bar). The grid sizes the tile to it
 * between 3 and 16 rows (`GENOME_FIT_TYPE`), so opening a track grows the tile
 * and closing one shrinks it; past the cap the host scrolls, as it always did.
 *
 * Needs "Fit tracks to the tile" off (the renderer turns it off), or the
 * tracks would stretch to the host and the host to the tracks.
 *
 * `inFullscreen` holds the last answer: the tile is the page then, with its
 * tracks stretched to it, which is not a height the grid should adopt.
 */
export function useJBrowseAutoHeight(
  index: string,
  hostRef: RefObject<HTMLElement | null>,
  enabled: boolean,
  ready: boolean,
  inFullscreen: boolean,
): void {
  const [contentPx, setContentPx] = useState<number | null>(null);
  useEffect(() => {
    const view = enabled && ready ? (hostRef.current?.firstElementChild as HTMLElement | null) : null;
    if (!view || typeof ResizeObserver === 'undefined') {
      setContentPx(null);
      return undefined;
    }
    const measure = () => {
      const next = Math.round(view.offsetHeight);
      // Held within 2 px: reflow churn must not republish the height.
      setContentPx((prev) => (prev !== null && Math.abs(prev - next) < 2 ? prev : next));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(view);
    return () => observer.disconnect();
  }, [hostRef, enabled, ready]);

  const chromePx = useTileChrome(hostRef, ready ? 1 : 0);
  const fit =
    enabled && contentPx !== null && contentPx > 0 && chromePx !== null
      ? Math.ceil(contentPx + chromePx)
      : null;
  const held = useRef<number | null>(null);
  const published = inFullscreen && enabled ? held.current : fit;
  held.current = published;
  useAutofitValue(index, published);
}
