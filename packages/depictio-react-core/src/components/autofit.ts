import { useEffect, useRef, type DependencyList, type RefObject } from 'react';

/**
 * The contract between a tile that knows how tall its content is and the grid
 * that decides how tall the tile gets to be.
 *
 * Emitted on every change to a tile's content height, so the grid can size the
 * tile to what it holds instead of the other way round. A CustomEvent rather
 * than a prop: the only path from a renderer to DashboardGrid runs through
 * ComponentRenderer, and threading a measurement callback through every
 * renderer to serve two of them is not worth it. The grid already listens for
 * panel events this way.
 */
export const AUTOFIT_EVENT = 'depictio:autofit';

export interface AutofitDetail {
  index: string;
  /** Height, in px, the tile has to offer for this component's content to fit.
   *  A property of the content, never of the tile it currently sits in. */
  height: number;
}

/**
 * Last height published per component index.
 *
 * The event alone is not enough: React runs a child's effects before its
 * parent's, so a tile measures and dispatches before DashboardGrid has added
 * its listener, and that first measurement (the only one a tile whose content
 * never reflows will ever make) is dispatched to nobody. The grid seeds itself
 * from here on mount and listens for the rest.
 */
const measuredHeights = new Map<string, number>();

/** Every height measured so far, for a consumer mounting after the tiles. */
export const autofitHeights = (): ReadonlyMap<string, number> => measuredHeights;

/**
 * Observe `nodeRef` and publish the height its content needs under `index`.
 *
 * The node handed in must be height-auto: it is the whole reason this works.
 * An element that stretches to its tile reports the tile back, which is both
 * useless as a measurement and a feedback loop, since the grid answers a
 * measurement by resizing the tile.
 *
 * `toTileHeight` converts the raw content height into the height the tile has
 * to offer, for a renderer whose content sits inside a frame of its own.
 */
export function useAutofitHeight(
  index: string,
  nodeRef: RefObject<HTMLElement | null>,
  deps: DependencyList,
  toTileHeight?: (contentHeight: number) => number,
): void {
  // Read through a ref so an inline arrow at the call site cannot re-run the
  // effect: re-running it would tear the ResizeObserver down and rebuild it on
  // every render, and a card renders again on every bulk-compute tick.
  const toTileHeightRef = useRef(toTileHeight);
  toTileHeightRef.current = toTileHeight;

  useEffect(() => {
    const node = nodeRef.current;
    if (!node || !index || typeof ResizeObserver === 'undefined') return;
    const publish = () => {
      const content = node.scrollHeight;
      const height = toTileHeightRef.current ? toTileHeightRef.current(content) : content;
      // Only on change: the grid re-renders on receipt, which re-runs the
      // observer, and an unconditional dispatch would loop.
      if (measuredHeights.get(index) === height) return;
      measuredHeights.set(index, height);
      window.dispatchEvent(
        new CustomEvent<AutofitDetail>(AUTOFIT_EVENT, {
          detail: { index, height },
        }),
      );
    };
    // Measure once here rather than leaving it to the observer's own first
    // callback. This runs inside the child's effect, so the height is in
    // `measuredHeights` by the time the grid's effect takes its catch-up pass
    // over the map, and the tile is sized on the first render after mount
    // instead of a pass later.
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    return () => observer.disconnect();
    // The caller's `deps` are spread in so a renderer can force a re-measure on
    // a content change the observer cannot see; the observer covers the rest.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, nodeRef, ...deps]);
}
