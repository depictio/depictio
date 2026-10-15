import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Accordion,
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
  deleteUser as apiDeleteUser,
  setUserAdmin,
} from 'depictio-react-core';
import type { AdminUser } from 'depictio-react-core';

import { STROKE, useGlassPages } from '../chrome/variants/glass/pages';
import CreateUserModal from './CreateUserModal';
import DeleteUserModal from './DeleteUserModal';
import Facts from './Facts';

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
  const [createOpened, setCreateOpened] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

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

  const sortedUsers = useMemo(
    () =>
      [...users].sort((a, b) => {
        const ax = a.email?.toLowerCase() ?? '';
        const bx = b.email?.toLowerCase() ?? '';
        return ax.localeCompare(bx);
      }),
    [users],
  );

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

  if (sortedUsers.length === 0) {
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
      <Group justify="flex-end" mb="sm">
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
      </Group>
      <Accordion radius="md" variant="separated" multiple className={glass ? 'ga-rows' : undefined}>
        {sortedUsers.map((user) => {
          const userId = user.id ?? user._id;
          const isSelf =
            !!currentUserEmail && user.email?.toLowerCase() === currentUserEmail.toLowerCase();
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
            <Accordion.Item key={String(userId)} value={String(userId)}>
              <Accordion.Control>
                {glass ? (
                  <Group gap="sm" wrap="nowrap">
                    <UserRound size={17} strokeWidth={STROKE} className="ga-row-icon" aria-hidden />
                    <Text fw={550} size="sm" style={{ flex: 1, minWidth: 0 }} truncate>
                      {user.email}
                    </Text>
                    <Group gap={6} wrap="nowrap">
                      {isSelf && (
                        <Badge color="gray" size="sm" className="gp-tag-plain">
                          You
                        </Badge>
                      )}
                      {!user.is_active && (
                        <Badge color="red" size="sm">
                          Inactive
                        </Badge>
                      )}
                      <Badge
                        color={user.is_admin ? primary : 'gray'}
                        size="sm"
                        leftSection={
                          user.is_admin ? <ShieldCheck size={12} strokeWidth={STROKE} /> : undefined
                        }
                        className={user.is_admin ? undefined : 'gp-tag-plain'}
                      >
                        {user.is_admin ? 'System admin' : 'User'}
                      </Badge>
                    </Group>
                  </Group>
                ) : (
                  <Group justify="space-between" wrap="nowrap">
                    <Text fw={500} size="lg" style={{ flex: 1, minWidth: 0 }} truncate>
                      {user.email}
                    </Text>
                    <Group gap="xs">
                      {isSelf && (
                        <Badge color="orange" variant="light" size="sm" radius="sm">
                          You
                        </Badge>
                      )}
                      <Badge
                        color={user.is_admin ? 'blue' : 'gray'}
                        variant="light"
                        size="md"
                        radius="sm"
                      >
                        {user.is_admin ? 'System Admin' : 'User'}
                      </Badge>
                    </Group>
                  </Group>
                )}
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="xs">
                  <Facts
                    items={[
                      { label: 'User ID', value: String(userId ?? '—') },
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
              </Accordion.Panel>
            </Accordion.Item>
          );
        })}
      </Accordion>
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
    </>
  );
};

export default AdminUsersPanel;
