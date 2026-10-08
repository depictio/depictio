import { createContext, useContext } from 'react';

/**
 * Links from prose to a sibling tab, by name.
 *
 * A text body can say `[Community](tab:Community & Diversity)`. Tab ids are
 * minted at import and differ on every instance, so a YAML author — or a
 * template shipped for every nf-core pipeline — cannot write `/dashboard/<id>`.
 * The name is what the author knows; the app that holds the tab family turns
 * it into a link, and lends it the tab's own icon and colour so a link reads
 * as the tab it opens.
 */
export interface TabLinkTarget {
  href: string;
  /** The tab's dashboard id. Optional: a host that only links has no use for it. */
  dashboardId?: string;
  /** The tab's displayed name. */
  label: string;
  /** Iconify name or image path, as the tab declares it. */
  icon?: string | null;
  /** Mantine palette name or CSS colour. */
  color?: string | null;
  /** The tab's own one-line description (its subtitle), if it has one. */
  description?: string | null;
  /** The sidebar group the tab is listed under, or null when it has none. */
  group?: string | null;
}

/** Resolves a tab name (case-insensitive), or a tab's dashboard id, to its
 *  link; null if unknown. */
export type TabLinkResolver = (name: string) => TabLinkTarget | null;

export const TabLinkContext = createContext<TabLinkResolver | null>(null);

export function useTabLinkResolver(): TabLinkResolver | null {
  return useContext(TabLinkContext);
}

/** Normalised lookup key for a tab name. */
export function tabLinkKey(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, ' ');
}

/** A list item that is a tab link, optionally followed by what the tab answers. */
export interface TabTileItem {
  label: string;
  tab: string;
  /** Text after the link (`: …` or `— …`), or null to use the tab's own. */
  text: string | null;
}

const TAB_TILE = /^\[([^\]\n]+)\]\(tab:((?:[^()\n]|\([^()\n]*\))+)\)\s*(?:[:\u2014\u2013-]\s*(.*\S))?\s*$/;

/**
 * Reads a list item as a tab tile, or null when it is anything else. A list
 * renders as tiles only when every item reads, so prose that merely mentions a
 * tab stays a list.
 */
export function parseTabTile(item: string): TabTileItem | null {
  const m = TAB_TILE.exec(item.trim());
  if (!m) return null;
  return { label: m[1].trim(), tab: m[2].trim(), text: m[3] ? m[3].trim() : null };
}

/**
 * Whether a list is tab tiles of which not one is on this dashboard: every
 * item reads as a tile and no tile's tab resolves. Such a list draws nothing
 * (see TabTiles), and neither should the heading that announces it.
 */
export function tabTilesAllMissing(items: string[], resolveTab: TabLinkResolver): boolean {
  const tiles = items.map(parseTabTile);
  return (
    tiles.length > 0 &&
    tiles.every((tile) => tile !== null && resolveTab(tile.tab) === null)
  );
}

/**
 * How many columns a row of `count` tiles takes in `width` pixels: as many as
 * fit at `minPx`, then evened out so the last row is never one tile on its
 * own (five tiles where four fit go three and two, not four and one).
 */
export function balancedColumns(count: number, width: number, minPx: number, gapPx: number): number {
  if (count <= 0) return 1;
  const fit = Math.max(1, Math.floor((width + gapPx) / (minPx + gapPx)));
  const rows = Math.ceil(count / fit);
  return Math.ceil(count / rows);
}
