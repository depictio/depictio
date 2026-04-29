import React from 'react';
import { Anchor, Avatar, Button, Group, Loader, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useCurrentUser } from '../hooks/useCurrentUser';

/**
 * Profile badge — initials avatar + email-name for logged-in users; outlined
 * "Sign In" button otherwise. Mirrors the Dash sidebar footer avatar slot.
 */
const ProfileBadge: React.FC = () => {
  const { user, authMode, loading } = useCurrentUser();

  if (loading) {
    return <Loader size="xs" />;
  }

  if (authMode === 'single_user') {
    return (
      <Anchor
        href="/profile-beta"
        underline="never"
        style={{ color: 'inherit' }}
      >
        <Group gap="xs" wrap="nowrap">
          <Icon icon="mdi:account-circle-outline" width={18} />
          <Text size="sm" c="dimmed">
            Single user mode
          </Text>
        </Group>
      </Anchor>
    );
  }

  if (authMode === 'unauthenticated') {
    return (
      <Anchor
        href="/profile-beta"
        underline="never"
        style={{ color: 'inherit' }}
      >
        <Group gap="xs" wrap="nowrap">
          <Icon icon="mdi:incognito" width={18} />
          <Text size="sm" c="dimmed">
            Unauthenticated mode
          </Text>
        </Group>
      </Anchor>
    );
  }

  if (!user) {
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

  const localPart = user.email.split('@')[0] || user.email;
  const initials = computeInitials(localPart);

  return (
    <Anchor
      href="/profile-beta"
      underline="never"
      style={{ color: 'inherit' }}
    >
      <Group gap="xs" wrap="nowrap">
        <Avatar size="sm" radius="xl" color="blue">
          {initials}
        </Avatar>
        <Text size="sm" truncate maw={120}>
          {localPart}
        </Text>
      </Group>
    </Anchor>
  );
};

function computeInitials(name: string): string {
  const cleaned = name.replace(/[^a-zA-Z0-9._-]/g, '');
  const parts = cleaned.split(/[._-]+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export default ProfileBadge;
