import React, { useCallback, useEffect, useState } from 'react';
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
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  listDashboards,
  listProjects,
  createDashboard,
  editDashboard as apiEditDashboard,
  deleteDashboard as apiDeleteDashboard,
  duplicateDashboard as apiDuplicateDashboard,
  importDashboardJson,
  exportDashboardJson,
} from 'depictio-react-core';
import type {
  CreateDashboardInput,
  DashboardListEntry,
  EditDashboardInput,
  ImportDashboardOptions,
  ProjectListEntry,
} from 'depictio-react-core';

import { useCurrentUser } from '../hooks/useCurrentUser';
import { AppSidebar } from '../chrome';
import DashboardsList from './DashboardsList';
import CreateDashboardModal from './CreateDashboardModal';
import EditDashboardModal from './EditDashboardModal';
import DeleteDashboardModal from './DeleteDashboardModal';

/** Separate storage key from the per-dashboard sidebar (`sidebar-collapsed`)
 *  so the management page can default to OPEN regardless of the user's
 *  in-dashboard preference. */
const SIDEBAR_KEY = 'dashboards-sidebar-collapsed';

function useDashboardsSidebar(): [boolean, () => void] {
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

const DashboardsApp: React.FC = () => {
  const [dashboards, setDashboards] = useState<DashboardListEntry[]>([]);
  const [projects, setProjects] = useState<ProjectListEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [editTarget, setEditTarget] = useState<DashboardListEntry | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DashboardListEntry | null>(null);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, toggleDesktop] = useDashboardsSidebar();
  const { user } = useCurrentUser();

  useEffect(() => {
    document.title = 'Depictio — Dashboards';
  }, []);

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    Promise.all([listDashboards(true), listProjects()])
      .then(([list, projs]) => {
        setDashboards(list);
        setProjects(projs);
      })
      .catch((err: Error) => {
        setLoadError(err.message || 'Failed to load dashboards');
      })
      .finally(() => setLoading(false));
  }, [refreshKey]);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const currentUserEmail = user?.email ?? null;

  const handleCreate = useCallback(
    async (input: CreateDashboardInput) => {
      const newId = await createDashboard(input);
      notifications.show({
        color: 'teal',
        title: 'Dashboard created',
        message: `"${input.title}" is ready.`,
        autoClose: 2500,
      });
      closeCreate();
      refresh();
      return newId;
    },
    [closeCreate, refresh],
  );

  const handleImport = useCallback(
    async (jsonContent: Record<string, unknown>, opts: ImportDashboardOptions) => {
      const result = await importDashboardJson(jsonContent, opts);
      notifications.show({
        color: 'teal',
        title: 'Dashboard imported',
        message: result.message || 'Imported successfully.',
        autoClose: 2500,
      });
      closeCreate();
      refresh();
    },
    [closeCreate, refresh],
  );

  const handleEdit = useCallback(
    async (dashboardId: string, input: EditDashboardInput) => {
      await apiEditDashboard(dashboardId, input);
      notifications.show({
        color: 'teal',
        title: 'Dashboard updated',
        message: 'Changes saved.',
        autoClose: 2000,
      });
      setEditTarget(null);
      refresh();
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (dashboardId: string) => {
      await apiDeleteDashboard(dashboardId);
      notifications.show({
        color: 'teal',
        title: 'Dashboard deleted',
        message: 'Dashboard removed.',
        autoClose: 2000,
      });
      setDeleteTarget(null);
      refresh();
    },
    [refresh],
  );

  const handleDuplicate = useCallback(
    async (dashboard: DashboardListEntry) => {
      try {
        await apiDuplicateDashboard(dashboard.dashboard_id);
        notifications.show({
          color: 'teal',
          title: 'Dashboard duplicated',
          message: `"${dashboard.title} (copy)" is ready.`,
          autoClose: 2500,
        });
        refresh();
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Duplicate failed',
          message: (err as Error).message,
        });
      }
    },
    [refresh],
  );

  const handleExport = useCallback(async (dashboard: DashboardListEntry) => {
    try {
      const payload = await exportDashboardJson(dashboard.dashboard_id);
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const safeTitle = (dashboard.title || dashboard.dashboard_id).replace(
        /[^a-zA-Z0-9._-]+/g,
        '_',
      );
      const a = document.createElement('a');
      a.href = url;
      a.download = `${safeTitle}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Export failed',
        message: (err as Error).message,
      });
    }
  }, []);

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
              icon="material-symbols:dashboard"
              width={22}
              color="var(--mantine-color-orange-6)"
            />
            <Title order={3} c="orange">
              Dashboards
            </Title>
          </Group>
          <Button
            color="orange"
            variant="filled"
            size="md"
            onClick={openCreate}
            style={{ fontFamily: 'Virgil' }}
          >
            + New Dashboard
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="dashboards" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box px="lg" py="md">
          {loading ? (
            <Center mih={200}>
              <Loader />
            </Center>
          ) : loadError ? (
            <Center mih={200}>
              <Stack align="center" gap="xs">
                <Icon
                  icon="mdi:alert-circle"
                  width={32}
                  color="var(--mantine-color-red-6)"
                />
                <Text c="red">{loadError}</Text>
                <Button variant="light" onClick={refresh}>
                  Try again
                </Button>
              </Stack>
            </Center>
          ) : (
            <DashboardsList
              dashboards={dashboards}
              projects={projects}
              currentUserEmail={currentUserEmail}
              onEdit={(d) => setEditTarget(d)}
              onDelete={(d) => setDeleteTarget(d)}
              onDuplicate={handleDuplicate}
              onExport={handleExport}
              onCreateClick={openCreate}
            />
          )}
        </Box>
      </AppShell.Main>

      <CreateDashboardModal
        opened={createOpened}
        projects={projects}
        existingTitles={dashboards.map((d) => d.title || '').filter(Boolean)}
        onClose={closeCreate}
        onCreate={handleCreate}
        onImport={handleImport}
      />
      <EditDashboardModal
        opened={Boolean(editTarget)}
        dashboard={editTarget}
        onClose={() => setEditTarget(null)}
        onSubmit={handleEdit}
      />
      <DeleteDashboardModal
        opened={Boolean(deleteTarget)}
        dashboard={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </AppShell>
  );
};

export default DashboardsApp;
