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
  /** The tab's displayed name. */
  label: string;
  /** Iconify name or image path, as the tab declares it. */
  icon?: string | null;
  /** Mantine palette name or CSS colour. */
  color?: string | null;
}

/** Resolves a tab name (case-insensitive) to its link, or null if unknown. */
export type TabLinkResolver = (name: string) => TabLinkTarget | null;

export const TabLinkContext = createContext<TabLinkResolver | null>(null);

export function useTabLinkResolver(): TabLinkResolver | null {
  return useContext(TabLinkContext);
}

/** Normalised lookup key for a tab name. */
export function tabLinkKey(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, ' ');
}
