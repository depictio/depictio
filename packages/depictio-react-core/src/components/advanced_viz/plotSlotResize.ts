import { useEffect, type RefObject } from 'react';

/**
 * Keeps the figure inside an advanced-viz frame the size of its slot.
 *
 * `react-plotly.js`'s `useResizeHandler` only listens to `window` resize, so a
 * slot that changes size on its own (the controls strip appearing under the
 * title, the rail taking 220px of width, a counts row wrapping) left the SVG at
 * its old pixel size: clipped, or floating in blank space, until the next
 * window resize. The frame observes the slot and resizes the Plotly graphs in
 * it. GenomeSpy needs nothing: an embed whose size is `container` observes its
 * own container and re-lays itself out.
 */

/** Trailing debounce, long enough to coalesce one layout change's burst of
 *  observer callbacks (strip mounts, badges reflow, rail measures). */
export const PLOT_RESIZE_DEBOUNCE_MS = 50;

type ObserverCtor = new (callback: () => void) => {
  observe: (node: Element) => void;
  disconnect: () => void;
};

export interface ObserveResizeOptions {
  debounceMs?: number;
  /** Injected by the tests; defaults to the global `ResizeObserver`. */
  Observer?: ObserverCtor;
}

/**
 * Call `onResize` once the node has changed size and stayed that way for
 * `debounceMs`. The observer's first report (the size at mount) is the
 * baseline, not a change, and sub-pixel jitter is ignored, so a steady tile
 * never triggers a relayout. Returns the teardown.
 */
export function observeResize(
  node: Element,
  onResize: () => void,
  { debounceMs = PLOT_RESIZE_DEBOUNCE_MS, Observer }: ObserveResizeOptions = {},
): () => void {
  const Ctor =
    Observer ?? (typeof ResizeObserver === 'undefined' ? undefined : (ResizeObserver as ObserverCtor));
  if (!Ctor) return () => undefined;
  let last: { w: number; h: number } | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const observer = new Ctor(() => {
    const rect = node.getBoundingClientRect();
    const next = { w: rect.width, h: rect.height };
    const prev = last;
    last = next;
    if (!prev || (Math.abs(prev.w - next.w) < 1 && Math.abs(prev.h - next.h) < 1)) return;
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      onResize();
    }, debounceMs);
  });
  observer.observe(node);
  return () => {
    if (timer !== null) clearTimeout(timer);
    observer.disconnect();
  };
}

/**
 * Resize every Plotly graph under `root` to its container. Plotly is imported
 * lazily: the frame is on the boot path of every advanced-viz tile, and a tile
 * that never resizes should not have to wait on it. A graph that unmounted
 * between the observer and the import is skipped, not reported.
 */
export async function resizePlotsIn(root: Element): Promise<void> {
  const graphs = Array.from(root.querySelectorAll('.js-plotly-plot'));
  if (!graphs.length) return;
  const mod = (await import('plotly.js')) as unknown as {
    default?: { Plots?: { resize?: (gd: Element) => Promise<unknown> } };
    Plots?: { resize?: (gd: Element) => Promise<unknown> };
  };
  const resize = (mod.default ?? mod).Plots?.resize;
  if (!resize) return;
  await Promise.all(
    graphs.filter((gd) => gd.isConnected).map((gd) => resize(gd).catch(() => undefined)),
  );
}

/** The frame's hook: observe the plot slot, resize the figures in it. */
export function usePlotSlotResize(slot: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const node = slot.current;
    if (!node) return undefined;
    return observeResize(node, () => {
      void resizePlotsIn(node);
    });
  }, [slot]);
}
