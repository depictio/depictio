import { createContext, useContext } from 'react';

import type { StoredMetadata } from '../../api';
import { resolveFigureStyle } from '../figureStyle';
import type { TabLinkTarget } from '../tabLinks';

/**
 * The `minimal` figure style, for an advanced visualisation.
 *
 * A figure in that style is drawn as a landing page's tile: its title in the
 * card header beside an icon badge, a short subtitle inline, the metric cards'
 * frame instead of a border, and a link to the tab it summarises. An advanced
 * visualisation in a `minimal` section used to keep its own bordered frame and
 * a plain title, so it read as a different kind of thing from the figures
 * beside it.
 *
 * Only the frame changes. What each renderer draws inside it is its own
 * business — the plot overlay the server applies to figures has no
 * counterpart here — so the dispatch resolves the header once and hands it to
 * `AdvancedVizFrame` through this context instead of threading it through
 * every renderer.
 */
export interface AdvancedVizShowcase {
  subtitle: string;
  /** Iconify id of the header badge, or empty for none. */
  icon: string;
  /** Mantine palette name or CSS colour; the brand's primary when empty. */
  iconColor: string;
  /** The tab the visualisation summarises (`link: tab:<name>`). */
  source: TabLinkTarget | null;
}

export const AdvancedVizShowcaseContext = createContext<AdvancedVizShowcase | null>(null);

export function useAdvancedVizShowcase(): AdvancedVizShowcase | null {
  return useContext(AdvancedVizShowcaseContext);
}

/** The tab name a `link: tab:<name>` points at, or null for any other link. */
export function tabLinkName(link: unknown): string | null {
  return typeof link === 'string' && link.startsWith('tab:') ? link.slice(4) : null;
}

/** The showcase header for `metadata`, or null when it is drawn in the default
 *  style. `metadata.figure_style` is expected to carry its section's style
 *  already (see `withSectionFigureStyle`). */
export function advancedVizShowcase(
  metadata: Pick<StoredMetadata, 'figure_style' | 'subtitle' | 'icon_name' | 'icon_color'>,
  source: TabLinkTarget | null,
): AdvancedVizShowcase | null {
  if (resolveFigureStyle(metadata.figure_style) !== 'minimal') return null;
  const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');
  return {
    subtitle: str(metadata.subtitle),
    icon: str(metadata.icon_name),
    iconColor: str(metadata.icon_color),
    source,
  };
}
