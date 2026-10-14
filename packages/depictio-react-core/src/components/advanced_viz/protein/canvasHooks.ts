/**
 * React plumbing shared by the protein panels: the scroll viewport's size and
 * a redraw coalesced to one per animation frame. A pointer move or a scroll
 * redraws through refs; it never re-renders the panel.
 */

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';

/** Client size of `ref`'s element, kept current by a ResizeObserver. */
export function useViewSize(ref: RefObject<HTMLElement | null>): { w: number; h: number } {
  const [view, setView] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () =>
      setView((prev) =>
        prev.w === el.clientWidth && prev.h === el.clientHeight
          ? prev
          : { w: el.clientWidth, h: el.clientHeight },
      );
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return view;
}

/**
 * A stable `requestDraw` that runs the latest `draw` on the next animation
 * frame (at most once per frame), and a redraw whenever `draw` changes.
 */
export function useDrawScheduler(draw: () => void): () => void {
  const drawRef = useRef(draw);
  drawRef.current = draw;
  const frameRef = useRef<number | null>(null);
  const requestDraw = useCallback(() => {
    if (frameRef.current != null) return;
    if (typeof requestAnimationFrame === 'undefined') {
      drawRef.current();
      return;
    }
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      drawRef.current();
    });
  }, []);
  useEffect(() => {
    requestDraw();
  }, [draw, requestDraw]);
  useEffect(
    () => () => {
      if (frameRef.current != null && typeof cancelAnimationFrame !== 'undefined') {
        cancelAnimationFrame(frameRef.current);
      }
    },
    [],
  );
  return requestDraw;
}
