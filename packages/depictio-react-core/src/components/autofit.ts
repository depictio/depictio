import { useEffect, useRef, useState, type DependencyList, type RefObject } from 'react';

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

/**
 * Grid geometry, mirrored by every ResponsiveGridLayout that shows autofitted
 * tiles. Autofit turns a measured pixel height into a row count with these, so
 * a change here has to move with those props.
 */
export const GRID_ROW_PX = 100;
export const GRID_ROW_GAP_PX = 4;

/**
 * How many rows a tile has to span to offer `height` px.
 *
 * n rows span n*GRID_ROW_PX plus the (n-1) gaps between them, so the room a
 * span of n offers is 104n - 4. Inverting that is the whole conversion — any
 * padding added on top buys a few pixels of comfort at the price of a whole
 * empty row.
 */
export function rowsForHeight(height: number): number {
  return Math.max(1, Math.ceil((height + GRID_ROW_GAP_PX) / (GRID_ROW_PX + GRID_ROW_GAP_PX)));
}

/** The subset of `Layout` this module needs, so it does not depend on RGL. */
interface SizedItem {
  i: string;
  y: number;
  h: number;
}

/** The subset of a component's metadata this module needs. */
interface FittableMember {
  index: string;
  component_type?: string;
}

/**
 * Replace each stored height with the one the content measured, where there is
 * a measurement to use.
 *
 * Shared by every grid that renders fitted tiles: `DashboardGrid` for a tab's
 * own sections, `PersistentSectionsHost` for the pinned ones a sibling tab
 * owns. Those are two grids, and a rule that lived in only one of them meant a
 * text tile fitted itself on the tab that declared it and nowhere else.
 */
export function fitLayoutHeights<T extends SizedItem>(
  members: readonly FittableMember[],
  layouts: readonly T[],
  autoHeights: Readonly<Record<string, number>>,
  enabled = true,
): T[] {
  const fittedIds = new Set(
    enabled
      ? members
          .filter((m) => m.component_type === 'text' || m.component_type === 'card')
          .map((m) => m.index)
      : [],
  );
  const cardIds = new Set(members.filter((m) => m.component_type === 'card').map((m) => m.index));
  // A card answers to the tallest measurement taken on its row rather than to
  // its own. Cards are authored as a band across a row, and one of them growing
  // to fit a breakdown its neighbours don't have turns that band into a
  // staircase. Keyed on the stored `y`, i.e. the row as the author laid it out,
  // before packing moves anything.
  const cardRowDemand = new Map<number, number>();
  for (const l of layouts) {
    if (!cardIds.has(l.i) || !fittedIds.has(l.i)) continue;
    const measured = autoHeights[l.i];
    if (!measured) continue;
    cardRowDemand.set(l.y, Math.max(cardRowDemand.get(l.y) ?? 0, rowsForHeight(measured)));
  }
  return layouts.map((l) => {
    if (cardIds.has(l.i)) {
      const demand = cardRowDemand.get(l.y);
      // Cards grow, never shrink: a measurement says how much room the content
      // needs, not how much room the card is worth. A sparse card fitted to its
      // value alone would drop below the height its author gave it, and drop
      // out of line with the row it belongs to.
      const grown = demand ? Math.max(l.h, demand) : l.h;
      return grown === l.h ? l : { ...l, h: grown };
    }
    const measured = fittedIds.has(l.i) ? autoHeights[l.i] : undefined;
    if (!measured) return l;
    const rows = rowsForHeight(measured);
    return rows === l.h ? l : { ...l, h: rows };
  });
}

/**
 * Subscribe to every tile's published content height.
 *
 * React runs a child's effects before its parent's, so every tile has already
 * measured and dispatched by the time this listener exists. The catch-up pass
 * over `autofitHeights()` is what covers the common case — content that renders
 * once and never reflows — which would otherwise never reach a layout at all.
 */
export function useAutofitHeights(): Record<string, number> {
  const [heights, setHeights] = useState<Record<string, number>>({});
  useEffect(() => {
    const onMeasure = (event: Event) => {
      const detail = (event as CustomEvent<AutofitDetail>).detail;
      if (!detail?.index) return;
      setHeights((prev) =>
        prev[detail.index] === detail.height ? prev : { ...prev, [detail.index]: detail.height },
      );
    };
    window.addEventListener(AUTOFIT_EVENT, onMeasure);
    setHeights((prev) => {
      let next = prev;
      for (const [index, height] of autofitHeights()) {
        if (next[index] !== height) next = { ...next, [index]: height };
      }
      return next;
    });
    return () => window.removeEventListener(AUTOFIT_EVENT, onMeasure);
  }, []);
  return heights;
}
