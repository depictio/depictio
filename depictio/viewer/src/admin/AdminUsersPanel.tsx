import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  SegmentedControl,
  Stack,
  Text,
  useMantineTheme,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { ShieldCheck, Trash2, UserPlus, UserRound } from 'lucide-react';

import {
  listAllUsers,
  listGroups,
  fetchGroup,
  deleteUser as apiDeleteUser,
  setUserAdmin,
} from 'depictio-react-core';
import type { AdminUser } from 'depictio-react-core';

import { STROKE, useGlassPages } from '../chrome/variants/glass/pages';
import CreateUserModal from './CreateUserModal';
import DeleteUserModal from './DeleteUserModal';
import BulkDeleteModal from './BulkDeleteModal';
import { parseServerTimestamp } from '../lib/datetime';
import AdminTable, { type AdminTableColumn } from './AdminTable';
import Facts from './Facts';

type UserColumnKey =
  | 'email'
  | 'displayName'
  | 'login'
  | 'sso'
  | 'role'
  | 'status'
  | 'lastLogin'
  | 'registered'
  | 'groups';

interface UserRow {
  user: AdminUser;
  userId: string;
  isSelf: boolean;
  /** The built-in anonymous (public mode) account: never deletable. */
  isSystem: boolean;
  groups: string[];
}

/** Sort key of a server timestamp: epoch ms, or null when absent. */
function dateSort(raw: unknown): number | null {
  const d = parseServerTimestamp(raw);
  return d ? d.getTime() : null;
}

const NoValue: React.FC = () => (
  <Text span size="sm" c="dimmed">
    —
  </Text>
);

interface AdminUsersPanelProps {
  /** Email of the signed-in admin — used to disable destructive self-actions. */
  currentUserEmail: string | null;
}

function formatTimestamp(value: unknown): string {
  if (!value) return '—';
  if (typeof value !== 'string') return String(value);
  // Backend returns ISO strings like "2026-04-12T08:23:11" — try to format
  // them to "Month DD, YYYY HH:MM" to match the Dash page. Fallback to raw.
  const d = new Date(value.endsWith('Z') ? value : `${value}Z`);
  if (Number.isNaN(d.getTime())) return value;
  const month = d.toLocaleString('en-US', { month: 'long' });
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${month} ${pad(d.getDate())}, ${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const AdminUsersPanel: React.FC<AdminUsersPanelProps> = ({ currentUserEmail }) => {
  const glass = useGlassPages();
  const primary = useMantineTheme().primaryColor;
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [bulkTargets, setBulkTargets] = useState<UserRow[] | null>(null);
  const bulkItems = useMemo(
    () => (bulkTargets ?? []).map((r) => ({ id: r.userId, label: r.user.email || r.userId })),
    [bulkTargets],
  );
  const [createOpened, setCreateOpened] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  // user id -> names of the groups the user belongs to. Best effort: when the
  // group calls fail the table renders without group data.
  const [groupsByUser, setGroupsByUser] = useState<Map<string, string[]>>(new Map());

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listAllUsers()
      .then((list) => {
        if (cancelled) return;
        setUsers(list);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load users');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const summaries = await listGroups();
        const details = await Promise.allSettled(summaries.map((g) => fetchGroup(g.id)));
        const map = new Map<string, string[]>();
        for (const result of details) {
          if (result.status !== 'fulfilled') continue;
          const group = result.value;
          for (const m of group.members ?? []) {
            const names = map.get(String(m.id)) ?? [];
            names.push(group.name);
            map.set(String(m.id), names);
          }
        }
        for (const names of map.values()) names.sort((a, b) => a.localeCompare(b));
        if (!cancelled) setGroupsByUser(map);
      } catch {
        if (!cancelled) setGroupsByUser(new Map());
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const handleToggleAdmin = useCallback(
    async (user: AdminUser, value: 'True' | 'False') => {
      const userId = user.id ?? user._id;
      if (!userId) return;
      const isAdmin = value === 'True';
      try {
        await setUserAdmin(String(userId), isAdmin);
        notifications.show({
          color: 'teal',
          title: 'User updated',
          message: `${user.email} is now ${isAdmin ? 'a system admin' : 'a standard user'}.`,
          autoClose: 2500,
        });
        refresh();
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Update failed',
          message: (err as Error).message,
        });
      }
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (userId: string) => {
      await apiDeleteUser(userId);
      notifications.show({
        color: 'teal',
        title: 'User deleted',
        message: 'Account removed.',
        autoClose: 2000,
      });
      setDeleteTarget(null);
      refresh();
    },
    [refresh],
  );

  const rows = useMemo<UserRow[]>(
    () =>
      users.map((user) => {
        const userId = String(user.id ?? user._id ?? user.email);
        return {
          user,
          userId,
          isSelf:
            !!currentUserEmail && user.email?.toLowerCase() === currentUserEmail.toLowerCase(),
          isSystem: user.is_anonymous === true || /^anonymous@/i.test(user.email ?? ''),
          groups: groupsByUser.get(userId) ?? [],
        };
      }),
    [users, currentUserEmail, groupsByUser],
  );

  const columns = useMemo<AdminTableColumn<UserRow, UserColumnKey>[]>(
    () => [
      {
        key: 'email',
        label: 'Email',
        alwaysVisible: true,
        sortValue: (r) => r.user.email?.toLowerCase() ?? null,
        render: (r) => (
          <Group gap="sm" wrap="nowrap">
            {glass && (
              <UserRound size={17} strokeWidth={STROKE} className="ga-row-icon" aria-hidden />
            )}
            <Text fw={glass ? 550 : 500} size="sm" truncate>
              {r.user.email}
            </Text>
            {r.isSelf &&
              (glass ? (
                <Badge color="gray" size="sm" className="gp-tag-plain">
                  You
                </Badge>
              ) : (
                <Badge color="orange" variant="light" size="sm" radius="sm">
                  You
                </Badge>
              ))}
          </Group>
        ),
      },
      {
        key: 'displayName',
        label: 'Name',
        description: 'Display name',
        sortValue: (r) => r.user.display_name?.toLowerCase() ?? null,
        render: (r) => <Text size="sm">{r.user.display_name || <NoValue />}</Text>,
      },
      {
        key: 'login',
        label: 'Login',
        defaultVisible: false,
        sortValue: (r) => r.user.login?.toLowerCase() ?? null,
        render: (r) => <Text size="sm">{r.user.login || <NoValue />}</Text>,
      },
      {
        key: 'sso',
        label: 'SSO',
        description: 'SSO provider',
        defaultVisible: false,
        sortValue: (r) => r.user.sso_provider?.toLowerCase() ?? null,
        render: (r) => <Text size="sm">{r.user.sso_provider || <NoValue />}</Text>,
      },
      {
        key: 'role',
        label: 'Role',
        sortValue: (r) => (r.user.is_admin ? 'System admin' : 'User'),
        render: (r) =>
          glass ? (
            <Badge
              color={r.user.is_admin ? primary : 'gray'}
              size="sm"
              leftSection={
                r.user.is_admin ? <ShieldCheck size={12} strokeWidth={STROKE} /> : undefined
              }
              className={r.user.is_admin ? undefined : 'gp-tag-plain'}
            >
              {r.user.is_admin ? 'System admin' : 'User'}
            </Badge>
          ) : (
            <Badge
              color={r.user.is_admin ? 'blue' : 'gray'}
              variant="light"
              size="md"
              radius="sm"
            >
              {r.user.is_admin ? 'System Admin' : 'User'}
            </Badge>
          ),
      },
      {
        key: 'status',
        label: 'Status',
        description: 'Active / verified',
        // Inactive accounts first when sorting ascending.
        sortValue: (r) => (r.user.is_active === false ? 0 : r.user.is_verified ? 2 : 1),
        render: (r) => (
          <Group gap={6} wrap="nowrap">
            {r.user.is_active === false ? (
              <Badge color="red" variant="light" size="sm" radius="sm">
                Inactive
              </Badge>
            ) : (
              <Badge color="green" variant="light" size="sm" radius="sm">
                Active
              </Badge>
            )}
            {!r.user.is_verified && (
              <Badge color="gray" variant="light" size="sm" radius="sm">
                Unverified
              </Badge>
            )}
          </Group>
        ),
      },
      {
        key: 'lastLogin',
        label: 'Last login',
        sortValue: (r) => dateSort(r.user.last_login),
        render: (r) => <Text size="sm">{formatTimestamp(r.user.last_login)}</Text>,
      },
      {
        key: 'registered',
        label: 'Registered',
        defaultVisible: false,
        sortValue: (r) => dateSort(r.user.registration_date),
        render: (r) => <Text size="sm">{formatTimestamp(r.user.registration_date)}</Text>,
      },
      {
        key: 'groups',
        label: 'Groups',
        sortValue: (r) => (r.groups.length > 0 ? r.groups.join(', ').toLowerCase() : null),
        render: (r) =>
          r.groups.length === 0 ? (
            <NoValue />
          ) : (
            <Group gap={4}>
              {r.groups.map((name) => (
                <Badge
                  key={name}
                  color="gray"
                  variant="light"
                  size="sm"
                  radius="sm"
                  className={glass ? 'gp-tag-plain' : undefined}
                >
                  {name}
                </Badge>
              ))}
            </Group>
          ),
      },
    ],
    [glass, primary],
  );

  const searchText = useCallback(
    (r: UserRow) =>
      [
        r.user.email,
        r.user.display_name ?? '',
        r.user.login ?? '',
        r.user.sso_provider ?? '',
        r.user.is_admin ? 'admin system' : 'user',
        r.user.is_active === false ? 'inactive' : 'active',
        ...r.groups,
      ].join(' '),
    [],
  );

  const renderDetail = (row: UserRow) => {
    const { user, userId, isSelf } = row;
    const statusControl = (
      <SegmentedControl
        size="xs"
        color={glass ? undefined : 'blue'}
        value={user.is_admin ? 'True' : 'False'}
        data={[
          { label: 'Standard', value: 'False' },
          { label: 'System Admin', value: 'True' },
        ]}
        disabled={isSelf}
        onChange={(v) => handleToggleAdmin(user, v as 'True' | 'False')}
      />
    );
    return (
      <Stack gap="xs">
        <Facts
          items={[
            { label: 'User ID', value: String(userId ?? '—') },
            ...(user.display_name ? [{ label: 'Display name', value: user.display_name }] : []),
            ...(user.login ? [{ label: 'Login', value: user.login }] : []),
            ...(user.sso_provider ? [{ label: 'SSO provider', value: user.sso_provider }] : []),
            ...(row.groups.length > 0 ? [{ label: 'Groups', value: row.groups.join(', ') }] : []),
            {
              label: 'Registration date',
              value: formatTimestamp(user.registration_date),
            },
            { label: 'Last login', value: formatTimestamp(user.last_login) },
            {
              label: 'Account status',
              value: (
                <Badge
                  color={user.is_active ? 'green' : 'red'}
                  variant="light"
                  size="sm"
                  radius="sm"
                >
                  {user.is_active ? 'Active' : 'Inactive'}
                </Badge>
              ),
            },
            { label: 'Verified', value: user.is_verified ? 'Yes' : 'No' },
            ...(user.must_change_password
              ? [{ label: 'Password', value: 'Must be changed at next sign-in' }]
              : []),
            ...(glass ? [] : [{ label: 'User status', value: statusControl }]),
          ]}
        />
        {glass ? (
          <Group justify="space-between" gap="sm" className="ga-row-foot">
            <Group gap="xs">
              <Text size="sm" c="dimmed">
                Role
              </Text>
              {statusControl}
            </Group>
            <Button
              color="red"
              variant="subtle"
              size="xs"
              leftSection={<Trash2 size={14} strokeWidth={STROKE} />}
              disabled={isSelf}
              title={isSelf ? 'You cannot delete your own account' : undefined}
              onClick={() => setDeleteTarget(user)}
            >
              Delete user
            </Button>
          </Group>
        ) : (
          <Group gap="xs" mt="sm">
            <Text fw="bold" size="sm">
              Actions:
            </Text>
            <Button
              color="red"
              variant="filled"
              size="xs"
              leftSection={<Icon icon="tabler:trash" width={14} />}
              disabled={isSelf}
              onClick={() => setDeleteTarget(user)}
            >
              Delete
            </Button>
          </Group>
        )}
      </Stack>
    );
  };

  if (loading) {
    return (
      <Center mih={200}>
        <Loader />
      </Center>
    );
  }

  if (error) {
    return (
      <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
        {error}
      </Alert>
    );
  }

  if (rows.length === 0) {
    return (
      <Center mih={200}>
        <Stack align="center" gap="xs">
          <Icon icon="ph:empty-bold" width={48} color="var(--mantine-color-dimmed)" />
          <Text c="dimmed">No users found.</Text>
        </Stack>
      </Center>
    );
  }

  return (
    <>
      <AdminTable
        rows={rows}
        rowKey={(r) => r.userId}
        columns={columns}
        storageKey="depictio.admin.users.columns.v1"
        defaultSort={{ key: 'email' }}
        searchText={searchText}
        searchPlaceholder="Search users..."
        renderDetail={renderDetail}
        selection={{
          getId: (r) => r.userId,
          isSelectable: (r) => !r.isSelf && !r.isSystem,
          disabledReason: (r) => (r.isSelf ? 'You cannot delete yourself' : 'System account'),
          actions: (selected, clear) => (
            <Button
              className="gp-danger"
              color="red"
              variant="filled"
              size="xs"
              leftSection={<Icon icon="tabler:trash" width={14} />}
              onClick={() => {
                setBulkTargets(selected);
                clear();
              }}
            >
              Delete selected
            </Button>
          ),
        }}
        toolbarExtra={
          <Button
            size={glass ? 'sm' : 'xs'}
            color={glass ? undefined : 'teal'}
            leftSection={
              glass ? (
                <UserPlus size={15} strokeWidth={STROKE} aria-hidden />
              ) : (
                <Icon icon="mdi:account-plus-outline" width={14} />
              )
            }
            onClick={() => setCreateOpened(true)}
            data-testid="admin-create-user-btn"
          >
            Add user
          </Button>
        }
      />
      <CreateUserModal
        opened={createOpened}
        onClose={() => setCreateOpened(false)}
        onCreated={() => {
          setCreateOpened(false);
          refresh();
        }}
      />
      <DeleteUserModal
        opened={Boolean(deleteTarget)}
        user={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
      <BulkDeleteModal
        opened={bulkTargets !== null}
        noun="users"
        nounSingular="user"
        items={bulkItems}
        note="Accounts, sessions and personal data are removed. Dashboards and projects they own remain."
        onDelete={(id) => apiDeleteUser(id)}
        onDone={refresh}
        onClose={() => setBulkTargets(null)}
      />
    </>
  );
};

export default AdminUsersPanel;
