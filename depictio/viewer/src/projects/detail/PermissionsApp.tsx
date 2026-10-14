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
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  Title,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef, ICellRendererParams, CellValueChangedEvent } from 'ag-grid-community';
import { GlassPage, STROKE, useGlassPages } from '../../chrome/variants/glass/pages';
import '../../chrome/variants/glass/pages/permissions.css';
import {
  ArrowRight,
  Database,
  Globe,
  Lock,
  ShieldCheck,
  TriangleAlert,
  UserMinus,
  UserPlus,
  Trash2,
  UserRound,
  Users,
  UsersRound,
} from 'lucide-react';

import {
  fetchProject,
  listAllUsers,
  listGroups,
  listMyGroups,
  toggleProjectVisibility,
  updateProjectPermissions,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  AdminUser,
  GroupSummary,
  MyGroup,
  PermissionsGroup,
  ProjectListEntry,
} from 'depictio-react-core';

import { useCurrentUser } from '../../hooks/useCurrentUser';
import { AppSidebar } from '../../chrome';
import { usePageTitle } from '../../branding';

type Role = 'Owner' | 'Editor' | 'Viewer';
const ROLES: Role[] = ['Owner', 'Editor', 'Viewer'];

function roleOf(r: UserRow): Role | '' {
  return ROLES.find((role) => r[role]) ?? '';
}

interface UserRow {
  _id: string;
  email: string;
  Owner: boolean;
  Editor: boolean;
  Viewer: boolean;
  is_admin?: boolean;
}

interface GroupRow {
  _id: string;
  name: string;
  Owner: boolean;
  Editor: boolean;
  Viewer: boolean;
}

function groupRoleOf(r: GroupRow): Role | '' {
  return ROLES.find((role) => r[role]) ?? '';
}

function readProjectIdFromPath(): string | null {
  const m = window.location.pathname.match(/^\/projects\/([^/?#]+)/);
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

/** Group counterpart of buildRows — one grid row per group, with three
 *  exclusive role flags (the server 422s a group holding several roles). */
function buildGroupRows(project: ProjectListEntry | null): GroupRow[] {
  if (!project) return [];
  const byKey = new Map<string, GroupRow>();
  const seed = (
    list: PermissionsGroup[] | undefined,
    role: 'Owner' | 'Editor' | 'Viewer',
  ) => {
    (list || []).forEach((g) => {
      const id = (g._id ?? g.id ?? '') as string;
      const name = g.name || '';
      const key = id || name;
      if (!key) return;
      const existing = byKey.get(key);
      if (existing) {
        existing[role] = true;
      } else {
        byKey.set(key, {
          _id: id,
          name,
          Owner: role === 'Owner',
          Editor: role === 'Editor',
          Viewer: role === 'Viewer',
        });
      }
    });
  };
  seed(project.permissions?.group_owners, 'Owner');
  seed(project.permissions?.group_editors, 'Editor');
  seed(project.permissions?.group_viewers, 'Viewer');
  return Array.from(byKey.values());
}

/** Inverse of buildGroupRows — flatten the grid back into the API's
 *  group_owners/group_editors/group_viewers shape. Drops role-less groups. */
function rowsToGroupPermissions(rows: GroupRow[]): {
  group_owners: PermissionsGroup[];
  group_editors: PermissionsGroup[];
  group_viewers: PermissionsGroup[];
} {
  const collect = (role: 'Owner' | 'Editor' | 'Viewer') =>
    rows
      .filter((r) => r[role])
      .map((r) => ({ _id: r._id, name: r.name }));
  return {
    group_owners: collect('Owner'),
    group_editors: collect('Editor'),
    group_viewers: collect('Viewer'),
  };
}

/** Big public/private state badge for the visibility-change confirm modal.
 *  Two side-by-side instances visualise the from→to transition. */
const VisibilityCard: React.FC<{
  kind: 'public' | 'private';
  role: 'from' | 'to';
  glass?: boolean;
}> = ({ kind, role, glass }) => {
  const isPublic = kind === 'public';
  const color = isPublic ? 'teal' : 'violet';
  const icon = isPublic ? 'mdi:earth' : 'mdi:lock';
  const isFrom = role === 'from';
  if (glass) {
    const Mark = isPublic ? Globe : Lock;
    return (
      <div className="pm-vis" data-role={role}>
        <span className="pm-vis-label">{isFrom ? 'From' : 'To'}</span>
        <Mark size={28} strokeWidth={STROKE} aria-hidden />
        <Badge color="gray" size="md" className="gp-tag-plain">
          {isPublic ? 'Public' : 'Private'}
        </Badge>
      </div>
    );
  }
  return (
    <Stack gap={4} align="center" miw={120}>
      <Text size="xs" c="dimmed" fw={500}>
        {isFrom ? 'FROM' : 'TO'}
      </Text>
      <Paper
        withBorder
        radius="md"
        p="md"
        style={{
          borderColor: `var(--mantine-color-${color}-6)`,
          borderWidth: 2,
          opacity: isFrom ? 0.6 : 1,
          minWidth: 120,
        }}
      >
        <Stack gap={4} align="center">
          <Icon icon={icon} width={28} color={`var(--mantine-color-${color}-6)`} />
          <Badge color={color} variant="light" size="md" fw={600}>
            {isPublic ? 'Public' : 'Private'}
          </Badge>
        </Stack>
      </Paper>
    </Stack>
  );
};

const PermissionsApp: React.FC = () => {
  const accent = useBrandAccents();
  const projectId = readProjectIdFromPath();
  const { user } = useCurrentUser();
  const { colorScheme } = useMantineColorScheme();
  const primary = useMantineTheme().primaryColor;
  const isDark = colorScheme === 'dark';

  const [project, setProject] = useState<ProjectListEntry | null>(null);
  const [rows, setRows] = useState<UserRow[]>([]);
  const [groupRows, setGroupRows] = useState<GroupRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [emailInput, setEmailInput] = useState('');
  const [adding, setAdding] = useState(false);
  const [groupInput, setGroupInput] = useState('');
  const [addingGroup, setAddingGroup] = useState(false);
  /** Cached email list for the Autocomplete. Populated only when the
   *  current user can list users (admin); otherwise stays empty and the
   *  Autocomplete degrades to a plain text field. */
  const [allUsers, setAllUsers] = useState<AdminUser[]>([]);
  /** All groups (names only) for the group Autocomplete — the list endpoint
   *  works for any authenticated user. */
  const [allGroups, setAllGroups] = useState<GroupSummary[]>([]);
  /** The caller's own groups (with is_group_admin) — feeds the canManage
   *  gate for group admins of owner groups. Failure tolerated as []. */
  const [myGroups, setMyGroups] = useState<MyGroup[]>([]);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);
  // Pending public/private flip awaiting modal confirmation. Mirrors the
  // Dash flow (`make-project-public-modal`): toggling the Switch only opens
  // the modal; the API call fires on confirm.
  const [pendingPublic, setPendingPublic] = useState<boolean | null>(null);
  const [visibilityBusy, setVisibilityBusy] = useState(false);

  usePageTitle('Project Permissions');
  const glass = useGlassPages();

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
    // Groups list (any authenticated user). Unlike listAllUsers this is not
    // expected to fail for non-admins, so a failure gets a visible toast.
    listGroups()
      .then((groups) => {
        if (!cancelled) setAllGroups(groups);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setAllGroups([]);
        notifications.show({
          color: 'red',
          title: 'Could not load groups',
          message: err.message || 'Group suggestions are unavailable.',
        });
      });
    // My groups — only used to widen canManage for group admins of owner
    // groups; a failure just falls back to the user/admin gate.
    listMyGroups()
      .then((mine) => {
        if (!cancelled) setMyGroups(mine);
      })
      .catch(() => {
        if (!cancelled) setMyGroups([]);
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
        setGroupRows(buildGroupRows(project));
      })
      .catch((err: Error) =>
        setLoadError(err.message || 'Failed to load project.'),
      )
      .finally(() => setLoading(false));
  }, [projectId, refreshKey]);

  const refresh = () => setRefreshKey((k) => k + 1);

  // Owner-only gate (matches backend `update_project_permissions` rule):
  // sysadmin, direct owner, or group admin of a group in group_owners.
  const canManage = useMemo(() => {
    if (!user || !project) return false;
    if (user.is_admin) return true;
    if (
      project.permissions?.owners?.some((o) => (o._id ?? o.id) === user.id)
    ) {
      return true;
    }
    const ownerGroupIds = new Set(
      (project.permissions?.group_owners || [])
        .map((g) => (g._id ?? g.id) as string | undefined)
        .filter(Boolean),
    );
    return myGroups.some((g) => g.is_group_admin && ownerGroupIds.has(g.id));
  }, [user, project, myGroups]);

  /** Single save path — always sends BOTH the user lists and the group
   *  lists, so a change to one grid can't wipe the other. */
  const persist = async (nextRows: UserRow[], nextGroupRows: GroupRow[]) => {
    if (!projectId) return;
    const perms = rowsToPermissions(nextRows);
    const groupPerms = rowsToGroupPermissions(nextGroupRows);
    if (perms.owners.length === 0 && groupPerms.group_owners.length === 0) {
      throw new Error(
        'A project must have at least one owner (user or group).',
      );
    }
    await updateProjectPermissions({
      project_id: projectId,
      permissions: { ...perms, ...groupPerms },
    });
    refresh();
  };

  const saveRow = async (updated: UserRow) => {
    const next = [...rows];
    const idx = next.findIndex((r) => r._id === updated._id);
    if (idx < 0) return;
    next[idx] = updated;
    try {
      await persist(next, groupRows);
      notifications.show({
        color: 'teal',
        title: 'Permissions updated',
        message: updated.email,
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

  // Roles are mutually exclusive on the server (Pydantic validator): the
  // role switched on clears the others on the same row, otherwise the API
  // rejects with "User cannot be both an X and a Y".
  const setRole = (row: UserRow, role: Role) =>
    saveRow({ ...row, Owner: false, Editor: false, Viewer: false, [role]: true });

  const handleCellChange = (e: CellValueChangedEvent<UserRow>) => {
    const flippedOn = e.colDef.field as Role | undefined;
    if (flippedOn && e.data[flippedOn]) return setRole(e.data, flippedOn);
    return saveRow({ ...e.data });
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
      await persist(next, groupRows);
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
      await persist(next, groupRows);
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

  const saveGroupRow = async (updated: GroupRow) => {
    const next = [...groupRows];
    const idx = next.findIndex((r) => r._id === updated._id);
    if (idx < 0) return;
    next[idx] = updated;
    try {
      await persist(rows, next);
      notifications.show({
        color: 'teal',
        title: 'Permissions updated',
        message: updated.name,
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

  // A group may hold exactly one role (server 422s otherwise) — the role
  // switched on clears the others on the same row, mirroring setRole.
  const setGroupRole = (row: GroupRow, role: Role) =>
    saveGroupRow({ ...row, Owner: false, Editor: false, Viewer: false, [role]: true });

  const handleGroupCellChange = (e: CellValueChangedEvent<GroupRow>) => {
    const flippedOn = e.colDef.field as Role | undefined;
    if (flippedOn && e.data[flippedOn]) return setGroupRole(e.data, flippedOn);
    return saveGroupRow({ ...e.data });
  };

  const handleAddGroup = async () => {
    const trimmed = groupInput.trim();
    if (!trimmed) return;
    setAddingGroup(true);
    try {
      const g = allGroups.find(
        (x) => (x.name || '').toLowerCase() === trimmed.toLowerCase(),
      );
      if (!g) {
        throw new Error(
          `No group named "${trimmed}". Pick one from the suggestions.`,
        );
      }
      if (groupRows.some((r) => r._id === g.id || r.name === g.name)) {
        throw new Error(`Group "${g.name}" is already in this project.`);
      }
      const row: GroupRow = {
        _id: g.id,
        name: g.name,
        Owner: false,
        Editor: false,
        Viewer: true, // default newly-added groups to Viewer
      };
      const next = [...groupRows, row];
      await persist(rows, next);
      setGroupInput('');
      notifications.show({
        color: 'teal',
        title: 'Group added',
        message: `${row.name} (Viewer)`,
        autoClose: 2000,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Add failed',
        message: (err as Error).message,
      });
    } finally {
      setAddingGroup(false);
    }
  };

  const handleDeleteGroup = async (rowToDelete: GroupRow) => {
    const next = groupRows.filter((r) => r._id !== rowToDelete._id);
    try {
      await persist(rows, next);
      notifications.show({
        color: 'teal',
        title: 'Group removed',
        message: rowToDelete.name,
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

  const confirmToggleVisibility = async () => {
    if (!projectId || pendingPublic === null) return;
    const nextPublic = pendingPublic;
    setVisibilityBusy(true);
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
      setPendingPublic(null);
      refresh();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Visibility update failed',
        message: (err as Error).message,
      });
    } finally {
      setVisibilityBusy(false);
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
    // groupRows: handleDelete's persist path sends the group lists too.
    [canManage, rows, groupRows],
  );

  const groupColDefs = useMemo<ColDef<GroupRow>[]>(
    () => [
      { field: '_id', hide: true },
      {
        field: 'name',
        headerName: 'Group',
        flex: 2,
        minWidth: 220,
        editable: false,
        cellRenderer: (params: ICellRendererParams<GroupRow>) => {
          const v = params.value as string;
          const sso = allGroups.find(
            (g) => g.id === params.data?._id,
          )?.sso_managed;
          return (
            <Group gap="xs" h="100%" wrap="nowrap">
              <Icon
                icon="mdi:account-group-outline"
                width={16}
                color="var(--mantine-color-gray-6)"
              />
              <Text size="sm">{v}</Text>
              {sso && (
                <Badge color="grape" variant="light" radius="sm" size="xs">
                  SSO
                </Badge>
              )}
            </Group>
          );
        },
      },
      ...(['Owner', 'Editor', 'Viewer'] as const).map(
        (role): ColDef<GroupRow> => ({
          field: role,
          headerName: role,
          width: 100,
          cellRenderer: 'agCheckboxCellRenderer',
          cellStyle: {
            textAlign: 'center',
            pointerEvents: canManage ? 'auto' : 'none',
          },
          editable: canManage,
          suppressKeyboardEvent: () => !canManage,
        }),
      ),
      {
        headerName: '',
        width: 70,
        sortable: false,
        filter: false,
        editable: false,
        cellRenderer: (params: ICellRendererParams<GroupRow>) => {
          if (!params.data) return null;
          return (
            <Center h="100%">
              <ActionIcon
                size="sm"
                variant="subtle"
                color="red"
                disabled={!canManage}
                title={canManage ? 'Remove group' : 'Owner permission required'}
                onClick={() => handleDeleteGroup(params.data!)}
              >
                <Icon icon="mdi:delete" width={16} />
              </ActionIcon>
            </Center>
          );
        },
      },
    ],
    [canManage, rows, groupRows, allGroups],
  );

  const shownPublic = pendingPublic !== null ? pendingPublic : Boolean(project?.is_public);
  const VisMark = shownPublic ? Globe : Lock;

  // Glass: visibility as a row, members as a list with the role on each row.
  const glassBody = project && (
    <div className="pm-page" data-testid="permissions-page">
      {!canManage && (
        <Alert color="yellow" variant="light" icon={<Lock size={18} strokeWidth={STROKE} />}>
          Read-only mode. Only project owners (or admins) can modify roles or visibility.
        </Alert>
      )}

      <section aria-label="Visibility">
        <div className="pm-visibility" data-public={shownPublic ? '' : undefined}>
          <span className="pm-chip">
            <VisMark size={20} strokeWidth={STROKE} aria-hidden />
          </span>
          <div className="pm-visibility-body">
            <div className="pm-visibility-title">{shownPublic ? 'Public' : 'Private'}</div>
            <div className="pm-visibility-text">
              {shownPublic
                ? 'Anyone signed in can view this project.'
                : 'Only listed members can view this project.'}
            </div>
          </div>
          <Switch
            checked={shownPublic}
            onChange={(e) => setPendingPublic(e.currentTarget.checked)}
            disabled={!canManage || visibilityBusy}
            aria-label="Public project"
            data-testid="project-visibility-switch"
          />
        </div>
      </section>

      <section aria-label="Members">
        <div className="pm-head">
          <Users size={18} strokeWidth={STROKE} aria-hidden />
          <Title order={4}>Members</Title>
          <span className="pm-count">{rows.length}</span>
        </div>
        <p className="pm-hint">
          <b>Owners</b> manage members and visibility, <b>editors</b> change the project's
          content, <b>viewers</b> can only look.
        </p>
        <ul className="pm-members">
          {rows.length === 0 && (
            <li className="pm-empty">No members yet. Add a teammate by email below.</li>
          )}
          {rows.map((r) => {
            const wildcard = r.email === '*';
            const isSelf = !!user && (r._id === user.id || r.email === user.email);
            const role = roleOf(r);
            const Mark = wildcard ? Globe : UserRound;
            return (
              <li
                key={r._id || r.email}
                className="pm-member"
                data-testid="permissions-member-row"
                data-email={r.email}
              >
                <Mark size={17} strokeWidth={STROKE} className="pm-member-icon" aria-hidden />
                <div className="pm-member-who">
                  <span className="pm-member-email">{wildcard ? 'All signed-in users' : r.email}</span>
                  {isSelf && (
                    <Badge color="gray" size="sm" className="gp-tag-plain">
                      You
                    </Badge>
                  )}
                  {r.is_admin && (
                    <Badge
                      color="gray"
                      size="sm"
                      className="gp-tag-plain"
                      leftSection={<ShieldCheck size={12} strokeWidth={STROKE} />}
                    >
                      Admin
                    </Badge>
                  )}
                </div>
                {canManage ? (
                  <SegmentedControl
                    size="xs"
                    className="pm-role"
                    value={role}
                    data={ROLES.map((x) => ({ label: x, value: x }))}
                    onChange={(v) => setRole(r, v as Role)}
                    aria-label={`Role of ${r.email}`}
                    data-testid="permissions-role-control"
                  />
                ) : (
                  <Badge
                    color={role === 'Owner' ? primary : role === 'Editor' ? 'indigo' : 'gray'}
                    size="sm"
                    className={role === 'Viewer' ? 'gp-tag-plain' : undefined}
                  >
                    {role || 'No role'}
                  </Badge>
                )}
                <div className="pm-member-end">
                  {canManage && (
                    <ActionIcon
                      size="md"
                      variant="subtle"
                      color="red"
                      title="Remove user"
                      aria-label={`Remove ${r.email}`}
                      onClick={() => handleDelete(r)}
                    >
                      <UserMinus size={17} strokeWidth={STROKE} />
                    </ActionIcon>
                  )}
                </div>
              </li>
            );
          })}
          {canManage && (
            <li className="pm-add">
              <Autocomplete
                flex={1}
                placeholder={
                  allUsers.length > 0
                    ? 'Search users, or * for all signed-in users'
                    : 'user@example.com, or * for all signed-in users'
                }
                value={emailInput}
                onChange={setEmailInput}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !adding) handleAdd();
                }}
                disabled={adding}
                leftSection={<UserPlus size={16} strokeWidth={STROKE} />}
                data={[
                  '*',
                  ...allUsers.map((u) => u.email).filter((e) => e && !rows.some((r) => r.email === e)),
                ]}
                limit={20}
                comboboxProps={{ withinPortal: true }}
                data-testid="permissions-add-user-input"
              />
              <Button
                loading={adding}
                onClick={handleAdd}
                disabled={!emailInput.trim()}
                data-testid="permissions-add-user-btn"
              >
                Add member
              </Button>
            </li>
          )}
        </ul>
      </section>

      <section aria-label="Groups">
        <div className="pm-head">
          <UsersRound size={18} strokeWidth={STROKE} aria-hidden />
          <Title order={4}>Groups</Title>
          <span className="pm-count">{groupRows.length}</span>
        </div>
        <p className="pm-hint">
          Every member of a group gets the group's role. A person's effective role is the
          highest of their own and their groups'.
        </p>
        <ul className="pm-members" data-testid="permissions-groups-grid">
          {groupRows.length === 0 && (
            <li className="pm-empty">No groups yet. Share this project with a group below.</li>
          )}
          {groupRows.map((r) => {
            const role = groupRoleOf(r);
            const sso = allGroups.find((g) => g.id === r._id)?.sso_managed;
            return (
              <li
                key={r._id || r.name}
                className="pm-member"
                data-testid="permissions-group-row"
                data-name={r.name}
              >
                <UsersRound size={17} strokeWidth={STROKE} className="pm-member-icon" aria-hidden />
                <div className="pm-member-who">
                  <span className="pm-member-email">{r.name}</span>
                  {sso && (
                    <Badge color="gray" size="sm" className="gp-tag-plain">
                      SSO
                    </Badge>
                  )}
                </div>
                {canManage ? (
                  <SegmentedControl
                    size="xs"
                    className="pm-role"
                    value={role}
                    data={ROLES.map((x) => ({ label: x, value: x }))}
                    onChange={(v) => setGroupRole(r, v as Role)}
                    aria-label={`Role of ${r.name}`}
                    data-testid="permissions-group-role-control"
                  />
                ) : (
                  <Badge
                    color={role === 'Owner' ? primary : role === 'Editor' ? 'indigo' : 'gray'}
                    size="sm"
                    className={role === 'Viewer' ? 'gp-tag-plain' : undefined}
                  >
                    {role || 'No role'}
                  </Badge>
                )}
                <div className="pm-member-end">
                  {canManage && (
                    <ActionIcon
                      size="md"
                      variant="subtle"
                      color="red"
                      title="Remove group"
                      aria-label={`Remove ${r.name}`}
                      onClick={() => handleDeleteGroup(r)}
                    >
                      <Trash2 size={17} strokeWidth={STROKE} />
                    </ActionIcon>
                  )}
                </div>
              </li>
            );
          })}
          {canManage && (
            <li className="pm-add">
              <Autocomplete
                flex={1}
                placeholder="Search groups"
                value={groupInput}
                onChange={setGroupInput}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !addingGroup) handleAddGroup();
                }}
                disabled={addingGroup}
                leftSection={<UsersRound size={16} strokeWidth={STROKE} />}
                // Suggestions: every known group not already on the project.
                data={allGroups
                  .map((g) => g.name)
                  .filter((n) => n && !groupRows.some((r) => r.name === n))}
                limit={20}
                comboboxProps={{ withinPortal: true }}
                data-testid="permissions-add-group-input"
              />
              <Button
                loading={addingGroup}
                onClick={handleAddGroup}
                disabled={!groupInput.trim()}
                data-testid="permissions-add-group-btn"
              >
                Add group
              </Button>
            </li>
          )}
        </ul>
      </section>
    </div>
  );

  const body = (
    <>
      {loading ? (
        <Center mih={300}>
          <Loader />
        </Center>
      ) : loadError ? (
        <Center mih={300}>
          <Stack align="center" gap="xs">
            {glass ? (
              <TriangleAlert size={32} strokeWidth={STROKE} color="var(--mantine-color-red-6)" aria-hidden />
            ) : (
              <Icon
                icon="mdi:alert-circle"
                width={32}
                color="var(--mantine-color-red-6)"
              />
            )}
            <Text c="red">{loadError}</Text>
            <Button component="a" href="/projects" variant={glass ? 'default' : 'light'}>
              Back to projects
            </Button>
          </Stack>
        </Center>
      ) : !project ? null : glass ? (
        glassBody
      ) : (
        <Stack gap="lg" data-testid="permissions-page">
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
                  label={
                    (pendingPublic !== null ? pendingPublic : project.is_public)
                      ? 'Public'
                      : 'Private'
                  }
                  checked={
                    pendingPublic !== null
                      ? pendingPublic
                      : Boolean(project.is_public)
                  }
                  // Switch color reflects the *off* (private) state in
                  // Mantine — Mantine swaps to `color` only when checked
                  // (= public). For the unchecked private state we set
                  // a violet thumb via styles to match the Dash badge.
                  color={accent.secondary}
                  styles={{
                    track: !(pendingPublic !== null
                      ? pendingPublic
                      : project.is_public)
                      ? {
                          backgroundColor: 'var(--mantine-color-violet-6)',
                          borderColor: 'var(--mantine-color-violet-6)',
                        }
                      : undefined,
                  }}
                  onChange={(e) => setPendingPublic(e.currentTarget.checked)}
                  disabled={!canManage || visibilityBusy}
                  data-testid="project-visibility-switch"
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
                data-testid="permissions-users-grid"
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
                    data-testid="permissions-add-user-input"
                  />
                  <Button
                    size="sm"
                    color={accent.secondary}
                    loading={adding}
                    onClick={handleAdd}
                    disabled={!emailInput.trim()}
                    leftSection={<Icon icon="mdi:plus" width={14} />}
                    data-testid="permissions-add-user-btn"
                  >
                    Add user
                  </Button>
                </Group>
              )}
            </Stack>
          </Card>

          <Card withBorder radius="md" p="md">
            <Stack gap="sm">
              <Group justify="space-between">
                <Group gap="xs">
                  <Icon
                    icon="mdi:account-group-outline"
                    width={22}
                    color="var(--mantine-color-blue-6)"
                  />
                  <Title order={5}>Groups</Title>
                  <Badge color="blue" variant="light" radius="sm" size="sm">
                    {groupRows.length}
                  </Badge>
                </Group>
              </Group>
              <Box
                className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
                style={{
                  height: Math.max(160, 56 + groupRows.length * 36 + 4),
                  width: '100%',
                }}
                data-testid="permissions-groups-grid"
              >
                <AgGridReact<GroupRow>
                  rowData={groupRows}
                  columnDefs={groupColDefs}
                  headerHeight={36}
                  rowHeight={36}
                  suppressCellFocus
                  onCellValueChanged={handleGroupCellChange}
                  stopEditingWhenCellsLoseFocus
                  overlayNoRowsTemplate={
                    '<span style="color:var(--mantine-color-dimmed);font-size:12px">No groups yet — share this project with a group below.</span>'
                  }
                />
              </Box>
              {canManage && (
                <Group gap="xs" align="flex-end">
                  <Autocomplete
                    flex={1}
                    size="sm"
                    label={undefined}
                    placeholder="Type to search groups…"
                    value={groupInput}
                    onChange={setGroupInput}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !addingGroup) handleAddGroup();
                    }}
                    disabled={addingGroup}
                    leftSection={<Icon icon="mdi:account-group-outline" width={16} />}
                    // Suggestions: every known group that isn't already
                    // attached to the project.
                    data={allGroups
                      .map((g) => g.name)
                      .filter((n) => n && !groupRows.some((r) => r.name === n))}
                    limit={20}
                    comboboxProps={{ withinPortal: true }}
                    data-testid="permissions-add-group-input"
                  />
                  <Button
                    size="sm"
                    color={accent.secondary}
                    loading={addingGroup}
                    onClick={handleAddGroup}
                    disabled={!groupInput.trim()}
                    leftSection={<Icon icon="mdi:plus" width={14} />}
                    data-testid="permissions-add-group-btn"
                  >
                    Add group
                  </Button>
                </Group>
              )}
            </Stack>
          </Card>
        </Stack>
      )}
    </>
  );

  const modals = (
    <>
      <Modal
        opened={pendingPublic !== null}
        onClose={() => {
          if (!visibilityBusy) setPendingPublic(null);
        }}
        title={<Text fw={600}>Change Project Visibility</Text>}
        centered
        size="md"
      >
        <Stack gap="lg">
          <Group justify="center" gap="md" wrap="nowrap">
            <VisibilityCard kind={project?.is_public ? 'public' : 'private'} role="from" glass={glass} />
            {glass ? (
              <ArrowRight size={24} strokeWidth={STROKE} color="var(--gl-faint)" aria-hidden />
            ) : (
              <Icon
                icon="mdi:arrow-right-bold"
                width={28}
                color="var(--mantine-color-dimmed)"
              />
            )}
            <VisibilityCard kind={pendingPublic ? 'public' : 'private'} role="to" glass={glass} />
          </Group>
          <Text size="sm" ta="center" c="dimmed">
            {pendingPublic
              ? 'Anyone signed in will be able to view this project.'
              : 'Only listed members will be able to view this project.'}
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button
              variant="default"
              onClick={() => setPendingPublic(null)}
              disabled={visibilityBusy}
            >
              Cancel
            </Button>
            <Button
              color={glass ? undefined : pendingPublic ? 'teal' : 'violet'}
              leftSection={
                glass ? (
                  pendingPublic ? <Globe size={16} strokeWidth={STROKE} /> : <Lock size={16} strokeWidth={STROKE} />
                ) : (
                  <Icon
                    icon={pendingPublic ? 'mdi:earth' : 'mdi:lock'}
                    width={16}
                  />
                )
              }
              onClick={confirmToggleVisibility}
              loading={visibilityBusy}
              data-testid="confirm-visibility-btn"
            >
              {pendingPublic ? 'Make Public' : 'Make Private'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );

  if (glass) {
    const name = project?.name || 'Project';
    return (
      <>
        <GlassPage
          section="projects"
          title="Permissions"
          description={`Who can see, edit and own ${name}.`}
          crumbs={[{ label: name, href: `/projects/${projectId}` }, { label: 'Permissions' }]}
          actions={
            <Button
              component="a"
              href={`/projects/${projectId}`}
              variant="default"
              leftSection={<Database size={17} strokeWidth={1.8} aria-hidden />}
            >
              Data collections
            </Button>
          }
        >
          {body}
        </GlassPage>
        {modals}
      </>
    );
  }

  return (
    <AppShell
      data-testid="app-shell"
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
              color={`var(--mantine-color-${accent.secondary}-6)`}
            />
            <Title order={3} c={accent.secondary}>
              Project Permissions
            </Title>
          </Group>
          <Group gap="xs">
            <Button
              component="a"
              href={`/projects/${projectId}`}
              variant="subtle"
              color={accent.secondary}
              leftSection={<Icon icon="mdi:database-outline" width={16} />}
            >
              Data Collections
            </Button>
            <Button
              component="a"
              href="/projects"
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
          {body}
        </Box>
      </AppShell.Main>
      {modals}
    </AppShell>
  );
};

export default PermissionsApp;
