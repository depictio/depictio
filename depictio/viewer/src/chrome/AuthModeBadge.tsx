import React from 'react';
import { Badge, Center, ThemeIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCurrentUser } from '../hooks/useCurrentUser';

interface AuthModeBadgeProps {
  /** Icon only, label in a tooltip — for the sidebar footer row, where the
   *  chip shares a 250px rail with three other controls. */
  compact?: boolean;
}

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
const AuthModeBadge: React.FC<AuthModeBadgeProps> = ({ compact = false }) => {
  const { isPublicMode, isDemoMode, isSingleUserMode, authMode } = useCurrentUser();

  if (isSingleUserMode || authMode === 'unauthenticated') return null;

  const mode = isDemoMode
    ? { label: 'Demo Mode', color: 'violet', icon: 'mdi:compass-outline' }
    : isPublicMode
      ? { label: 'Public Mode', color: 'teal', icon: 'mdi:earth' }
      : null;
  if (!mode) return null;

  if (compact) {
    return (
      <Tooltip label={mode.label} withArrow>
        <ThemeIcon variant="light" color={mode.color} size="sm" aria-label={mode.label}>
          <Icon icon={mode.icon} width={14} />
        </ThemeIcon>
      </Tooltip>
    );
  }

  return (
    <Center>
      <Badge
        variant="light"
        color={mode.color}
        size="lg"
        leftSection={<Icon icon={mode.icon} width={14} />}
        style={{ textTransform: 'none' }}
      >
        {mode.label}
      </Badge>
    </Center>
  );
};

export default AuthModeBadge;
