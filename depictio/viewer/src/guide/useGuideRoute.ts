import { useCallback, useEffect, useState } from 'react';

/**
 * The Guide's place in the URL: `?guide=1` on the tab it was opened from.
 *
 * A query flag rather than a path of its own, because the Guide is a view of
 * the tab the reader is on, not a separate page: the tab's dashboard stays
 * loaded underneath, so closing the Guide shows it again at once and "Show me"
 * can point at its real elements. The flag is still a real URL, so the Guide
 * can be bookmarked, shared, or reopened from history.
 *
 * Opening pushes a history entry, so the browser's Back closes it and returns
 * to the tab. Closing from inside the Guide pops that entry — but only when it
 * provably is the one this page pushed, from this tab:
 *
 * - The entry carries a token minted when the page loaded. A plain flag (what
 *   this used to store) survives a reload, a restored session and a trip
 *   through other tabs and back, and an entry reached that way has no tab of
 *   ours in front of it — `back()` from there left the tab, usually for the
 *   Overview, which is where readers come to a child tab from.
 * - The tab's own address is remembered with the token, and must still be the
 *   one in the address bar.
 * - A close already on its way back is not sent back a second time: two
 *   closes before the first `popstate` (a "Show me" straight after Esc, say)
 *   would otherwise walk two entries and land on the tab before this one.
 *
 * Anything else — a `?guide=1` link opened straight, a reload — closes by
 * rewriting the URL in place, which can never leave the tab.
 */

const PARAM = 'guide';
/** Marks the history entry this hook pushed, so close knows it may go back. */
const STATE_KEY = 'depictioGuide';
/** This page load's mark: an entry pushed by an earlier load is not ours. */
const PAGE_TOKEN = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

interface GuideEntry {
  token: string;
  /** The tab's address the entry was pushed from, flag excluded. */
  from: string;
}

/** Set between a `back()` and the `popstate` that answers it. */
let backPending = false;

function readOpen(): boolean {
  if (typeof window === 'undefined') return false;
  return new URLSearchParams(window.location.search).get(PARAM) === '1';
}

/** The current URL with the flag set or cleared, path-relative. */
function urlWithGuide(open: boolean): string {
  const url = new URL(window.location.href);
  if (open) url.searchParams.set(PARAM, '1');
  else url.searchParams.delete(PARAM);
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Whether the current entry is the one this page load pushed for the Guide. */
function isOwnEntry(): boolean {
  const entry = (window.history.state as Record<string, unknown> | null)?.[STATE_KEY];
  if (!entry || typeof entry !== 'object') return false;
  const { token, from } = entry as Partial<GuideEntry>;
  return token === PAGE_TOKEN && from === urlWithGuide(false);
}

/** The history state without our entry, for a URL rewritten in place. */
function stateWithoutGuide(): unknown {
  const state = window.history.state as Record<string, unknown> | null;
  if (!state || !(STATE_KEY in state)) return state;
  const { [STATE_KEY]: _dropped, ...rest } = state;
  return rest;
}

/** The Guide's URL for the tab the reader is on — for links to it. */
export function guideHref(): string {
  return typeof window === 'undefined' ? '' : urlWithGuide(true);
}

export interface GuideRoute {
  /** The Guide is showing (and enabled). */
  open: boolean;
  openGuide: () => void;
  closeGuide: () => void;
  /** Where the Guide lives, for an `<a href>` (middle-click opens it apart). */
  href: string;
}

/**
 * @param enabled - the author's switch. While off the flag is ignored, so an
 *   old bookmark lands on the tab rather than on a Guide that is not offered.
 */
export function useGuideRoute(enabled: boolean): GuideRoute {
  const [open, setOpen] = useState(readOpen);

  useEffect(() => {
    const onPop = () => {
      backPending = false;
      setOpen(readOpen());
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const openGuide = useCallback(() => {
    if (!readOpen()) {
      const entry: GuideEntry = { token: PAGE_TOKEN, from: urlWithGuide(false) };
      window.history.pushState(
        { ...(window.history.state ?? {}), [STATE_KEY]: entry },
        '',
        urlWithGuide(true),
      );
    }
    setOpen(true);
  }, []);

  const closeGuide = useCallback(() => {
    // Hidden at once rather than on the popstate a `back()` fires later:
    // "Show me" closes the Guide and points at the page straight after.
    setOpen(false);
    if (backPending || !readOpen()) return;
    if (isOwnEntry()) {
      backPending = true;
      window.history.back();
    } else {
      window.history.replaceState(stateWithoutGuide(), '', urlWithGuide(false));
    }
  }, []);

  return {
    open: enabled && open,
    openGuide,
    closeGuide,
    href: guideHref(),
  };
}
