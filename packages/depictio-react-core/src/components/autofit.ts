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
 * Record `height` for `index` and tell the grids about it.
 *
 * The single write end of the channel: a DOM measurement (`useAutofitHeight`)
 * and a content demand (`publishContentDemand`) are the same statement about
 * the same tile, so they travel the same map and the same event. A second
 * channel would need a second merge rule in every consumer.
 */
function publishHeight(index: string, height: number): void {
  // Only on change: the grid re-renders on receipt, which re-runs the
  // observer, and an unconditional dispatch would loop.
  if (measuredHeights.get(index) === height) return;
  measuredHeights.set(index, height);
  window.dispatchEvent(new CustomEvent<AutofitDetail>(AUTOFIT_EVENT, { detail: { index, height } }));
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

  useEffect(() => {
    const node = nodeRef.current;
    if (!node || !index || typeof ResizeObserver === 'undefined') return;
    const publish = () => {
      const content = node.scrollHeight;
      publishHeight(index, toTileHeightRef.current ? toTileHeightRef.current(content) : content);
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

/** The room a span of `rows` offers, the inverse of `rowsForHeight`. */
export function heightForRows(rows: number): number {
  return Math.max(1, rows) * (GRID_ROW_PX + GRID_ROW_GAP_PX) - GRID_ROW_GAP_PX;
}

/**
 * What a tile says its content needs, in grid rows.
 *
 * Rows rather than pixels because the producers count things, not pixels: a
 * bar chart knows it has two categories, a table knows it shows twelve rows,
 * a faceted panel knows it has three facets. Each turns that into the rows it
 * wants; the conversion to pixels happens here, once, against the same grid
 * geometry every consumer converts back with.
 */
export interface ContentDemand {
  rows: number;
}

/**
 * Publish a content demand for `index`, in grid rows.
 *
 * The counterpart of `useAutofitHeight` for content that cannot be measured
 * off the DOM: a Plotly figure fills whatever box it is given, so its node
 * reports the tile back rather than what the content needs. Rows are converted
 * through `heightForRows` and travel the same map and event as a measurement,
 * so `fitLayoutHeights` has one rule to apply, not two.
 */
export function publishContentDemand(index: string, demand: ContentDemand): void {
  if (!index) return;
  const rows = Math.max(0, Math.round(demand?.rows ?? 0));
  // 0 rows means "no demand", the tile keeps its stored height. Worth an
  // event only for a tile that had one and lost it (a figure re-rendered on a
  // visu type that publishes none): it has a height to release. A tile that
  // never had one says nothing, so the dozen figures on a dashboard that makes
  // no demands cost the grid nothing.
  if (rows <= 0 && !measuredHeights.has(index)) return;
  publishHeight(index, rows > 0 ? heightForRows(rows) : 0);
}

/** Publish `demand` for as long as this component is mounted. */
export function useContentDemand(
  index: string | number | undefined,
  demand: ContentDemand | null,
): void {
  const rows = demand?.rows;
  useEffect(() => {
    if (index === undefined || index === null || index === '') return;
    publishContentDemand(String(index), { rows: rows ?? 0 });
  }, [index, rows]);
}

/** The subset of `Layout` this module needs, so it does not depend on RGL. */
interface SizedItem {
  i: string;
  y: number;
  h: number;
}

/** Whether a tile's height is the content's business (`auto`) or the author's
 *  (`fixed`). Stored on `stored_metadata.fit`, never on the layout item:
 *  react-grid-layout's `cloneLayoutItem` drops every key it does not know, so
 *  a flag carried there would not survive the first drag. */
export type FitMode = 'auto' | 'fixed';

/** The subset of a component's metadata this module needs. */
interface FittableMember {
  index: string;
  component_type?: string;
  fit?: FitMode | null;
  /** MultiQC only: which module / plot the tile shows. */
  selected_module?: string | null;
  selected_plot?: string | null;
}

/** The MultiQC general statistics table, the one MultiQC tile that is a table
 *  and not a figure. Policies and defaults are keyed on this instead of on
 *  `multiqc`, so it fits like a table while the figures keep their aspect. */
export const MULTIQC_GENERAL_STATS_FIT_TYPE = 'multiqc_general_stats';

/** The key a component's fit policy and default are looked up under. */
export function fitType(member: FittableMember): string {
  if (
    member.component_type === 'multiqc' &&
    (member.selected_plot === 'general_stats' || member.selected_module === 'general_stats')
  ) {
    return MULTIQC_GENERAL_STATS_FIT_TYPE;
  }
  return member.component_type ?? '';
}

/**
 * How far a type is allowed to fit, and in which direction. A type may be
 * allowed to grow, to shrink, both, or neither, and the bounds cap whichever
 * it is allowed to do.
 *
 * `shrink: false` is the rule for content that mounts late, anything behind
 * `LazyMount` or its own viewport gate. Such a tile publishes its demand when
 * the reader reaches it, and a shrink at that moment pulls the rest of the
 * page up under their eyes. Growing is safe: it pushes content down ahead of
 * where they are reading.
 *
 * The bounds are in grid rows and are a content rule, not a layout one: an
 * author who stored a taller tile keeps it (see `fitLayoutHeights`).
 */
interface FitPolicy {
  min: number;
  max: number;
  grow: boolean;
  shrink: boolean;
}

const FIT_POLICIES: Readonly<Record<string, FitPolicy>> = {
  text: { min: 1, max: 12, grow: true, shrink: true },
  card: { min: 1, max: 4, grow: true, shrink: false },
  // A table that holds more rows than fit does not want a taller tile: AG Grid
  // pages and scrolls, and a dashboard is not the place to read a hundred rows
  // at once. A table that holds six is the case worth fixing, it should not
  // sit in a box built for a hundred. So: shrink to the content, never grow
  // past the height the author chose.
  table: { min: 2, max: 12, grow: false, shrink: true },
  [MULTIQC_GENERAL_STATS_FIT_TYPE]: { min: 2, max: 12, grow: false, shrink: true },
  figure: { min: 2, max: 12, grow: true, shrink: true },
  advanced_viz: { min: 3, max: 16, grow: true, shrink: false },
};

/**
 * What `fit` means when a component does not carry one.
 *
 * Text, cards, tables (the MultiQC general statistics table included) and
 * advanced viz answer to their content. Figures and MultiQC plots do not: their
 * aspect ratio is an authoring decision, so they hold the height the YAML gave
 * them unless the author opts in with `layout: {fit: auto}`. Every other type
 * has no policy and is never fitted.
 */
const DEFAULT_FIT: Readonly<Record<string, FitMode>> = {
  text: 'auto',
  card: 'auto',
  table: 'auto',
  [MULTIQC_GENERAL_STATS_FIT_TYPE]: 'auto',
  advanced_viz: 'auto',
  figure: 'fixed',
  multiqc: 'fixed',
};

/** The `fit` a component actually has, default included. */
export function effectiveFit(componentType?: string, fit?: FitMode | null): FitMode {
  if (fit === 'auto' || fit === 'fixed') return fit;
  return DEFAULT_FIT[componentType ?? ''] ?? 'fixed';
}

/** Whether this component's height follows its content. False for a tile the
 *  user has sized by hand, for a type with no policy, and for everything when
 *  the dashboard has autofit switched off. */
export function isAutofitted(member: FittableMember): boolean {
  const type = fitType(member);
  return effectiveFit(type, member.fit) === 'auto' && FIT_POLICIES[type] !== undefined;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * Replace each stored height with the one the content asked for, where there is
 * a measurement or a demand to use.
 *
 * Shared by every grid that renders fitted tiles: `DashboardGrid` for a tab's
 * own sections, `PersistentSectionsHost` for the pinned ones a sibling tab
 * owns. Those are two grids, and a rule that lived in only one of them meant a
 * text tile fitted itself on the tab that declared it and nowhere else.
 *
 * Three rules, in this order:
 *  - a `fixed` tile is never touched. That is the whole precedence chain  -
 *    YAML size < autofit < the size the user set by hand, which is what sets
 *    `fit: fixed` on the component.
 *  - an `auto` tile takes its own demand, clamped to its type's bounds, and
 *    only in the directions its type may move: a card grows, a table shrinks,
 *    a text tile does both.
 *  - every tile on a row then takes the tallest answer given on that row, so a
 *    band of tiles stays a band. A `fixed` tile joins in with its stored
 *    height: it is the one height on the row nothing can talk out of. A tile
 *    whose type caps it below that height stays at its own instead of growing
 *    into a box it cannot fill.
 *
 * Rows are keyed on the stored `y`, i.e. the row as the author laid it out,
 * before any packing moves things.
 */
export function fitLayoutHeights<T extends SizedItem>(
  members: readonly FittableMember[],
  layouts: readonly T[],
  autoHeights: Readonly<Record<string, number>>,
  enabled = true,
): T[] {
  // `enabled: false` is the dashboard-level opt-out and the only way back to
  // stored-height-only layout, so it has to be a true no-op.
  if (!enabled) return [...layouts];

  const byId = new Map<string, FittableMember>();
  for (const m of members) byId.set(m.index, m);

  /** The rows a type would let this tile have, its author's height included:
   *  a taller stored tile is an authoring decision, not a violation. */
  const bounds = (member: FittableMember, stored: number) => {
    const policy = FIT_POLICIES[fitType(member)]!;
    return {
      min: policy.min,
      max: Math.max(policy.max, stored),
      grow: policy.grow,
      shrink: policy.shrink,
    };
  };

  const ownRows = new Map<string, number>();
  const rowFloor = new Map<number, number>();
  for (const l of layouts) {
    const member = byId.get(l.i);
    const demand = member && isAutofitted(member) ? autoHeights[l.i] : undefined;
    if (!member || !demand) {
      // A fixed tile, or one that has not answered yet, holds its stored height
      //, and holds its row to it.
      rowFloor.set(l.y, Math.max(rowFloor.get(l.y) ?? 0, l.h));
      continue;
    }
    const { min, max, grow, shrink } = bounds(member, l.h);
    const wanted = clamp(rowsForHeight(demand), min, max);
    const rows = clamp(wanted, shrink ? min : l.h, grow ? max : l.h);
    ownRows.set(l.i, rows);
    rowFloor.set(l.y, Math.max(rowFloor.get(l.y) ?? 0, rows));
  }

  return layouts.map((l) => {
    const own = ownRows.get(l.i);
    if (own === undefined) return l;
    const { max } = bounds(byId.get(l.i)!, l.h);
    const floor = rowFloor.get(l.y) ?? own;
    // Level up to the row, but only as far as this type is allowed to go.
    // A tile that cannot reach its row's height does not grow halfway into a
    // mostly empty box for the sake of a row it was never going to fill: a
    // two-line card beside a six-row figure is the common case, and it looks
    // better at the height its content asked for.
    const rows = floor > max ? own : Math.max(own, floor);
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
