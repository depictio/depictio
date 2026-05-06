import React from 'react';
import { Badge, Center } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCurrentUser } from '../hooks/useCurrentUser';

/**
 * Sidebar footer badge that surfaces public/demo deployments to the visitor.
 * Mirrors the public/demo branch of `_create_auth_mode_badge` in
 * `depictio/dash/layouts/sidebar.py` — visitors land with an auto-minted
 * temp user (so `authMode` stays 'standard' and `ProfileBadge` shows their
 * avatar), and without this hint there's no signal that they're not on a
 * personal account.
 *
 * Single-user and strict-unauthenticated modes already render their own
 * inline label inside `ProfileBadge`, so we skip those here to avoid
 * duplicating the mode chip in the footer.
 */
const AuthModeBadge: React.FC = () => {
  const { isPublicMode, isDemoMode, isSingleUserMode, authMode } = useCurrentUser();

  if (isSingleUserMode || authMode === 'unauthenticated') return null;

  if (isDemoMode) {
    return (
      <Center>
        <Badge
          variant="light"
          color="violet"
          size="lg"
          leftSection={<Icon icon="mdi:compass-outline" width={14} />}
          style={{ textTransform: 'none' }}
        >
          Demo Mode
        </Badge>
      </Center>
    );
  }

  if (isPublicMode) {
    return (
      <Center>
        <Badge
          variant="light"
          color="teal"
          size="lg"
          leftSection={<Icon icon="mdi:earth" width={14} />}
          style={{ textTransform: 'none' }}
        >
          Public Mode
        </Badge>
      </Center>
    );
  }

  return null;
};

export default AuthModeBadge;
