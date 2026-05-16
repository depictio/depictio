import React from 'react';

import Walkthrough from './Walkthrough';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { publicExplorerWalkthrough } from './steps/publicExplorer';
import { authBuilderWalkthrough } from './steps/authBuilder';

/** Selects which walkthrough to run for the current visitor:
 *
 *  - Public / demo deployments → explorer walkthrough.
 *  - Anyone else (logged-in users, single-user mode admins) → builder.
 *
 *  The host mounts both engines — only the one whose `enabled` is true will
 *  render anything, but mounting both lets the ProfileBadge restart event
 *  reach either definition regardless of which one auto-ran originally. */
const WalkthroughHost: React.FC = () => {
  const { isPublicMode, isDemoMode, loading } = useCurrentUser();
  if (loading) return null;
  const isExplorer = isPublicMode || isDemoMode;
  return (
    <>
      <Walkthrough definition={publicExplorerWalkthrough} enabled={isExplorer} />
      <Walkthrough definition={authBuilderWalkthrough} enabled={!isExplorer} />
    </>
  );
};

export default WalkthroughHost;
