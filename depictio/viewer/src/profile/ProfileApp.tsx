import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  AppShell,
  Avatar,
  Box,
  Button,
  Center,
  Container,
  Divider,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import {
  clearSession,
  fetchAuthStatus,
  fetchCurrentUserFull,
  type AuthStatusResponse,
  type ProfileUser,
} from 'depictio-react-core';

import { AppSidebar } from '../chrome';
import EditPasswordModal from './EditPasswordModal';
import { brandColors } from './colors';

const SIDEBAR_KEY = 'profile-sidebar-collapsed';

function useProfileSidebar(): [boolean, () => void] {
  const [opened, setOpened] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(SIDEBAR_KEY);
      if (raw == null) return true;
      return JSON.parse(raw) === false;
    } catch {
      return true;
    }
  });
  const toggle = useCallback(() => {
    setOpened((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, JSON.stringify(!next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  return [opened, toggle];
}

/** Mirrors `depictio/dash/layouts/profile.py` button enable/disable rules. */
function buttonStates(status: AuthStatusResponse | null): {
  logoutDisabled: boolean;
  editPasswordDisabled: boolean;
  cliAgentsDisabled: boolean;
} {
  const isPublic = Boolean(status?.is_public_mode);
  const isSingle = Boolean(status?.is_single_user_mode);
  const isDemo = Boolean(status?.is_demo_mode);
  return {
    logoutDisabled: isPublic || isSingle,
    editPasswordDisabled: isSingle || isPublic || isDemo,
    cliAgentsDisabled: isPublic,
  };
}

const ProfileApp: React.FC = () => {
  const [user, setUser] = useState<ProfileUser | null>(null);
  const [status, setStatus] = useState<AuthStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [editPasswordOpened, { open: openEditPassword, close: closeEditPassword }] =
    useDisclosure(false);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, toggleDesktop] = useProfileSidebar();

  useEffect(() => {
    document.title = 'Depictio — Profile';
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([fetchCurrentUserFull(), fetchAuthStatus()])
      .then(([u, s]) => {
        if (cancelled) return;
        setUser(u);
        setStatus(s);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = useCallback(() => {
    clearSession();
    window.location.assign('/auth');
  }, []);

  const states = buttonStates(status);

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
            <Icon icon="mdi:account-circle" width={26} color="var(--mantine-color-violet-6)" />
            <Title order={3} c="violet">
              Profile
            </Title>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="profile" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Container size="lg" p="xl" fluid>
          {loading ? (
            <Center mih={300}>
              <Loader />
            </Center>
          ) : !user ? (
            <Center mih={300}>
              <Stack align="center" gap="xs">
                <Icon
                  icon="mdi:account-off"
                  width={32}
                  color="var(--mantine-color-gray-6)"
                />
                <Text c="dimmed">No authenticated user.</Text>
                <Button component="a" href="/auth" variant="light">
                  Sign In
                </Button>
              </Stack>
            </Center>
          ) : (
            <Paper shadow="md" radius="lg" p="xl" withBorder>
              <SimpleGrid cols={{ base: 1, md: 2 }} spacing="xl">
                <Paper
                  radius="lg"
                  p="xl"
                  shadow="md"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minHeight: 200,
                    minWidth: 200,
                  }}
                >
                  <AvatarFromEmail email={user.email} />
                </Paper>

                <Stack gap="lg">
                  <Group justify="space-between">
                    <Title order={2} fw={600}>
                      User Profile
                    </Title>
                    <Icon icon="mdi:account-circle" width={36} height={36} />
                  </Group>
                  <Divider variant="dashed" my="md" size="sm" />

                  <Stack gap="xs" style={{ padding: '16px 0' }}>
                    <UserInfoRow label="Email" value={user.email} />
                    <UserInfoRow label="Database ID" value={user.id || 'N/A'} />
                    <UserInfoRow label="Registration Date" value={user.registration_date || 'N/A'} />
                    <UserInfoRow label="Last login" value={user.last_login || 'N/A'} />
                    <UserInfoRow label="Admin" value={user.is_admin ? 'Yes' : 'No'} />
                  </Stack>

                  <Group gap="md" justify="flex-start" mt="lg">
                    <Button
                      variant="filled"
                      radius="md"
                      disabled={states.logoutDisabled}
                      onClick={handleLogout}
                      leftSection={<Icon icon="mdi:logout" width={20} />}
                      styles={{
                        root: {
                          backgroundColor: states.logoutDisabled ? undefined : brandColors.red,
                        },
                      }}
                    >
                      Logout
                    </Button>

                    <Button
                      variant="filled"
                      radius="md"
                      disabled={states.editPasswordDisabled}
                      onClick={openEditPassword}
                      leftSection={<Icon icon="mdi:lock-outline" width={20} />}
                      styles={{
                        root: {
                          backgroundColor: states.editPasswordDisabled
                            ? undefined
                            : brandColors.blue,
                        },
                      }}
                    >
                      Edit Password
                    </Button>

                    <Button
                      component="a"
                      href={states.cliAgentsDisabled ? undefined : '/cli-agents-beta'}
                      variant="filled"
                      radius="md"
                      disabled={states.cliAgentsDisabled}
                      leftSection={<Icon icon="mdi:console" width={20} />}
                      styles={{
                        root: {
                          backgroundColor: states.cliAgentsDisabled
                            ? undefined
                            : brandColors.green,
                        },
                      }}
                    >
                      CLI Agents
                    </Button>
                  </Group>

                  <Box mt="md" />
                </Stack>
              </SimpleGrid>
            </Paper>
          )}
        </Container>
      </AppShell.Main>

      <EditPasswordModal opened={editPasswordOpened} onClose={closeEditPassword} />
    </AppShell>
  );
};

const UserInfoRow: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <Paper p="sm" radius="md" withBorder>
    <Group justify="space-between">
      <Text fw="bold" size="sm">
        {label}
      </Text>
      <Text size="sm" style={{ wordBreak: 'break-word' }}>
        {value}
      </Text>
    </Group>
  </Paper>
);

const AvatarFromEmail: React.FC<{ email: string }> = ({ email }) => {
  const bg = brandColors.purple.replace('#', '');
  const url = `https://ui-avatars.com/api/?format=svg&name=${encodeURIComponent(
    email,
  )}&background=${bg}&color=white&rounded=true&bold=true&size=160`;
  return <Avatar src={url} size={160} radius="xl" />;
};

export default ProfileApp;
