import { createContext, useContext } from 'react';

/**
 * Where a genomic tile's "Open in genome browser" action goes: the genome
 * browser of the tab family, which can sit on another tab than the tile.
 *
 * Provided by the host app (viewer and editor), which holds the family's
 * documents; `null` when the family has no browser, which hides the action.
 */
export interface GenomeBrowserTarget {
  /** The tab family: the main tab's dashboard id. */
  familyId: string;
  /** The tab that holds the browser. */
  dashboardId: string;
  /** The browser tile's component index. */
  index: string;
  /** The link to that tab. */
  href: string;
  /** Whether the browser is on the tab being shown, so there is no page load
   *  to cross and the locus goes out as an event. */
  here: boolean;
}

export const GenomeBrowserTargetContext = createContext<GenomeBrowserTarget | null>(null);

export function useGenomeBrowserTarget(): GenomeBrowserTarget | null {
  return useContext(GenomeBrowserTargetContext);
}
