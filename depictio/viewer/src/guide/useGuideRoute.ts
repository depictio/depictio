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
 * to the tab; closing from inside the Guide pops that same entry. A Guide that
 * was loaded straight from a `?guide=1` link has no entry of ours to pop, so
 * closing it rewrites the URL in place instead of leaving the site.
 */

const PARAM = 'guide';
/** Marks the history entry this hook pushed, so close knows it may go back. */
const STATE_KEY = 'depictioGuide';

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

/** The Guide's URL for the tab the reader is on — for links to it. */
export function guideHref(): string {
  return typeof window === 'undefined' ? '' : urlWithGuide(true);
}

export interface GuideRoute {
  /** The Guide is showing (and enabled). */
  open: boolean;
  openGuide: () => void;
  closeGuide: () => void;
  toggleGuide: () => void;
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
    const onPop = () => setOpen(readOpen());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const openGuide = useCallback(() => {
    if (!readOpen()) {
      window.history.pushState(
        { ...(window.history.state ?? {}), [STATE_KEY]: true },
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
    if (!readOpen()) return;
    if ((window.history.state as Record<string, unknown> | null)?.[STATE_KEY]) {
      window.history.back();
    } else {
      window.history.replaceState(window.history.state, '', urlWithGuide(false));
    }
  }, []);

  const toggleGuide = useCallback(() => {
    if (readOpen()) closeGuide();
    else openGuide();
  }, [openGuide, closeGuide]);

  return {
    open: enabled && open,
    openGuide,
    closeGuide,
    toggleGuide,
    href: guideHref(),
  };
}
