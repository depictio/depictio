import React from 'react';
import {
  Avatar,
  Button,
  Group,
  Loader,
  Menu,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCurrentUser } from '../hooks/useCurrentUser';
import { dispatchWalkthroughRestart } from '../walkthrough';

interface ProfileBadgeProps {
  /** Glyph only, identity in a tooltip — for the sidebar footer row. */
  compact?: boolean;
}

/**
 * Profile badge — initials avatar + email-name for logged-in users; outlined
 * "Sign In" button otherwise. Mirrors the Dash sidebar footer avatar slot.
 *
 * Clicking the badge opens a small menu with "Profile" + "Take the tour"
 * (the restart entry point for the walkthrough engine). For unauthenticated
 * visitors the same menu lets them re-launch the explorer tour.
 */
const ProfileBadge: React.FC<ProfileBadgeProps> = ({ compact = false }) => {
  const { user, authMode, isPublicMode, isDemoMode, loading } = useCurrentUser();

  if (loading) {
    return <Loader size="xs" />;
  }

  if (!user && authMode === 'standard' && !isPublicMode && !isDemoMode) {
    return (
      <Button
        component="a"
        href="/auth/login"
        variant="outline"
        color="blue"
        size="xs"
        leftSection={<Icon icon="mdi:login" width={14} />}
      >
        Sign In
      </Button>
    );
  }

  const tourId: 'public' | 'builder' =
    isPublicMode || isDemoMode ? 'public' : 'builder';
  const tourLabel = tourId === 'public' ? 'Take the demo tour' : 'Take the builder tour';

  return (
    <Menu shadow="md" width={210} position="bottom-end" withArrow>
      <Menu.Target>
        <UnstyledButton style={{ color: 'inherit' }}>
          {renderBadgeContent(user, authMode, compact)}
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item
          component="a"
          href="/profile"
          leftSection={<Icon icon="mdi:account-circle-outline" width={16} />}
        >
          Profile
        </Menu.Item>
        <Menu.Item
          leftSection={<Icon icon="mdi:compass-outline" width={16} />}
          onClick={() => dispatchWalkthroughRestart(tourId)}
        >
          {tourLabel}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
};

type BadgeUser = { email: string } | null;

/** Icon + label for each identity state. `compact` keeps the glyph and moves
 *  the label into a tooltip, so the footer row fits the 250px rail. */
function renderBadgeContent(
  user: BadgeUser,
  authMode: string,
  compact: boolean,
): React.ReactElement {
  const wrap = (glyph: React.ReactNode, label: string) =>
    compact ? (
      <Tooltip label={label} withArrow>
        <Group gap={0} wrap="nowrap" aria-label={label}>
          {glyph}
        </Group>
      </Tooltip>
    ) : (
      <Group gap="xs" wrap="nowrap">
        {glyph}
        <Text size="sm" c={user ? undefined : 'dimmed'} truncate maw={120}>
          {label}
        </Text>
      </Group>
    );

  if (authMode === 'single_user') {
    return wrap(<Icon icon="mdi:account-circle-outline" width={18} />, 'Single user mode');
  }
  if (authMode === 'unauthenticated') {
    return wrap(<Icon icon="mdi:incognito" width={18} />, 'Unauthenticated mode');
  }
  if (!user) {
    return wrap(<Icon icon="mdi:account-circle-outline" width={18} />, 'Guest');
  }
  const localPart = user.email.split('@')[0] || user.email;
  return wrap(
    <Avatar size="sm" radius="xl" color="blue">
      {computeInitials(localPart)}
    </Avatar>,
    localPart,
  );
}

function computeInitials(name: string): string {
  const cleaned = name.replace(/[^a-zA-Z0-9._-]/g, '');
  const parts = cleaned.split(/[._-]+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export default ProfileBadge;
