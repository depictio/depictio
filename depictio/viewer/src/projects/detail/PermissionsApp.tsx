import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  AppShell,
  Autocomplete,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Paper,
  Stack,
  Switch,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef, ICellRendererParams, CellValueChangedEvent } from 'ag-grid-community';

import {
  fetchProject,
  listAllUsers,
  toggleProjectVisibility,
  updateProjectPermissions,
} from 'depictio-react-core';
import type { AdminUser, ProjectListEntry } from 'depictio-react-core';

import { useCurrentUser } from '../../hooks/useCurrentUser';
import { AppSidebar } from '../../chrome';

interface UserRow {
  _id: string;
  email: string;
  Owner: boolean;
  Editor: boolean;
  Viewer: boolean;
  is_admin?: boolean;
}

function readProjectIdFromPath(): string | null {
  const m = window.location.pathname.match(/^\/projects-beta\/([^/?#]+)/);
  return m?.[1] || null;
}

/** Build the AG Grid rows from a project's permissions object. Mirrors the
 *  Dash `register_projectwise_user_management_callbacks` shape: every user
 *  appears once, with three boolean role flags. */
function buildRows(project: ProjectListEntry | null): UserRow[] {
  if (!project) return [];
  const byKey = new Map<string, UserRow>();
  const seed = (
    list: Array<{ _id?: string; id?: string; email?: string; is_admin?: boolean }> | undefined,
    role: 'Owner' | 'Editor' | 'Viewer',
  ) => {
    (list || []).forEach((u) => {
      const id = (u._id ?? u.id ?? '') as string;
      const email = u.email || '';
      const key = id || email;
      if (!key) return;
      const existing = byKey.get(key);
      if (existing) {
        existing[role] = true;
      } else {
        byKey.set(key, {
          _id: id,
          email,
          Owner: role === 'Owner',
          Editor: role === 'Editor',
          Viewer: role === 'Viewer',
          is_admin: Boolean(u.is_admin),
        });
      }
    });
  };
  seed(project.permissions?.owners, 'Owner');
  seed(project.permissions?.editors, 'Editor');
  seed(project.permissions?.viewers, 'Viewer');
  return Array.from(byKey.values());
}

/** Inverse of buildRows — flatten the grid back into the API's owners/
 *  editors/viewers shape. Drops users with no roles. */
function rowsToPermissions(rows: UserRow[]): {
  owners: { _id: string; email: string }[];
  editors: { _id: string; email: string }[];
  viewers: { _id: string; email: string }[];
} {
  const collect = (role: 'Owner' | 'Editor' | 'Viewer') =>
    rows
      .filter((r) => r[role])
      .map((r) => ({ _id: r._id, email: r.email }));
  return {
    owners: collect('Owner'),
    editors: collect('Editor'),
    viewers: collect('Viewer'),
  };
}

const PermissionsApp: React.FC = () => {
  const projectId = readProjectIdFromPath();
  const { user } = useCurrentUser();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const [project, setProject] = useState<ProjectListEntry | null>(null);
  const [rows, setRows] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [emailInput, setEmailInput] = useState('');
  const [adding, setAdding] = useState(false);
  /** Cached email list for the Autocomplete. Populated only when the
   *  current user can list users (admin); otherwise stays empty and the
   *  Autocomplete degrades to a plain text field. */
  const [allUsers, setAllUsers] = useState<AdminUser[]>([]);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);

  useEffect(() => {
    document.title = 'Depictio — Project Permissions';
  }, []);

  // Try to load the full user list once for the Autocomplete suggestions.
  // The endpoint is admin-only — for non-admins we silently fall back to
  // free text. Keeping the failure quiet avoids a useless toast on every
  // viewer's permissions page load.
  useEffect(() => {
    let cancelled = false;
    listAllUsers()
      .then((users) => {
        if (!cancelled) setAllUsers(users);
      })
      .catch(() => {
        if (!cancelled) setAllUsers([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!projectId) {
      setLoadError('No project ID in URL.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    fetchProject(projectId, { skipEnrichment: true })
      .then(({ project }) => {
        setProject(project);
        setRows(buildRows(project));
      })
      .catch((err: Error) =>
        setLoadError(err.message || 'Failed to load project.'),
      )
      .finally(() => setLoading(false));
  }, [projectId, refreshKey]);

  const refresh = () => setRefreshKey((k) => k + 1);

  // Owner-only gate (matches backend `update_project_permissions` rule).
  const canManage = useMemo(() => {
    if (!user || !project) return false;
    if (user.is_admin) return true;
    return !!project.permissions?.owners?.some(
      (o) => (o._id ?? o.id) === user.id,
    );
  }, [user, project]);

  const persist = async (nextRows: UserRow[]) => {
    if (!projectId) return;
    const perms = rowsToPermissions(nextRows);
    if (perms.owners.length === 0) {
      throw new Error('A project must have at least one owner.');
    }
    await updateProjectPermissions({
      project_id: projectId,
      permissions: perms,
    });
    refresh();
  };

  const handleCellChange = async (e: CellValueChangedEvent<UserRow>) => {
    const next = [...rows];
    const idx = next.findIndex((r) => r._id === e.data._id);
    if (idx < 0) return;
    next[idx] = { ...e.data };
    try {
      await persist(next);
      notifications.show({
        color: 'teal',
        title: 'Permissions updated',
        message: e.data.email,
        autoClose: 1500,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Update failed',
        message: (err as Error).message,
      });
      // Revert
      refresh();
    }
  };

  const handleAdd = async () => {
    const trimmed = emailInput.trim();
    if (!trimmed) return;
    setAdding(true);
    try {
      let row: UserRow;
      if (trimmed === '*') {
        row = {
          _id: '*',
          email: '*',
          Owner: false,
          Editor: false,
          Viewer: true, // wildcard makes sense as a viewer default
        };
      } else {
        // Resolve via the locally cached `allUsers` list. The auth endpoint
        // `/auth/fetch_user/from_email` requires an internal api-key header
        // that browser clients don't carry, so we look up by email in the
        // admin-listed set we loaded on mount instead.
        const u = allUsers.find(
          (x) => (x.email || '').toLowerCase() === trimmed.toLowerCase(),
        );
        if (!u) {
          throw new Error(
            `No user with email "${trimmed}". Pick one from the suggestions or ask an admin to invite them first.`,
          );
        }
        const id = (u._id ?? u.id) as string | undefined;
        if (!id) {
          throw new Error('User record has no id; cannot add.');
        }
        row = {
          _id: id,
          email: u.email,
          Owner: false,
          Editor: false,
          Viewer: true, // default newly-added users to Viewer
          is_admin: Boolean(u.is_admin),
        };
      }
      if (rows.some((r) => r._id === row._id || r.email === row.email)) {
        throw new Error(`${row.email} is already in this project.`);
      }
      const next = [...rows, row];
      await persist(next);
      setEmailInput('');
      notifications.show({
        color: 'teal',
        title: 'User added',
        message: `${row.email} (Viewer)`,
        autoClose: 2000,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Add failed',
        message: (err as Error).message,
      });
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (rowToDelete: UserRow) => {
    const next = rows.filter((r) => r._id !== rowToDelete._id);
    try {
      await persist(next);
      notifications.show({
        color: 'teal',
        title: 'User removed',
        message: rowToDelete.email,
        autoClose: 2000,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Remove failed',
        message: (err as Error).message,
      });
    }
  };

  const handleToggleVisibility = async (nextPublic: boolean) => {
    if (!projectId) return;
    try {
      await toggleProjectVisibility(projectId, nextPublic);
      notifications.show({
        color: 'teal',
        title: nextPublic ? 'Project is now public' : 'Project is now private',
        message: nextPublic
          ? 'Anyone signed in can view this project.'
          : 'Only listed members can view this project.',
        autoClose: 2500,
      });
      refresh();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Visibility update failed',
        message: (err as Error).message,
      });
    }
  };

  const colDefs = useMemo<ColDef<UserRow>[]>(
    () => [
      { field: '_id', hide: true },
      {
        field: 'email',
        headerName: 'Email',
        flex: 2,
        minWidth: 220,
        editable: false,
        cellRenderer: (params: ICellRendererParams<UserRow>) => {
          const v = params.value as string;
          if (v === '*') {
            return (
              <Group gap="xs" h="100%">
                <Icon
                  icon="mdi:earth"
                  width={16}
                  color="var(--mantine-color-green-6)"
                />
                <Text size="sm" fw={500}>
                  All users (*)
                </Text>
              </Group>
            );
          }
          return (
            <Group gap="xs" h="100%">
              <Icon
                icon="mdi:account-circle-outline"
                width={16}
                color="var(--mantine-color-gray-6)"
              />
              <Text size="sm">{v}</Text>
            </Group>
          );
        },
      },
      {
        field: 'Owner',
        headerName: 'Owner',
        width: 100,
        cellRenderer: 'agCheckboxCellRenderer',
        cellStyle: {
          textAlign: 'center',
          pointerEvents: canManage ? 'auto' : 'none',
        },
        editable: canManage,
        suppressKeyboardEvent: () => !canManage,
      },
      {
        field: 'Editor',
        headerName: 'Editor',
        width: 100,
        cellRenderer: 'agCheckboxCellRenderer',
        cellStyle: {
          textAlign: 'center',
          pointerEvents: canManage ? 'auto' : 'none',
        },
        editable: canManage,
        suppressKeyboardEvent: () => !canManage,
      },
      {
        field: 'Viewer',
        headerName: 'Viewer',
        width: 100,
        cellRenderer: 'agCheckboxCellRenderer',
        cellStyle: {
          textAlign: 'center',
          pointerEvents: canManage ? 'auto' : 'none',
        },
        editable: canManage,
        suppressKeyboardEvent: () => !canManage,
      },
      {
        headerName: '',
        width: 70,
        sortable: false,
        filter: false,
        editable: false,
        cellRenderer: (params: ICellRendererParams<UserRow>) => {
          if (!params.data) return null;
          return (
            <Center h="100%">
              <ActionIcon
                size="sm"
                variant="subtle"
                color="red"
                disabled={!canManage}
                title={canManage ? 'Remove user' : 'Owner permission required'}
                onClick={() => handleDelete(params.data!)}
              >
                <Icon icon="mdi:delete" width={16} />
              </ActionIcon>
            </Center>
          );
        },
      },
    ],
    [canManage, rows],
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
              Project Permissions
            </Title>
          </Group>
          <Group gap="xs">
            <Button
              component="a"
              href={`/projects-beta/${projectId}`}
              variant="subtle"
              color="teal"
              leftSection={<Icon icon="mdi:database-outline" width={16} />}
            >
              Data Collections
            </Button>
            <Button
              component="a"
              href="/projects-beta"
              variant="subtle"
              color="gray"
              leftSection={<Icon icon="mdi:arrow-left" width={16} />}
            >
              Back to Projects
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="projects" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box px="lg" py="md">
          {loading ? (
            <Center mih={300}>
              <Loader />
            </Center>
          ) : loadError ? (
            <Center mih={300}>
              <Stack align="center" gap="xs">
                <Icon
                  icon="mdi:alert-circle"
                  width={32}
                  color="var(--mantine-color-red-6)"
                />
                <Text c="red">{loadError}</Text>
                <Button component="a" href="/projects-beta" variant="light">
                  Back to projects
                </Button>
              </Stack>
            </Center>
          ) : !project ? null : (
            <Stack gap="lg">
              <Paper withBorder radius="md" p="lg">
                <Stack gap="xs">
                  <Group gap="sm" justify="space-between">
                    <Group gap="sm">
                      <Icon
                        icon="mdi:shield-account-outline"
                        width={26}
                        color="var(--mantine-color-blue-6)"
                      />
                      <Title order={3} c="blue" style={{ fontWeight: 600 }}>
                        Roles & Permissions
                      </Title>
                    </Group>
                    <Switch
                      label={project.is_public ? 'Public' : 'Private'}
                      checked={Boolean(project.is_public)}
                      color="teal"
                      onChange={(e) =>
                        handleToggleVisibility(e.currentTarget.checked)
                      }
                      disabled={!canManage}
                    />
                  </Group>
                  <Text size="sm" c="dimmed">
                    {project.name}
                  </Text>
                </Stack>
              </Paper>

              {!canManage && (
                <Alert
                  color="yellow"
                  variant="light"
                  icon={<Icon icon="mdi:lock-outline" width={18} />}
                >
                  Read-only mode. Only project owners (or admins) can modify
                  roles or visibility.
                </Alert>
              )}

              <Card withBorder radius="md" p="md">
                <Stack gap="sm">
                  <Group justify="space-between">
                    <Group gap="xs">
                      <Icon
                        icon="mdi:account-multiple-outline"
                        width={22}
                        color="var(--mantine-color-blue-6)"
                      />
                      <Title order={5}>Project Members</Title>
                      <Badge color="blue" variant="light" radius="sm" size="sm">
                        {rows.length}
                      </Badge>
                    </Group>
                  </Group>
                  <Box
                    className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
                    style={{
                      height: Math.max(160, 56 + rows.length * 36 + 4),
                      width: '100%',
                    }}
                  >
                    <AgGridReact<UserRow>
                      rowData={rows}
                      columnDefs={colDefs}
                      headerHeight={36}
                      rowHeight={36}
                      suppressCellFocus
                      onCellValueChanged={handleCellChange}
                      stopEditingWhenCellsLoseFocus
                      overlayNoRowsTemplate={
                        '<span style="color:var(--mantine-color-dimmed);font-size:12px">No users yet — add a teammate by email below.</span>'
                      }
                    />
                  </Box>
                  {canManage && (
                    <Group gap="xs" align="flex-end">
                      <Autocomplete
                        flex={1}
                        size="sm"
                        label={undefined}
                        placeholder={
                          allUsers.length > 0
                            ? 'Type to search users…  (or * for all signed-in users)'
                            : 'user@example.com  (or * for all signed-in users)'
                        }
                        value={emailInput}
                        onChange={setEmailInput}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !adding) handleAdd();
                        }}
                        disabled={adding}
                        leftSection={<Icon icon="mdi:account-plus-outline" width={16} />}
                        // Suggestions: every known user that isn't already a
                        // project member, plus the wildcard. Mantine filters
                        // by the current input value on its own.
                        data={[
                          '*',
                          ...allUsers
                            .map((u) => u.email)
                            .filter(
                              (e) => e && !rows.some((r) => r.email === e),
                            ),
                        ]}
                        limit={20}
                        comboboxProps={{ withinPortal: true }}
                      />
                      <Button
                        size="sm"
                        color="teal"
                        loading={adding}
                        onClick={handleAdd}
                        disabled={!emailInput.trim()}
                        leftSection={<Icon icon="mdi:plus" width={14} />}
                      >
                        Add user
                      </Button>
                    </Group>
                  )}
                </Stack>
              </Card>
            </Stack>
          )}
        </Box>
      </AppShell.Main>
    </AppShell>
  );
};

export default PermissionsApp;
