import { useEffect, type RefObject } from 'react';
import Plotly from 'plotly.js';

/**
 * Re-flows the Plotly chart inside `ref` whenever that box and the chart
 * disagree on its size.
 *
 * `useResizeHandler` re-flows on a window `resize` only. A tile that autofit
 * shrinks or grows leaves the window as it was, so the chart stays at the size
 * it was drawn at: it overflows the new box, its last bars and its legend cut
 * off, or leaves a band under it.
 */
export function usePlotlyFollowsBox(ref: RefObject<HTMLElement | null>, active: boolean): void {
  useEffect(() => {
    const box = ref.current;
    if (!active || !box || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([entry]) => {
      const width = Math.round(entry.contentRect.width);
      const height = Math.round(entry.contentRect.height);
      if (width < 1 || height < 1) return;
      const gd = box.querySelector('.js-plotly-plot') as
        | (HTMLElement & { _fullLayout?: { width?: number; height?: number } })
        | null;
      const drawn = gd?._fullLayout;
      if (!gd || !drawn) return;
      if (Math.round(drawn.width ?? 0) === width && Math.round(drawn.height ?? 0) === height) return;
      void Promise.resolve(Plotly.Plots.resize(gd)).catch(() => {});
    });
    ro.observe(box);
    return () => ro.disconnect();
  }, [ref, active]);
}
