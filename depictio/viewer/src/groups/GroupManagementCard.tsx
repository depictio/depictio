import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Autocomplete,
  Badge,
  Button,
  Divider,
  Group,
  Modal,
  Select,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  addGroupMember,
  listAllUsers,
  removeGroupMember,
  setGroupAdmin,
  setGroupPI,
  updateGroup,
} from 'depictio-react-core';
import type { GroupDetail, GroupMember } from 'depictio-react-core';

import { useCurrentUser } from '../hooks/useCurrentUser';

interface GroupManagementCardProps {
  group: GroupDetail;
  /** P.I. designation is sysadmin-only server-side — only the admin page
   *  passes true. Group admins manage members but never the P.I. */
  canEditPI: boolean;
  /** Called after every successful mutation so the owner can re-fetch. */
  onChanged: () => void;
}

/** Directory entry resolved from the admin-only /auth/list endpoint. */
interface DirectoryUser {
  id: string;
  email: string;
}

const GroupManagementCard: React.FC<GroupManagementCardProps> = ({
  group,
  canEditPI,
  onChanged,
}) => {
  const { user: currentUser } = useCurrentUser();

  // ---- rename / description ------------------------------------------------
  const [name, setName] = useState(group.name);
  const [description, setDescription] = useState(group.description ?? '');
  const [savingMeta, setSavingMeta] = useState(false);

  useEffect(() => {
    setName(group.name);
    setDescription(group.description ?? '');
  }, [group.id, group.name, group.description]);

  const metaDirty =
    name.trim() !== group.name || description.trim() !== (group.description ?? '');

  const handleSaveMeta = useCallback(async () => {
    if (!name.trim()) {
      notifications.show({ color: 'red', title: 'Invalid name', message: 'Group name cannot be empty.' });
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
  }, []);

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

  // ---- admin toggle --------------------------------------------------------
  const handleToggleAdmin = useCallback(
    async (member: GroupMember, value: 'admin' | 'member') => {
      const makeAdmin = value === 'admin';
      if (makeAdmin === member.is_group_admin) return;
      try {
        await setGroupAdmin(group.id, member.id, makeAdmin);
        notifications.show({
          color: 'teal',
          title: 'Member updated',
          message: `${member.email} is now ${makeAdmin ? 'a group admin' : 'a regular member'}.`,
          autoClose: 2500,
        });
        onChanged();
      } catch (err) {
        notifications.show({ color: 'red', title: 'Update failed', message: (err as Error).message });
      }
    },
    [group.id, onChanged],
  );

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

  // ---- P.I. designation (sysadmin only) ------------------------------------
  const handleSetPI = useCallback(
    async (memberId: string | null) => {
      if (!memberId || memberId === (group.pi_id ?? null)) return;
      const member = group.members.find((m) => m.id === memberId);
      try {
        await setGroupPI(group.id, memberId);
        notifications.show({
          color: 'teal',
          title: 'P.I. updated',
          message: `${member?.email ?? memberId} is now the P.I. of "${group.name}".`,
          autoClose: 2500,
        });
        onChanged();
      } catch (err) {
        notifications.show({ color: 'red', title: 'P.I. update failed', message: (err as Error).message });
      }
    },
    [group.id, group.name, group.members, group.pi_id, onChanged],
  );

  const isSelf = useCallback(
    (member: GroupMember) => {
      if (!currentUser) return false;
      if (currentUser.id && currentUser.id === member.id) return true;
      return currentUser.email.toLowerCase() === member.email.toLowerCase();
    },
    [currentUser],
  );

  const piSelectData = useMemo(
    () => group.members.map((m) => ({ value: m.id, label: m.email })),
    [group.members],
  );

  return (
    <Stack gap="md" data-testid="group-management-card">
      {group.sso_managed && (
        <Alert
          color="yellow"
          variant="light"
          icon={<Icon icon="mdi:cloud-sync-outline" />}
          title="Synced from SSO"
        >
          Synced from SSO — manual changes may be overwritten at next login.
        </Alert>
      )}

      {/* Rename / description */}
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

      <Divider label="Members" labelPosition="left" />

      {/* Member list */}
      <Stack gap="xs">
        {group.members.length === 0 && (
          <Text c="dimmed" size="sm">
            This group has no members yet.
          </Text>
        )}
        {group.members.map((member) => {
          const self = isSelf(member);
          return (
            <Group
              key={member.id}
              justify="space-between"
              wrap="nowrap"
              gap="xs"
              data-testid="group-member-row"
            >
              <Group gap="xs" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
                <Text size="sm" fw={500} truncate>
                  {member.email}
                </Text>
                {member.display_name && (
                  <Text size="xs" c="dimmed" truncate>
                    {member.display_name}
                  </Text>
                )}
                {member.is_pi && (
                  <Badge
                    color="yellow"
                    variant="light"
                    size="sm"
                    radius="sm"
                    leftSection={<Icon icon="mdi:crown-outline" width={12} />}
                  >
                    P.I.
                  </Badge>
                )}
                {member.is_group_admin && (
                  <Badge color="blue" variant="light" size="sm" radius="sm">
                    Admin
                  </Badge>
                )}
                {self && (
                  <Badge color="orange" variant="light" size="sm" radius="sm">
                    You
                  </Badge>
                )}
              </Group>
              <Group gap="xs" wrap="nowrap">
                <SegmentedControl
                  size="xs"
                  color="blue"
                  value={member.is_group_admin ? 'admin' : 'member'}
                  data={[
                    { label: 'Member', value: 'member' },
                    { label: 'Admin', value: 'admin' },
                  ]}
                  // Backend rejects self-demotion; disable the toggle for the
                  // current user's own row (mirrors AdminUsersPanel).
                  disabled={self && member.is_group_admin}
                  onChange={(v) => handleToggleAdmin(member, v as 'admin' | 'member')}
                  data-testid="group-admin-toggle"
                />
                <ActionIcon
                  color="red"
                  variant="light"
                  size="md"
                  onClick={() => setRemoveTarget(member)}
                  aria-label={`Remove ${member.email} from group`}
                  data-testid="group-remove-member-btn"
                >
                  <Icon icon="tabler:trash" width={16} />
                </ActionIcon>
              </Group>
            </Group>
          );
        })}
      </Stack>

      {/* Add member */}
      <Group align="flex-end" gap="xs" wrap="nowrap">
        {directoryFailed ? (
          <TextInput
            label="Add member"
            placeholder="user@example.com"
            value={addEmail}
            onChange={(e) => setAddEmail(e.currentTarget.value)}
            size="xs"
            style={{ flex: 1 }}
            data-testid="group-add-member-input"
          />
        ) : (
          <Autocomplete
            label="Add member"
            placeholder="user@example.com"
            value={addEmail}
            onChange={setAddEmail}
            data={addCandidates}
            limit={20}
            size="xs"
            style={{ flex: 1 }}
            data-testid="group-add-member-input"
          />
        )}
        <Button
          color="teal"
          size="xs"
          leftSection={<Icon icon="mdi:account-plus-outline" width={14} />}
          onClick={handleAddMember}
          loading={adding}
          disabled={!addEmail.trim()}
          data-testid="group-add-member-btn"
        >
          Add
        </Button>
      </Group>

      {/* P.I. designation — sysadmin only */}
      {canEditPI && (
        <Select
          label="Principal Investigator"
          description="The P.I. is automatically a member and group admin."
          placeholder="Select a member"
          value={group.pi_id ?? null}
          data={piSelectData}
          onChange={handleSetPI}
          size="xs"
          maw={360}
          searchable
          leftSection={<Icon icon="mdi:crown-outline" width={14} />}
          data-testid="group-pi-select"
        />
      )}

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
            group-admin role in this group; projects shared with the group become inaccessible
            to them.
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

export default GroupManagementCard;
