import React from 'react';
import { Avatar, Button, Group, Loader, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCurrentUser } from '../hooks/useCurrentUser';
import { initialsOf, useMyAvatar } from './account';

/**
 * Profile badge — initials avatar + email-name for logged-in users; outlined
 * "Sign In" button otherwise. Mirrors the Dash sidebar footer avatar slot.
 *
 * The badge is a plain link to Account settings (`/profile`), where sign out,
 * password, CLI tokens and the guided tour live. No menu in between.
 */
const ProfileBadge: React.FC = () => {
  const { user, authMode, isPublicMode, isDemoMode, loading } = useCurrentUser();
  const avatarUrl = useMyAvatar();

  if (loading) {
    return <Loader size="xs" />;
  }

  if (!user && authMode === 'standard' && !isPublicMode && !isDemoMode) {
    return (
      <Button
        component="a"
        href="/auth/login"
        variant="light"
        color="gray"
        size="xs"
        leftSection={<Icon icon="mdi:login" width={14} />}
      >
        Sign In
      </Button>
    );
  }

  return (
    <Tooltip label="Account settings" withArrow openDelay={300}>
      <UnstyledButton
        component="a"
        href="/profile"
        style={{ color: 'inherit' }}
        aria-label="Account settings"
        data-testid="profile-badge"
      >
        {renderBadgeContent(user, authMode, avatarUrl)}
      </UnstyledButton>
    </Tooltip>
  );
};

type BadgeUser = { email: string } | null;

function renderBadgeContent(
  user: BadgeUser,
  authMode: string,
  avatarUrl: string | null,
): React.ReactElement {
  if (authMode === 'single_user') {
    return (
      <Group gap="xs" wrap="nowrap">
        <Icon icon="mdi:account-circle-outline" width={18} />
        <Text size="sm" c="dimmed">
          Single user mode
        </Text>
      </Group>
    );
  }
  if (authMode === 'unauthenticated') {
    return (
      <Group gap="xs" wrap="nowrap">
        <Icon icon="mdi:incognito" width={18} />
        <Text size="sm" c="dimmed">
          Unauthenticated mode
        </Text>
      </Group>
    );
  }
  if (!user) {
    return (
      <Group gap="xs" wrap="nowrap">
        <Icon icon="mdi:account-circle-outline" width={18} />
        <Text size="sm" c="dimmed">
          Guest
        </Text>
      </Group>
    );
  }
  const localPart = user.email.split('@')[0] || user.email;
  return (
    <Group gap="xs" wrap="nowrap">
      <Avatar size="sm" radius="xl" color="blue" src={avatarUrl} alt="">
        {initialsOf(user.email)}
      </Avatar>
      <Text size="sm" truncate maw={120}>
        {localPart}
      </Text>
    </Group>
  );
}

export default ProfileBadge;
