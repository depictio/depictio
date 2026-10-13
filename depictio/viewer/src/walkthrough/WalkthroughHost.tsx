import React, { useMemo } from 'react';

import Walkthrough from './Walkthrough';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { canGuestSignIn } from '../auth/guestSignIn';
import { buildPublicExplorerWalkthrough } from './steps/publicExplorer';
import { authBuilderWalkthrough } from './steps/authBuilder';
import { shouldSuppressWalkthrough } from './availability';

/** Selects which walkthrough to run for the current visitor:
 *
 *  - Public / demo deployments → explorer walkthrough.
 *  - Anyone else (logged-in users, single-user mode admins) → builder.
 *
 *  The host mounts both engines — only the one whose `enabled` is true will
 *  render anything, but mounting both lets the manual tour triggers' restart
 *  event reach either definition regardless of which one auto-ran originally.
 *
 *  Public walkthrough is built per-render from the live auth settings so the
 *  duplicate-to-temp-session step can quote the actual TTL the backend will
 *  honour. `useMemo` keeps the definition stable across renders that don't
 *  change those settings — otherwise `useWalkthrough` would treat each
 *  render as a new definition.
 *
 *  The hard-disable gates (`/auth`, dev mode, the kill switch,
 *  `?no-walkthrough=1`) live in `availability.ts`, shared with the manual
 *  triggers so a button is hidden exactly when this host renders nothing. */
const WalkthroughHost: React.FC = () => {
  const {
    user,
    googleOAuthEnabled,
    samlEnabled,
    isPublicMode,
    isDemoMode,
    isDevMode,
    walkthroughDisabled,
    temporaryUserExpiryHours,
    temporaryUserExpiryMinutes,
    loading,
  } = useCurrentUser();
  const isGuest = Boolean(user?.is_temporary);
  const canSignIn = canGuestSignIn({
    loading,
    isPublicMode,
    isDemoMode,
    isGuest,
    googleOAuthEnabled,
    samlEnabled,
  });
  const publicWalkthrough = useMemo(
    () =>
      buildPublicExplorerWalkthrough({
        expiryHours: temporaryUserExpiryHours,
        expiryMinutes: temporaryUserExpiryMinutes,
        canSignIn,
      }),
    [temporaryUserExpiryHours, temporaryUserExpiryMinutes, canSignIn],
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

export default WalkthroughHost;
