import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  AppShell,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Tabs,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { AppSidebar } from '../chrome';
import { useCurrentUser } from '../hooks/useCurrentUser';
import AdminUsersPanel from './AdminUsersPanel';
import AdminProjectsPanel from './AdminProjectsPanel';
import AdminDashboardsPanel from './AdminDashboardsPanel';

type AdminTab = 'users' | 'projects' | 'dashboards';

/** Persist the active tab so a refresh keeps the admin where they left off. */
const TAB_KEY = 'admin-active-tab';

function readInitialTab(): AdminTab {
  try {
    const raw = localStorage.getItem(TAB_KEY);
    if (raw === 'users' || raw === 'projects' || raw === 'dashboards') {
      return raw;
    }
  } catch {
    /* ignore */
  }
  return 'users';
}

const AdminApp: React.FC = () => {
  const { user, loading } = useCurrentUser();
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);
  const [activeTab, setActiveTab] = useState<AdminTab>(readInitialTab);

  useEffect(() => {
    document.title = 'Depictio — Administration';
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(TAB_KEY, activeTab);
    } catch {
      /* ignore */
    }
  }, [activeTab]);

  const renderBody = () => {
    if (loading) {
      return (
        <Center mih={300}>
          <Loader />
        </Center>
      );
    }
    if (!user || !user.is_admin) {
      return (
        <Center mih={400}>
          <Stack align="center" gap="md" maw={420} ta="center">
            <Icon
              icon="material-symbols:lock-outline"
              width={64}
              color="var(--mantine-color-red-6)"
            />
            <Title order={3}>Forbidden</Title>
            <Text c="dimmed">
              The administration page is only available to system administrators.
            </Text>
            <Button
              component="a"
              href="/dashboards-beta"
              variant="light"
              leftSection={<Icon icon="material-symbols:dashboard" width={16} />}
            >
              Back to dashboards
            </Button>
          </Stack>
        </Center>
      );
    }
    return (
      <Tabs
        value={activeTab}
        onChange={(v) => v && setActiveTab(v as AdminTab)}
        keepMounted={false}
      >
        <Tabs.List>
          <Tabs.Tab value="users" leftSection={<Icon icon="mdi:account-group" width={16} />}>
            Users
          </Tabs.Tab>
          <Tabs.Tab value="projects" leftSection={<Icon icon="mdi:jira" width={16} />}>
            Projects
          </Tabs.Tab>
          <Tabs.Tab
            value="dashboards"
            leftSection={<Icon icon="material-symbols:dashboard" width={16} />}
          >
            Dashboards
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="users" pt="md">
          <AdminUsersPanel currentUserEmail={user.email} />
        </Tabs.Panel>
        <Tabs.Panel value="projects" pt="md">
          <AdminProjectsPanel />
        </Tabs.Panel>
        <Tabs.Panel value="dashboards" pt="md">
          <AdminDashboardsPanel />
        </Tabs.Panel>
      </Tabs>
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
              icon="material-symbols:settings"
              width={22}
              color="var(--mantine-color-blue-6)"
            />
            <Title order={3} c="blue">
              Administration
            </Title>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="admin" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box px="lg" py="md">
          {renderBody()}
        </Box>
      </AppShell.Main>
    </AppShell>
  );
};

export default AdminApp;
