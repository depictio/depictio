import React, { useEffect } from 'react';
import {
  ActionIcon,
  AppShell,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { AppSidebar } from '../chrome';
import { useCurrentUser } from '../hooks/useCurrentUser';
import GroupsWorkspace from './GroupsWorkspace';

/** Personal groups page: the groups the signed-in user belongs to, managed
 *  where they are a group admin. Reached from the profile page's group
 *  badges — deployment-wide group administration lives in `/admin`. */
const GroupsApp: React.FC = () => {
  const { user, loading } = useCurrentUser();
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);

  useEffect(() => {
    document.title = 'Depictio — My Groups';
  }, []);

  const renderBody = () => {
    if (loading) {
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
    return <GroupsWorkspace scope="mine" />;
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
            <Icon icon="mdi:account-multiple-outline" width={22} color="var(--mantine-color-grape-6)" />
            <Title order={3} c="grape">
              My Groups
            </Title>
          </Group>
          <Group gap="xs">
            {user?.is_admin && (
              <Button
                component="a"
                href="/admin"
                variant="subtle"
                color="blue"
                leftSection={<Icon icon="material-symbols:settings" width={16} />}
              >
                Manage all groups
              </Button>
            )}
            <Button
              component="a"
              href="/profile"
              variant="subtle"
              color="gray"
              leftSection={<Icon icon="mdi:arrow-left" width={16} />}
            >
              Back to Profile
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="profile" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box px="lg" py="md">
          {renderBody()}
        </Box>
      </AppShell.Main>
    </AppShell>
  );
};

export default GroupsApp;
