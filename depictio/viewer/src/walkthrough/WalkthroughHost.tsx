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
 *  render as a new definition. */
const WalkthroughHost: React.FC = () => {
  const {
    isPublicMode,
    isDemoMode,
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
  const isExplorer = isPublicMode || isDemoMode;
  return (
    <>
      <Walkthrough definition={publicWalkthrough} enabled={isExplorer} />
      <Walkthrough definition={authBuilderWalkthrough} enabled={!isExplorer} />
    </>
  );
};

export default WalkthroughHost;
