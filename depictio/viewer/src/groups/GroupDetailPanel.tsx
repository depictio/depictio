import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Autocomplete,
  Badge,
  Box,
  Button,
  Center,
  Group,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
  useComputedColorScheme,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { CellValueChangedEvent, ColDef, ICellRendererParams } from 'ag-grid-community';

import {
  addGroupMember,
  listAllUsers,
  removeGroupMember,
  setGroupAdmin,
  setGroupPendingPI,
  setGroupPI,
  updateGroup,
} from 'depictio-react-core';
import type { GroupDetail, GroupMember } from 'depictio-react-core';

import { useCurrentUser } from '../hooks/useCurrentUser';

interface GroupDetailPanelProps {
  group: GroupDetail;
  /** Rename, add/remove members and the group-admin toggle. False renders
   *  the same table read-only (plain member of somebody else's group). */
  canManage: boolean;
  /** P.I. designation is sysadmin-only server-side — only the admin surface
   *  passes true. Group admins manage members but never the P.I. */
  canEditPI: boolean;
  /** Called after every successful mutation so the owner can re-fetch. */
  onChanged: () => void;
  /** Rendered as the panel's delete action. Omitted for protected/seeded
   *  groups and on the non-admin surface. */
  onDelete?: () => void;
}

/** Directory entry resolved from the admin-only /auth/list endpoint. */
interface DirectoryUser {
  id: string;
  email: string;
}

const ROW_HEIGHT = 36;

const GroupDetailPanel: React.FC<GroupDetailPanelProps> = ({
  group,
  canManage,
  canEditPI,
  onChanged,
  onDelete,
}) => {
  const { user: currentUser } = useCurrentUser();
  const colorScheme = useComputedColorScheme('light', { getInitialValueInEffect: true });
  const isDark = colorScheme === 'dark';

  // ---- rename / description ------------------------------------------------
  const [name, setName] = useState(group.name);
  const [description, setDescription] = useState(group.description ?? '');
  const [savingMeta, setSavingMeta] = useState(false);

  useEffect(() => {
    setName(group.name);
    setDescription(group.description ?? '');
  }, [group.id, group.name, group.description]);

  const metaDirty = name.trim() !== group.name || description.trim() !== (group.description ?? '');

  const handleSaveMeta = useCallback(async () => {
    if (!name.trim()) {
      notifications.show({
        color: 'red',
        title: 'Invalid name',
        message: 'Group name cannot be empty.',
      });
      return;
    }
    setSavingMeta(true);
    try {
      await updateGroup(group.id, { name: name.trim(), description: description.trim() });
      notifications.show({
        color: 'teal',
        title: 'Group updated',
        message: `Saved changes to "${name.trim()}".`,
        autoClose: 2500,
      });
      onChanged();
    } catch (err) {
      notifications.show({ color: 'red', title: 'Update failed', message: (err as Error).message });
    } finally {
      setSavingMeta(false);
    }
  }, [group.id, name, description, onChanged]);

  // ---- add member ----------------------------------------------------------
  // The user directory comes from the admin-only /auth/list endpoint. Group
  // admins that are not sysadmins get a 403 — degrade to a plain email input.
  const [directory, setDirectory] = useState<DirectoryUser[] | null>(null);
  const [directoryFailed, setDirectoryFailed] = useState(false);
  const [addEmail, setAddEmail] = useState('');
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (!canManage) return;
    let cancelled = false;
    listAllUsers()
      .then((users) => {
        if (cancelled) return;
        setDirectory(
          users
            .map((u) => ({ id: String(u.id ?? u._id ?? ''), email: u.email }))
            .filter((u) => u.id && u.email),
        );
      })
      .catch(() => {
        if (!cancelled) setDirectoryFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [canManage]);

  const memberEmails = useMemo(
    () => new Set(group.members.map((m) => m.email.toLowerCase())),
    [group.members],
  );

  const addCandidates = useMemo(
    () =>
      (directory ?? [])
        .map((u) => u.email)
        .filter((email) => !memberEmails.has(email.toLowerCase()))
        .sort((a, b) => a.localeCompare(b)),
    [directory, memberEmails],
  );

  const handleAddMember = useCallback(async () => {
    const email = addEmail.trim().toLowerCase();
    if (!email) return;
    const match = (directory ?? []).find((u) => u.email.toLowerCase() === email);
    if (!match) {
      notifications.show({
        color: 'red',
        title: 'User not found',
        message: `No user with email "${addEmail.trim()}" could be resolved.`,
      });
      return;
    }
    setAdding(true);
    try {
      await addGroupMember(group.id, match.id);
      notifications.show({
        color: 'teal',
        title: 'Member added',
        message: `${match.email} added to "${group.name}".`,
        autoClose: 2500,
      });
      setAddEmail('');
      onChanged();
    } catch (err) {
      notifications.show({ color: 'red', title: 'Add failed', message: (err as Error).message });
    } finally {
      setAdding(false);
    }
  }, [addEmail, directory, group.id, group.name, onChanged]);

  // ---- mutations driven from the grid --------------------------------------
  const handleToggleAdmin = useCallback(
    async (member: GroupMember, makeAdmin: boolean) => {
      try {
        await setGroupAdmin(group.id, member.id, makeAdmin);
        notifications.show({
          color: 'teal',
          title: 'Member updated',
          message: `${member.email} is now ${makeAdmin ? 'a group admin' : 'a regular member'}.`,
          autoClose: 2500,
        });
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Update failed',
          message: (err as Error).message,
        });
      } finally {
        // Re-fetch either way: the grid holds an optimistic checkbox value
        // that must snap back to the server's answer when the call failed.
        onChanged();
      }
    },
    [group.id, onChanged],
  );

  const handleSetPI = useCallback(
    async (member: GroupMember) => {
      try {
        await setGroupPI(group.id, member.id);
        notifications.show({
          color: 'teal',
          title: 'P.I. updated',
          message: `${member.email} is now the P.I. of "${group.name}".`,
          autoClose: 2500,
        });
        onChanged();
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'P.I. update failed',
          message: (err as Error).message,
        });
      }
    },
    [group.id, group.name, onChanged],
  );

  // ---- deferred P.I. (designated by email before the account exists) -------
  const [pendingEmail, setPendingEmail] = useState('');
  const [pendingBusy, setPendingBusy] = useState(false);

  useEffect(() => {
    setPendingEmail('');
  }, [group.id]);

  const handleSetPendingPI = useCallback(async () => {
    const email = pendingEmail.trim().toLowerCase();
    if (!email) return;
    setPendingBusy(true);
    try {
      const updated = await setGroupPendingPI(group.id, email);
      notifications.show({
        color: 'teal',
        title: updated.pi_id ? 'P.I. designated' : 'P.I. designation parked',
        message: updated.pi_id
          ? `${email} already has an account and is now the P.I.`
          : `${email} becomes P.I. of "${group.name}" at their first sign-in.`,
        autoClose: 3500,
      });
      setPendingEmail('');
      onChanged();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Designation failed',
        message: (err as Error).message,
      });
    } finally {
      setPendingBusy(false);
    }
  }, [group.id, group.name, pendingEmail, onChanged]);

  const handleClearPendingPI = useCallback(async () => {
    setPendingBusy(true);
    try {
      await setGroupPendingPI(group.id, null);
      notifications.show({
        color: 'teal',
        title: 'Designation cleared',
        message: `No pending P.I. on "${group.name}" anymore.`,
        autoClose: 2500,
      });
      onChanged();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Clear failed',
        message: (err as Error).message,
      });
    } finally {
      setPendingBusy(false);
    }
  }, [group.id, group.name, onChanged]);

  // ---- remove member -------------------------------------------------------
  const [removeTarget, setRemoveTarget] = useState<GroupMember | null>(null);
  const [removing, setRemoving] = useState(false);

  const handleRemoveMember = useCallback(async () => {
    if (!removeTarget) return;
    setRemoving(true);
    try {
      await removeGroupMember(group.id, removeTarget.id);
      notifications.show({
        color: 'teal',
        title: 'Member removed',
        message: `${removeTarget.email} removed from "${group.name}".`,
        autoClose: 2500,
      });
      setRemoveTarget(null);
      onChanged();
    } catch (err) {
      notifications.show({ color: 'red', title: 'Remove failed', message: (err as Error).message });
    } finally {
      setRemoving(false);
    }
  }, [group.id, group.name, removeTarget, onChanged]);

  const isSelf = useCallback(
    (member: GroupMember) => {
      if (!currentUser) return false;
      if (currentUser.id && currentUser.id === member.id) return true;
      return currentUser.email.toLowerCase() === member.email.toLowerCase();
    },
    [currentUser],
  );

  // ---- members grid --------------------------------------------------------
  const [memberFilter, setMemberFilter] = useState('');

  useEffect(() => {
    setMemberFilter('');
  }, [group.id]);

  const memberColDefs = useMemo<ColDef<GroupMember>[]>(
    () => [
      { field: 'id', hide: true },
      {
        field: 'email',
        headerName: 'Member',
        flex: 2,
        minWidth: 220,
        editable: false,
        cellRenderer: (params: ICellRendererParams<GroupMember>) => (
          <Group gap="xs" h="100%" wrap="nowrap">
            <Icon
              icon="mdi:account-circle-outline"
              width={16}
              color="var(--mantine-color-gray-6)"
            />
            <Text size="sm" truncate>
              {params.value as string}
            </Text>
            {params.data && isSelf(params.data) && (
              <Badge color="orange" variant="light" size="xs" radius="sm">
                You
              </Badge>
            )}
          </Group>
        ),
      },
      {
        field: 'display_name',
        headerName: 'Name',
        flex: 1,
        minWidth: 120,
        editable: false,
        cellRenderer: (params: ICellRendererParams<GroupMember>) => (
          <Text size="sm" c="dimmed" truncate>
            {(params.value as string) || '—'}
          </Text>
        ),
      },
      {
        field: 'is_group_admin',
        headerName: 'Group admin',
        width: 130,
        cellRenderer: 'agCheckboxCellRenderer',
        cellStyle: { textAlign: 'center' },
        // The backend rejects self-demotion — lock the current user's own
        // row while they hold the role (mirrors AdminUsersPanel).
        editable: (params) =>
          canManage && !(params.data ? isSelf(params.data) && params.data.is_group_admin : false),
        suppressKeyboardEvent: () => !canManage,
      },
      {
        field: 'is_pi',
        headerName: 'P.I.',
        width: 90,
        editable: false,
        sortable: true,
        cellRenderer: (params: ICellRendererParams<GroupMember>) => {
          if (!params.data) return null;
          if (params.data.is_pi) {
            return (
              <Center h="100%">
                <Badge
                  color="yellow"
                  variant="light"
                  size="sm"
                  radius="sm"
                  leftSection={<Icon icon="mdi:crown-outline" width={12} />}
                >
                  P.I.
                </Badge>
              </Center>
            );
          }
          if (!canEditPI) return null;
          return (
            <Center h="100%">
              <Tooltip label="Designate as P.I." withArrow>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="yellow"
                  aria-label={`Designate ${params.data.email} as P.I.`}
                  onClick={() => handleSetPI(params.data!)}
                  data-testid="group-set-pi-btn"
                >
                  <Icon icon="mdi:crown-outline" width={16} />
                </ActionIcon>
              </Tooltip>
            </Center>
          );
        },
      },
      {
        headerName: '',
        colId: 'actions',
        width: 70,
        sortable: false,
        filter: false,
        editable: false,
        hide: !canManage,
        cellRenderer: (params: ICellRendererParams<GroupMember>) => {
          if (!params.data) return null;
          return (
            <Center h="100%">
              <ActionIcon
                size="sm"
                variant="subtle"
                color="red"
                title="Remove from group"
                aria-label={`Remove ${params.data.email} from group`}
                onClick={() => setRemoveTarget(params.data!)}
                data-testid="group-remove-member-btn"
              >
                <Icon icon="mdi:delete" width={16} />
              </ActionIcon>
            </Center>
          );
        },
      },
    ],
    [canManage, canEditPI, handleSetPI, isSelf],
  );

  const handleMemberCellChange = useCallback(
    (event: CellValueChangedEvent<GroupMember>) => {
      if (event.colDef.field !== 'is_group_admin' || !event.data) return;
      handleToggleAdmin(event.data, Boolean(event.newValue));
    },
    [handleToggleAdmin],
  );

  return (
    <Stack gap="md" data-testid="group-management-card">
      {/* Header: identity + destructive action */}
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          <Icon icon="mdi:account-multiple-outline" width={22} color="var(--mantine-color-grape-6)" />
          <Title order={4} lineClamp={1}>
            {group.name}
          </Title>
          {group.sso_managed && (
            <Tooltip label="Synced from SSO — manual changes may be overwritten at next login.">
              <Badge color="grape" variant="light" size="sm" radius="sm">
                SSO
              </Badge>
            </Tooltip>
          )}
          <Badge color="gray" variant="light" size="sm" radius="sm">
            {group.members.length} member{group.members.length === 1 ? '' : 's'}
          </Badge>
        </Group>
        {onDelete && (
          <Button
            color="red"
            variant="light"
            size="xs"
            leftSection={<Icon icon="tabler:trash" width={14} />}
            onClick={onDelete}
            data-testid="admin-delete-group-btn"
          >
            Delete group
          </Button>
        )}
      </Group>

      {/* Rename / description */}
      {canManage ? (
        <Group align="flex-end" gap="xs" wrap="wrap">
          <TextInput
            label="Name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            size="xs"
            style={{ flex: 1, minWidth: 160 }}
            data-testid="group-rename-input"
          />
          <TextInput
            label="Description"
            placeholder="No description"
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            size="xs"
            style={{ flex: 2, minWidth: 220 }}
            data-testid="group-description-input"
          />
          <Button
            size="xs"
            variant="light"
            leftSection={<Icon icon="mdi:content-save-outline" width={14} />}
            onClick={handleSaveMeta}
            loading={savingMeta}
            disabled={!metaDirty}
            data-testid="group-save-meta-btn"
          >
            Save
          </Button>
        </Group>
      ) : (
        group.description && (
          <Text size="sm" c="dimmed">
            {group.description}
          </Text>
        )
      )}

      {group.sso_managed && canManage && (
        <Alert color="grape" variant="light" icon={<Icon icon="mdi:cloud-sync-outline" />} py="xs">
          Synced from SSO — manual changes may be overwritten at next login.
        </Alert>
      )}

      {/* Deferred P.I.: parked on an email until that person first signs in.
          Members who already have an account are promoted from the grid's
          crown action instead. */}
      {group.pending_pi_email ? (
        <Alert
          color="yellow"
          variant="light"
          icon={<Icon icon="mdi:crown-outline" />}
          py="xs"
          data-testid="group-pending-pi"
        >
          <Group justify="space-between" wrap="nowrap" gap="xs">
            <Text size="sm">
              P.I. pending — <b>{group.pending_pi_email}</b> becomes P.I. and group admin at their
              first sign-in.
            </Text>
            {canEditPI && (
              <Button
                size="compact-xs"
                variant="subtle"
                color="yellow"
                onClick={handleClearPendingPI}
                loading={pendingBusy}
                data-testid="group-clear-pending-pi"
              >
                Clear
              </Button>
            )}
          </Group>
        </Alert>
      ) : (
        canEditPI &&
        !group.pi_id && (
          <Group align="flex-end" gap="xs" wrap="nowrap">
            <TextInput
              flex={1}
              size="xs"
              label="Principal Investigator"
              description="Email of the P.I. — applied at their first sign-in when they have no account yet."
              placeholder="pi@example.com"
              value={pendingEmail}
              onChange={(e) => setPendingEmail(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !pendingBusy) handleSetPendingPI();
              }}
              leftSection={<Icon icon="mdi:crown-outline" width={14} />}
              data-testid="group-pending-pi-input"
            />
            <Button
              size="xs"
              variant="light"
              color="yellow"
              onClick={handleSetPendingPI}
              loading={pendingBusy}
              disabled={!pendingEmail.trim()}
              data-testid="group-pending-pi-btn"
            >
              Designate
            </Button>
          </Group>
        )
      )}

      {/* Members */}
      <Stack gap="xs">
        <Group justify="space-between" gap="xs" wrap="nowrap">
          <Group gap="xs">
            <Text fw={600} size="sm">
              Members
            </Text>
            <Badge color="blue" variant="light" size="sm" radius="sm">
              {group.members.length}
            </Badge>
          </Group>
          <TextInput
            size="xs"
            w={220}
            placeholder="Filter members…"
            value={memberFilter}
            onChange={(e) => setMemberFilter(e.currentTarget.value)}
            leftSection={<Icon icon="mdi:magnify" width={14} />}
            data-testid="group-member-filter"
          />
        </Group>
        <Box
          className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
          style={{
            height: Math.min(520, Math.max(140, 44 + group.members.length * ROW_HEIGHT)),
            width: '100%',
          }}
          data-testid="group-members-grid"
        >
          <AgGridReact<GroupMember>
            rowData={group.members}
            columnDefs={memberColDefs}
            getRowId={(params) => params.data.id}
            headerHeight={36}
            rowHeight={ROW_HEIGHT}
            suppressCellFocus
            quickFilterText={memberFilter}
            onCellValueChanged={handleMemberCellChange}
            stopEditingWhenCellsLoseFocus
            overlayNoRowsTemplate={
              '<span style="color:var(--mantine-color-dimmed);font-size:12px">This group has no members yet.</span>'
            }
          />
        </Box>

        {canManage && (
          <Group gap="xs" align="flex-end" wrap="nowrap">
            {directoryFailed ? (
              <TextInput
                flex={1}
                size="sm"
                placeholder="user@example.com"
                value={addEmail}
                onChange={(e) => setAddEmail(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !adding) handleAddMember();
                }}
                leftSection={<Icon icon="mdi:account-plus-outline" width={16} />}
                data-testid="group-add-member-input"
              />
            ) : (
              <Autocomplete
                flex={1}
                size="sm"
                placeholder="Type to search users…"
                value={addEmail}
                onChange={setAddEmail}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !adding) handleAddMember();
                }}
                data={addCandidates}
                limit={20}
                comboboxProps={{ withinPortal: true }}
                leftSection={<Icon icon="mdi:account-plus-outline" width={16} />}
                data-testid="group-add-member-input"
              />
            )}
            <Button
              size="sm"
              color="teal"
              leftSection={<Icon icon="mdi:plus" width={14} />}
              onClick={handleAddMember}
              loading={adding}
              disabled={!addEmail.trim()}
              data-testid="group-add-member-btn"
            >
              Add member
            </Button>
          </Group>
        )}
      </Stack>

      {/* Remove confirmation */}
      <Modal
        opened={Boolean(removeTarget)}
        onClose={() => setRemoveTarget(null)}
        title="Remove member"
        size="md"
        centered
      >
        <Stack gap="sm">
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert" />}>
            Remove &quot;{removeTarget?.email}&quot; from &quot;{group.name}&quot;? They lose any
            group-admin role in this group; projects shared with the group become inaccessible to
            them.
          </Alert>
          <Group justify="flex-end" gap="xs">
            <Button variant="subtle" onClick={() => setRemoveTarget(null)} disabled={removing}>
              Cancel
            </Button>
            <Button
              color="red"
              leftSection={<Icon icon="tabler:trash" width={14} />}
              onClick={handleRemoveMember}
              loading={removing}
              data-testid="group-remove-member-confirm"
            >
              Remove
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};

/** Placeholder for the detail pane before a group is picked. */
export const GroupDetailPlaceholder: React.FC<{ message: string }> = ({ message }) => (
  <Paper withBorder radius="md" p="xl" h="100%">
    <Center h="100%" mih={200}>
      <Stack align="center" gap="xs">
        <Icon icon="mdi:account-multiple-outline" width={40} color="var(--mantine-color-dimmed)" />
        <Text c="dimmed" size="sm" ta="center">
          {message}
        </Text>
      </Stack>
    </Center>
  </Paper>
);

export default GroupDetailPanel;
