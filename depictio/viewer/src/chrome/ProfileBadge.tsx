import React from 'react';
import { Avatar, Button, Group, Loader, Menu, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCurrentUser } from '../hooks/useCurrentUser';
import { dispatchWalkthroughRestart } from '../walkthrough';

/**
 * Profile badge — initials avatar + email-name for logged-in users; outlined
 * "Sign In" button otherwise. Mirrors the Dash sidebar footer avatar slot.
 *
 * Clicking the badge opens a small menu with "Profile" + "Take the tour"
 * (the restart entry point for the walkthrough engine). For unauthenticated
 * visitors the same menu lets them re-launch the explorer tour.
 */
const ProfileBadge: React.FC = () => {
  const { user, authMode, isPublicMode, isDemoMode, loading } = useCurrentUser();

  if (loading) {
    return <Loader size="xs" />;
  }

  if (!user && authMode === 'standard') {
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
          {renderBadgeContent(user, authMode)}
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item
          component="a"
          href="/profile-beta"
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

function renderBadgeContent(user: BadgeUser, authMode: string): React.ReactElement {
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
      <Avatar size="sm" radius="xl" color="blue">
        {computeInitials(localPart)}
      </Avatar>
      <Text size="sm" truncate maw={120}>
        {localPart}
      </Text>
    </Group>
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
