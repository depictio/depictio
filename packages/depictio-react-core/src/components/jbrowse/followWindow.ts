/**
 * Following the genomic window another tile publishes on the `viewWindow` bus
 * (a coverage track, another browser). Pure: given the window, the one on
 * screen and the assembly's name resolver, say where to navigate, or that
 * there is nothing to do.
 */
import type { ViewWindowEvent } from '../../highlight/viewWindow';

export interface CurrentWindow {
  entity: string;
  start: number;
  end: number;
}

/** The widest window a browser follows, in bases. Alignment tracks refuse a
 *  region over 1 Mb (JBrowse's SNPCoverageAdapter throws), and a navigator
 *  zoomed out on a whole contig publishes tens of megabases: a wider window is
 *  followed on its centre at this width. */
export const MAX_FOLLOW_SPAN = 1_000_000;

/** The locus string to navigate to for `win`, or null when the window names no
 *  contig the assembly knows, or the view already shows it (the echo of our own
 *  publish coming back from a tile that follows us). `canonical` maps any name
 *  of a contig to the assembly's canonical one, undefined when it has none. */
export function followTarget(
  win: Pick<ViewWindowEvent, 'entity' | 'entityAliases' | 'start' | 'end'>,
  current: CurrentWindow | null,
  canonical: (name: string) => string | undefined,
  maxSpan: number = MAX_FOLLOW_SPAN,
): string | null {
  if (!Number.isFinite(win.start) || !Number.isFinite(win.end) || win.end < win.start) return null;
  let start = win.start;
  let end = win.end;
  if (end - start > maxSpan) {
    const mid = Math.round((start + end) / 2);
    start = Math.max(0, mid - Math.floor(maxSpan / 2));
    end = start + maxSpan;
  }
  let refName: string | undefined;
  for (const name of [win.entity, ...(win.entityAliases ?? [])]) {
    refName = canonical(name);
    if (refName) break;
  }
  if (!refName) return null;
  if (current && current.entity === refName) {
    // Our own window is rounded outwards to whole bases, so a round trip can
    // come back a base or two off: that is the same window, not a new one.
    const slack = Math.max(2, Math.round((end - start) * 0.002));
    if (Math.abs(current.start - start) <= slack && Math.abs(current.end - end) <= slack) {
      return null;
    }
  }
  return `${refName}:${start}-${end}`;
}
