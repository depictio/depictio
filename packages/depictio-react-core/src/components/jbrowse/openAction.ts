/**
 * The "Open in genome browser" action of a genomic tile: when it shows, and
 * what it does. Pure, so the rules are testable without a DOM.
 */
import type { GenomeBrowserTarget } from './browserTarget';
import { locusOfInterval, type GenomicInterval } from '../../highlight/genomicHover';
import { announcePendingLocus, writePendingLocus } from './pendingLocus';

/** Look of the action, stated once. The icon is one the bundled subset holds
 *  (the browser tile uses it for its own header). */
export const OPEN_IN_BROWSER_ACTION = {
  icon: 'tabler:dna',
  label: 'Open in genome browser',
} as const;

export type OpenActionState = 'hidden' | 'disabled' | 'enabled';

/**
 * `hidden` without a browser to go to, on a tile that cannot say where it is
 * looking (`reader` false, i.e. not a genomic tile) and on the browser tile
 * itself; `disabled` while none of the tile's sources gives a locus.
 */
export function openActionState(args: {
  target: GenomeBrowserTarget | null;
  reader: boolean;
  selfIndex: string;
  locus: string | null;
}): OpenActionState {
  const { target, reader, selfIndex, locus } = args;
  if (!target || !reader) return 'hidden';
  if (target.index === selfIndex) return 'hidden';
  return locus ? 'enabled' : 'disabled';
}

/**
 * Centre the genome browser of this tab on `interval`: a single position gets
 * a few hundred bases around it, a span a margin. The channel the "Open in
 * genome browser" action uses when the browser is on the page already (an
 * event), without the page jump: the reader clicked a row and is looking at
 * it. Nothing happens, and false comes back, when the browser is on another
 * tab (a row click must not navigate away) or the interval names no locus.
 */
export function centreGenomeBrowser(
  target: GenomeBrowserTarget | null | undefined,
  interval: GenomicInterval | null | undefined,
): boolean {
  if (!target || !target.here) return false;
  const locus = locusOfInterval(interval);
  if (!locus) return false;
  announcePendingLocus({
    familyId: target.familyId,
    dashboardId: target.dashboardId,
    index: target.index,
    locus,
    scroll: false,
  });
  return true;
}

/**
 * Go to `locus` in the target browser. On the same tab there is no page load
 * to cross, so the browser is told by event. On another tab the locus is
 * written for the family first, and the page navigates to the tab, whose
 * browser reads it once when it builds its view.
 */
export function openInGenomeBrowser(
  target: GenomeBrowserTarget,
  locus: string,
  io: { assign: (href: string) => void } = { assign: (href) => window.location.assign(href) },
): void {
  const pending = { dashboardId: target.dashboardId, index: target.index, locus };
  if (target.here) {
    announcePendingLocus({ familyId: target.familyId, ...pending });
    return;
  }
  writePendingLocus(target.familyId, pending);
  io.assign(target.href);
}
