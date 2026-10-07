import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type DependencyList,
  type RefObject,
} from 'react';

import { ROW_SPLIT } from '../gridConfig';
import { resolveCardVariant } from './cardVariant';

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
 * A namespace for the heights published below it.
 *
 * Heights are keyed by component index, and the index is the dashboard's. A
 * second copy of a tile drawn elsewhere on the page (the dashboard Guide shows
 * the dashboard's own components) measures at its own width, and publishing
 * that under the tile's index would resize the tile on the canvas. Under a
 * scope, a renderer publishes as `<scope><index>`, and a grid under the same
 * scope reads back only its own: the canvas never sees the copy, nor the copy
 * the canvas. The default scope is empty, which is the key as it always was.
 */
const AutofitScopeContext = createContext('');

export const AutofitScope = AutofitScopeContext.Provider;

/** Record `height` for `key` and tell the grid, if it changed. 0 withdraws a
 *  measurement: the grid then falls back to the tile's stored height. */
function publishHeight(key: string, height: number): void {
  if ((measuredHeights.get(key) ?? 0) === height) return;
  if (height > 0) measuredHeights.set(key, height);
  else measuredHeights.delete(key);
  window.dispatchEvent(new CustomEvent<AutofitDetail>(AUTOFIT_EVENT, { detail: { index: key, height } }));
}

/**
 * Publish a height a renderer computed rather than measured, or null for none.
 *
 * For a tile whose content fills whatever box it is given (a figure laid out
 * to its tile), so that no element of it has a natural height to observe, yet
 * which knows the height it reads best at: the phylogeny summary, so many
 * rows of a comfortable pitch. Withdrawn on null and on unmount, so a tile
 * that leaves that mode (the summary switched back to the full tree) returns
 * to the height its author gave it.
 */
export function useAutofitValue(index: string, height: number | null): void {
  const scope = useContext(AutofitScopeContext);
  const key = scope + index;
  useEffect(() => {
    if (!index) return;
    publishHeight(key, height && height > 0 ? Math.ceil(height) : 0);
  }, [index, key, height]);
  useEffect(() => () => publishHeight(key, 0), [key]);
}

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
  const scope = useContext(AutofitScopeContext);

  useEffect(() => {
    const node = nodeRef.current;
    if (!node || !index || typeof ResizeObserver === 'undefined') return;
    const key = scope + index;
    const publish = () => {
      const content = node.scrollHeight;
      const height = toTileHeightRef.current ? toTileHeightRef.current(content) : content;
      // Only on change (see `publishHeight`): the grid re-renders on receipt,
      // which re-runs the observer, and an unconditional dispatch would loop.
      publishHeight(key, height);
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
  }, [scope, index, nodeRef, ...deps]);
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
export function rowsForHeight(height: number, rowPx: number = GRID_ROW_PX): number {
  return Math.max(1, Math.ceil((height + GRID_ROW_GAP_PX) / (rowPx + GRID_ROW_GAP_PX)));
}

/** A read-only grid's row: `ROW_SPLIT` of them and their gaps span one `GRID_ROW_PX`. */
export const SPLIT_ROW_PX = (GRID_ROW_PX - (ROW_SPLIT - 1) * GRID_ROW_GAP_PX) / ROW_SPLIT;

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
  /** A text tile's frame; framed tiles size as a row, like cards. */
  surface?: unknown;
  /** A card's style, its section's already folded in: a row of compact cards
   *  fits its content both ways. */
  variant?: unknown;
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
  /** The grid's row height: `SPLIT_ROW_PX` for a layout in read-only rows. */
  rowPx: number = GRID_ROW_PX,
): T[] {
  // An advanced viz is fitted only while it publishes a height, which only
  // one that knows its own (`useAutofitValue`) does; the others keep theirs.
  const fittedIds = new Set(
    enabled
      ? members
          .filter(
            (m) =>
              m.component_type === 'text' ||
              m.component_type === 'card' ||
              m.component_type === 'advanced_viz',
          )
          .map((m) => m.index)
      : [],
  );
  const cardIds = new Set(members.filter((m) => m.component_type === 'card').map((m) => m.index));
  // A card answers to the tallest measurement taken on its row rather than to
  // its own. Cards are authored as a band across a row, and one of them growing
  // to fit a breakdown its neighbours don't have turns that band into a
  // staircase. Keyed on the stored `y`, i.e. the row as the author laid it out,
  // before packing moves anything.
  // Framed text tiles (a row of finding cards) follow the same rule for the
  // same reason: one finding a line longer than the rest left a ragged band.
  // Unlike cards they still shrink — their height is their prose.
  const framedIds = new Set(
    members
      .filter((m) => m.component_type === 'text' && (m.surface === 'card' || m.surface === 'tinted'))
      .map((m) => m.index),
  );
  const framedRowDemand = new Map<number, number>();
  for (const l of layouts) {
    if (!framedIds.has(l.i) || !fittedIds.has(l.i)) continue;
    const measured = autoHeights[l.i];
    if (!measured) continue;
    framedRowDemand.set(
      l.y,
      Math.max(framedRowDemand.get(l.y) ?? 0, rowsForHeight(measured, rowPx)),
    );
  }
  // Rows on which every card is compact. A compact card exists to be low, and
  // the height an author's card was created with (sized for a default card)
  // would leave it a line of numbers floating in an empty tile. The whole row
  // has to be compact for it to shrink, because a default or headline card
  // beside it keeps its height, and the row would no longer line up.
  const variantOf = new Map(members.map((m) => [m.index, m.variant]));
  const compactRows = new Map<number, boolean>();
  for (const l of layouts) {
    if (!cardIds.has(l.i)) continue;
    const compact = resolveCardVariant(variantOf.get(l.i)) === 'compact';
    compactRows.set(l.y, (compactRows.get(l.y) ?? true) && compact);
  }
  const cardRowDemand = new Map<number, number>();
  for (const l of layouts) {
    if (!cardIds.has(l.i) || !fittedIds.has(l.i)) continue;
    const measured = autoHeights[l.i];
    if (!measured) continue;
    cardRowDemand.set(
      l.y,
      Math.max(cardRowDemand.get(l.y) ?? 0, rowsForHeight(measured, rowPx)),
    );
  }
  return layouts.map((l) => {
    if (cardIds.has(l.i)) {
      const demand = cardRowDemand.get(l.y);
      // Cards grow, never shrink: a measurement says how much room the content
      // needs, not how much room the card is worth. A sparse card fitted to its
      // value alone would drop below the height its author gave it, and drop
      // out of line with the row it belongs to. A row of nothing but compact
      // cards is the exception (see `compactRows`): it is all the same low
      // card, so it fits to the tallest of them either way.
      const grown = demand ? (compactRows.get(l.y) ? demand : Math.max(l.h, demand)) : l.h;
      return grown === l.h ? l : { ...l, h: grown };
    }
    if (framedIds.has(l.i)) {
      const demand = framedRowDemand.get(l.y);
      return !demand || demand === l.h ? l : { ...l, h: demand };
    }
    const measured = fittedIds.has(l.i) ? autoHeights[l.i] : undefined;
    if (!measured) return l;
    const rows = rowsForHeight(measured, rowPx);
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
  const scope = useContext(AutofitScopeContext);
  useEffect(() => {
    // Under a scope, only that scope's keys, read back as plain indices.
    const own = (key: string) => (key.startsWith(scope) ? key.slice(scope.length) : null);
    const onMeasure = (event: Event) => {
      const detail = (event as CustomEvent<AutofitDetail>).detail;
      const index = detail?.index ? own(detail.index) : null;
      if (!index) return;
      setHeights((prev) =>
        prev[index] === detail.height ? prev : { ...prev, [index]: detail.height },
      );
    };
    window.addEventListener(AUTOFIT_EVENT, onMeasure);
    setHeights((prev) => {
      let next = prev;
      for (const [key, height] of autofitHeights()) {
        const index = own(key);
        if (index && next[index] !== height) next = { ...next, [index]: height };
      }
      return next;
    });
    return () => window.removeEventListener(AUTOFIT_EVENT, onMeasure);
  }, [scope]);
  return heights;
}
