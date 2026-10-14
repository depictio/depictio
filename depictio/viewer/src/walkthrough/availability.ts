import { useCurrentUser } from '../hooks/useCurrentUser';
import { authBuilderWalkthrough } from './steps/authBuilder';
import { publicExplorerLabel } from './steps/publicExplorer';
import { dispatchWalkthroughRestart } from './useWalkthrough';

/** Gate 4, read once at load: the listing pages rewrite their query string
 *  (`lib/listingUrl.ts`), which drops the flag before the session answers. */
const NO_WALKTHROUGH_PARAM =
  typeof window !== 'undefined' &&
  new URLSearchParams(window.location.search).get('no-walkthrough') === '1';

/** The hard-disable gates of the walkthrough host. `WalkthroughHost` renders
 *  nothing when this is true, and every manual trigger (the header button, the
 *  Account settings section) reads it too, so a button never promises a tour
 *  the host will not draw.
 *
 *    1. `/auth` routes: the welcome step has no `route` filter, so without
 *       this guard `SpotlightBackdrop` paints a full-viewport dim layer on
 *       top of the sign-in form on first visit.
 *    2. `DEPICTIO_DEV_MODE=true`: local devs hot-reload constantly and don't
 *       want the tour relaunching on every version bump.
 *    3. `DEPICTIO_WALKTHROUGH_DISABLED=true`: explicit kill switch for
 *       deployments (embedded iframes, staging, internal demos) that just
 *       don't want the onboarding overlay at all.
 *    4. `?no-walkthrough=1` query flag: set by the screenshot pipeline so
 *       captured PNGs never contain the popover or backdrop, even if the
 *       walkthrough would otherwise auto-start for the seeded admin. */
export function shouldSuppressWalkthrough(isDevMode: boolean, walkthroughDisabled: boolean): boolean {
  if (typeof window === 'undefined') return false;
  if (window.location.pathname.startsWith('/auth')) return true;
  if (isDevMode) return true;
  if (walkthroughDisabled) return true;
  return NO_WALKTHROUGH_PARAM;
}

/** Why a tour trigger is disabled once the walkthrough is known to be off.
 *  One text for the header button and the Account settings section. */
export const TOUR_UNAVAILABLE_REASON = 'Guided tours are turned off on this deployment';

export interface TourLauncher {
  /** Whether the host will draw a tour here (it is not suppressed). */
  available: boolean;
  /** Why the trigger is disabled, or null when it is available or the
   *  deployment's answer is still loading (a disabled trigger with no reason
   *  yet, rather than a wrong one). */
  reason: string | null;
  /** What the trigger says: the definition's own label. */
  label: string;
  start: () => void;
}

/** What a manual tour trigger needs. Same pick as the host: public and demo
 *  deployments run the explorer tour, everyone else the builder tour. */
export function useTourLauncher(): TourLauncher {
  const { isPublicMode, isDemoMode, isDevMode, walkthroughDisabled, loading } = useCurrentUser();
  const id = isPublicMode || isDemoMode ? 'public' : 'builder';
  const available = !loading && !shouldSuppressWalkthrough(isDevMode, walkthroughDisabled);
  return {
    available,
    reason: available || loading ? null : TOUR_UNAVAILABLE_REASON,
    label: id === 'public' ? publicExplorerLabel : authBuilderWalkthrough.label,
    start: () => {
      dispatchWalkthroughRestart(id);
      // The explorer tour's first step has no `navigateTo` and the next one is
      // guarded to /dashboards, so started anywhere else it would stall on the
      // welcome card. The restart is already stored, so the reload resumes it.
      // (The builder tour's welcome step moves the user on by itself.)
      if (id === 'public' && !/^\/dashboards\/?$/.test(window.location.pathname)) {
        window.location.assign('/dashboards');
      }
    },
  };
}
