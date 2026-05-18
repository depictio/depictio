import React, { useMemo } from 'react';

import Walkthrough from './Walkthrough';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { buildPublicExplorerWalkthrough } from './steps/publicExplorer';
import { authBuilderWalkthrough } from './steps/authBuilder';

/** Selects which walkthrough to run for the current visitor:
 *
 *  - Public / demo deployments → explorer walkthrough.
 *  - Anyone else (logged-in users, single-user mode admins) → builder.
 *
 *  The host mounts both engines — only the one whose `enabled` is true will
 *  render anything, but mounting both lets the ProfileBadge restart event
 *  reach either definition regardless of which one auto-ran originally.
 *
 *  Public walkthrough is built per-render from the live auth settings so the
 *  duplicate-to-temp-session step can quote the actual TTL the backend will
 *  honour. `useMemo` keeps the definition stable across renders that don't
 *  change those settings — otherwise `useWalkthrough` would treat each
 *  render as a new definition.
 *
 *  Four hard-disable gates short-circuit before either engine mounts:
 *    1. `/auth` routes — the welcome step has no `route` filter, so without
 *       this guard `SpotlightBackdrop` paints a full-viewport dim layer on
 *       top of the sign-in form on first visit.
 *    2. `DEPICTIO_DEV_MODE=true` — local devs hot-reload constantly and
 *       don't want the tour relaunching on every version bump.
 *    3. `DEPICTIO_WALKTHROUGH_DISABLED=true` — explicit kill switch for
 *       deployments (embedded iframes, staging, internal demos) that just
 *       don't want the onboarding overlay at all.
 *    4. `?no-walkthrough=1` query flag — set by the screenshot pipeline so
 *       captured PNGs never contain the popover or backdrop, even if the
 *       walkthrough would otherwise auto-start for the seeded admin. */
const WalkthroughHost: React.FC = () => {
  const {
    isPublicMode,
    isDemoMode,
    isDevMode,
    walkthroughDisabled,
    temporaryUserExpiryHours,
    temporaryUserExpiryMinutes,
    loading,
  } = useCurrentUser();
  const publicWalkthrough = useMemo(
    () =>
      buildPublicExplorerWalkthrough({
        expiryHours: temporaryUserExpiryHours,
        expiryMinutes: temporaryUserExpiryMinutes,
      }),
    [temporaryUserExpiryHours, temporaryUserExpiryMinutes],
  );
  if (loading) return null;
  if (shouldSuppressWalkthrough(isDevMode, walkthroughDisabled)) return null;
  const isExplorer = isPublicMode || isDemoMode;
  return (
    <>
      <Walkthrough definition={publicWalkthrough} enabled={isExplorer} />
      <Walkthrough definition={authBuilderWalkthrough} enabled={!isExplorer} />
    </>
  );
};

function shouldSuppressWalkthrough(isDevMode: boolean, walkthroughDisabled: boolean): boolean {
  if (typeof window === 'undefined') return false;
  if (window.location.pathname.startsWith('/auth')) return true;
  if (isDevMode) return true;
  if (walkthroughDisabled) return true;
  const params = new URLSearchParams(window.location.search);
  if (params.get('no-walkthrough') === '1') return true;
  return false;
}

export default WalkthroughHost;
