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
  listProjects,
  createProject,
  updateProject as apiUpdateProject,
  deleteProject as apiDeleteProject,
  importProjectZip,
} from 'depictio-react-core';
import type {
  CreateProjectInput,
  EditProjectInput,
  ProjectListEntry,
} from 'depictio-react-core';

import { useCurrentUser } from '../hooks/useCurrentUser';
import { useAuthMode } from '../auth/hooks/useAuthMode';
import { AppSidebar } from '../chrome';
import ProjectsList from './ProjectsList';
import CreateProjectModal from './CreateProjectModal';
import EditProjectModal from './EditProjectModal';
import DeleteProjectModal from './DeleteProjectModal';

/** Separate storage key from per-dashboard sidebar (`sidebar-collapsed`) so
 *  the projects management page can default to OPEN regardless of the user's
 *  in-dashboard sidebar preference. Mirrors `DashboardsApp.tsx`. */
const SIDEBAR_KEY = 'projects-sidebar-collapsed';

function useProjectsSidebar(): [boolean, () => void] {
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

const ProjectsApp: React.FC = () => {
  const [projects, setProjects] = useState<ProjectListEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [editTarget, setEditTarget] = useState<ProjectListEntry | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProjectListEntry | null>(null);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, toggleDesktop] = useProjectsSidebar();
  const { user } = useCurrentUser();
  const { status: authStatus } = useAuthMode();
  const isPublic = Boolean(authStatus?.is_public_mode);

  useEffect(() => {
    document.title = 'Depictio — Projects';
  }, []);

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    listProjects()
      .then(setProjects)
      .catch((err: Error) => {
        setLoadError(err.message || 'Failed to load projects');
      })
      .finally(() => setLoading(false));
  }, [refreshKey]);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const handleCreate = useCallback(
    async (input: CreateProjectInput) => {
      const result = await createProject(input);
      notifications.show({
        color: 'teal',
        title: 'Project created',
        message: `"${input.name}" is ready.`,
        autoClose: 2500,
      });
      closeCreate();
      refresh();
      return result;
    },
    [closeCreate, refresh],
  );

  const handleImport = useCallback(
    async (file: File, overwrite: boolean) => {
      const result = await importProjectZip(file, overwrite);
      notifications.show({
        color: 'teal',
        title: 'Project imported',
        message: result.message || 'Imported successfully.',
        autoClose: 2500,
      });
      closeCreate();
      refresh();
    },
    [closeCreate, refresh],
  );

  const handleEdit = useCallback(
    async (projectId: string, input: EditProjectInput) => {
      await apiUpdateProject(projectId, input);
      notifications.show({
        color: 'teal',
        title: 'Project updated',
        message: 'Changes saved.',
        autoClose: 2000,
      });
      setEditTarget(null);
      refresh();
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (projectId: string) => {
      await apiDeleteProject(projectId);
      notifications.show({
        color: 'teal',
        title: 'Project deleted',
        message: 'Project and all linked dashboards removed.',
        autoClose: 2500,
      });
      setDeleteTarget(null);
      refresh();
    },
    [refresh],
  );

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
              icon="mdi:jira"
              width={22}
              color="var(--mantine-color-teal-6)"
            />
            <Title order={3} c="teal">
              Projects
            </Title>
          </Group>
          {!isPublic && (
            <Button
              color="teal"
              variant="filled"
              size="md"
              onClick={openCreate}
              style={{ fontFamily: 'Virgil' }}
            >
              + New Project
            </Button>
          )}
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="projects" />
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
            <ProjectsList
              projects={projects}
              currentUserId={user?.id ?? null}
              isAdmin={Boolean(user?.is_admin)}
              canCreate={!isPublic}
              onCreateClick={openCreate}
              onEdit={(p) => setEditTarget(p)}
              onDelete={(p) => setDeleteTarget(p)}
            />
          )}
        </Box>
      </AppShell.Main>

      <CreateProjectModal
        opened={createOpened}
        existingNames={projects.map((p) => p.name).filter(Boolean) as string[]}
        onClose={closeCreate}
        onCreate={handleCreate}
        onImport={handleImport}
      />
      <EditProjectModal
        opened={Boolean(editTarget)}
        project={editTarget}
        onClose={() => setEditTarget(null)}
        onSubmit={handleEdit}
      />
      <DeleteProjectModal
        opened={Boolean(deleteTarget)}
        project={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </AppShell>
  );
};

export default ProjectsApp;
