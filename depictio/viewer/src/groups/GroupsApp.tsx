import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  AppShell,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { fetchGroup, listMyGroups } from 'depictio-react-core';
import type { GroupDetail, MyGroup } from 'depictio-react-core';

import { AppSidebar } from '../chrome';
import { useCurrentUser } from '../hooks/useCurrentUser';
import GroupManagementCard from './GroupManagementCard';

const GroupsApp: React.FC = () => {
  const { user, loading: userLoading } = useCurrentUser();
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);

  const [groups, setGroups] = useState<MyGroup[]>([]);
  const [details, setDetails] = useState<Record<string, GroupDetail | 'loading' | 'error'>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    document.title = 'Depictio — Groups';
  }, []);

  const loadDetail = useCallback((groupId: string) => {
    setDetails((prev) => ({ ...prev, [groupId]: prev[groupId] ?? 'loading' }));
    fetchGroup(groupId)
      .then((detail) => setDetails((prev) => ({ ...prev, [groupId]: detail })))
      .catch(() => setDetails((prev) => ({ ...prev, [groupId]: 'error' })));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    listMyGroups()
      .then((list) => {
        if (cancelled) return;
        setGroups(list);
        // Members may read group detail — fetch every group's member list.
        for (const g of list) loadDetail(g.id);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load your groups');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey, loadDetail]);

  const handleChanged = useCallback(
    (groupId: string) => {
      loadDetail(groupId);
      // Re-list quietly so member counts / role badges stay accurate.
      listMyGroups()
        .then(setGroups)
        .catch(() => undefined);
    },
    [loadDetail],
  );

  const renderBody = () => {
    if (userLoading || loading) {
      return (
        <Center mih={300}>
          <Loader />
        </Center>
      );
    }
    if (!user) {
      return (
        <Center mih={300}>
          <Stack align="center" gap="xs">
            <Icon icon="mdi:account-off" width={32} color="var(--mantine-color-gray-6)" />
            <Text c="dimmed">Sign in to see your groups.</Text>
            <Button component="a" href="/auth" variant="light">
              Sign In
            </Button>
          </Stack>
        </Center>
      );
    }
    if (error) {
      return (
        <Center mih={300}>
          <Stack align="center" gap="xs">
            <Icon icon="mdi:alert-circle" width={32} color="var(--mantine-color-red-6)" />
            <Text c="red">{error}</Text>
            <Button variant="light" onClick={() => setRefreshKey((k) => k + 1)}>
              Retry
            </Button>
          </Stack>
        </Center>
      );
    }
    if (groups.length === 0) {
      return (
        <Center mih={300}>
          <Stack align="center" gap="xs">
            <Icon icon="ph:empty-bold" width={48} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed">You are not a member of any group yet.</Text>
          </Stack>
        </Center>
      );
    }
    return (
      <Stack gap="lg" maw={900}>
        {groups.map((group) => {
          const detail = details[group.id];
          return (
            <Card key={group.id} shadow="sm" radius="md" withBorder data-testid="my-group-card">
              <Stack gap="sm">
                <Group justify="space-between" wrap="nowrap">
                  <Group gap="xs" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
                    <Icon icon="mdi:account-multiple-outline" width={20} />
                    <Title order={4} style={{ minWidth: 0 }} lineClamp={1}>
                      {group.name}
                    </Title>
                  </Group>
                  <Group gap="xs" wrap="nowrap">
                    {group.is_pi && (
                      <Badge
                        color="yellow"
                        variant="light"
                        size="sm"
                        radius="sm"
                        leftSection={<Icon icon="mdi:crown-outline" width={12} />}
                      >
                        P.I.
                      </Badge>
                    )}
                    {group.is_group_admin && (
                      <Badge color="blue" variant="light" size="sm" radius="sm">
                        Group Admin
                      </Badge>
                    )}
                    {group.sso_managed && (
                      <Badge color="yellow" variant="light" size="sm" radius="sm">
                        SSO
                      </Badge>
                    )}
                    <Badge color="gray" variant="light" size="sm" radius="sm">
                      {group.member_count} member{group.member_count === 1 ? '' : 's'}
                    </Badge>
                  </Group>
                </Group>
                {group.description && (
                  <Text size="sm" c="dimmed">
                    {group.description}
                  </Text>
                )}

                {!detail || detail === 'loading' ? (
                  <Center mih={60}>
                    <Loader size="sm" />
                  </Center>
                ) : detail === 'error' ? (
                  <Text size="sm" c="dimmed">
                    Member list unavailable.
                  </Text>
                ) : group.is_group_admin ? (
                  <GroupManagementCard
                    group={detail}
                    canEditPI={false}
                    onChanged={() => handleChanged(group.id)}
                  />
                ) : (
                  <ReadOnlyMemberList detail={detail} />
                )}
              </Stack>
            </Card>
          );
        })}
      </Stack>
    );
  };

  return (
    <AppShell
      layout="alt"
      header={{ height: 64 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleMobile}
              hiddenFrom="sm"
              aria-label="Toggle navigation (mobile)"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleDesktop}
              visibleFrom="sm"
              aria-label="Toggle navigation"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <Icon
              icon="mdi:account-multiple-outline"
              width={22}
              color="var(--mantine-color-grape-6)"
            />
            <Title order={3} c="grape">
              Groups
            </Title>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="groups" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box px="lg" py="md">
          {renderBody()}
        </Box>
      </AppShell.Main>
    </AppShell>
  );
};

/** Members-only view: emails + role badges, no controls. */
const ReadOnlyMemberList: React.FC<{ detail: GroupDetail }> = ({ detail }) => (
  <Stack gap={6}>
    {detail.members.map((member) => (
      <Group key={member.id} gap="xs" wrap="nowrap" data-testid="group-member-row">
        <Text size="sm" fw={500} truncate>
          {member.email}
        </Text>
        {member.display_name && (
          <Text size="xs" c="dimmed" truncate>
            {member.display_name}
          </Text>
        )}
        {member.is_pi && (
          <Badge
            color="yellow"
            variant="light"
            size="sm"
            radius="sm"
            leftSection={<Icon icon="mdi:crown-outline" width={12} />}
          >
            P.I.
          </Badge>
        )}
        {member.is_group_admin && (
          <Badge color="blue" variant="light" size="sm" radius="sm">
            Admin
          </Badge>
        )}
      </Group>
    ))}
  </Stack>
);

export default GroupsApp;
