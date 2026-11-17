import { useCurrentUser } from '../hooks/useCurrentUser';
import { chapterFor } from './chapters';
import { startChapter, startChapterAt } from './store';

/** Read once at load: the listing pages rewrite their query string
 *  (`lib/listingUrl.ts`), which drops the flag before the session answers. */
const NO_WALKTHROUGH_PARAM =
  typeof window !== 'undefined' &&
  new URLSearchParams(window.location.search).get('no-walkthrough') === '1';

/** The hard-disable gates of the coach. `CoachHost` renders nothing when this
 *  is true, and every manual trigger (the header compass, the Account
 *  settings section) reads it too, so a button never promises a tour the host
 *  will not draw.
 *
 *    1. `/auth` routes: nothing to tour on the sign-in form.
 *    2. `DEPICTIO_DEV_MODE=true`: local devs reload constantly.
 *    3. `DEPICTIO_WALKTHROUGH_DISABLED=true`: the deployment's kill switch
 *       (embedded iframes, staging, internal demos).
 *    4. `?no-walkthrough=1`: set by the screenshot pipeline and the e2e
 *       suite, so no card ever lands in a capture. */
export function shouldSuppressWalkthrough(isDevMode: boolean, walkthroughDisabled: boolean): boolean {
  if (typeof window === 'undefined') return false;
  if (window.location.pathname.startsWith('/auth')) return true;
  if (isDevMode) return true;
  if (walkthroughDisabled) return true;
  return NO_WALKTHROUGH_PARAM;
}

/** Why a tour trigger is disabled once tours are known to be off. One text
 *  for the header compass and the Account settings section. */
export const TOUR_UNAVAILABLE_REASON = 'Guided tours are turned off on this deployment';

export interface TourLauncher {
  /** Whether the host will draw a tour here (it is not suppressed). */
  available: boolean;
  /** Why the trigger is disabled, or null when it is available or the
   *  deployment's answer is still loading. */
  reason: string | null;
  label: string;
  start: () => void;
}

/** What a manual tour trigger needs. It starts this page's chapter; from a
 *  page without one (Account settings), the dashboards list's. */
export function useTourLauncher(): TourLauncher {
  const { user, isPublicMode, isDemoMode, isDevMode, walkthroughDisabled, loading } = useCurrentUser();
  const guest = (isPublicMode || isDemoMode) && (!user || Boolean(user.is_temporary));
  const persona = guest ? 'guest' : 'builder';
  const available = !loading && !shouldSuppressWalkthrough(isDevMode, walkthroughDisabled);
  return {
    available,
    reason: available || loading ? null : TOUR_UNAVAILABLE_REASON,
    label: guest ? 'Take the tour' : 'Take the tour of this page',
    start: () => {
      if (typeof window === 'undefined') return;
      if (chapterFor(window.location.pathname, persona)) startChapter();
      else startChapterAt(guest ? 'dashboards-guest' : 'dashboards-builder', '/dashboards');
    },
  };
}
