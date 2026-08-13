import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  createGroup,
  deleteGroup as apiDeleteGroup,
  fetchGroup,
  listAllUsers,
  listGroups,
} from 'depictio-react-core';
import type { GroupDetail, GroupSummary } from 'depictio-react-core';

import GroupManagementCard from '../groups/GroupManagementCard';
import DeleteGroupModal from './DeleteGroupModal';

/** Seeded groups the permission system bootstraps around — the backend
 *  refuses to delete them (400), so hide the button entirely. */
const PROTECTED_GROUP_NAMES = new Set(['admin', 'users']);

const AdminGroupsPanel: React.FC = () => {
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [openedItems, setOpenedItems] = useState<string[]>([]);
  const [details, setDetails] = useState<Record<string, GroupDetail | 'loading' | 'error'>>({});
  const [deleteTarget, setDeleteTarget] = useState<GroupSummary | null>(null);
  const [createOpened, setCreateOpened] = useState(false);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    // Only show the blocking loader on first load — background refreshes
    // (post-mutation) keep the accordion in place.
    setError(null);
    listGroups()
      .then((list) => {
        if (cancelled) return;
        setGroups(list);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load groups');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const loadDetail = useCallback((groupId: string) => {
    setDetails((prev) => ({ ...prev, [groupId]: prev[groupId] ?? 'loading' }));
    fetchGroup(groupId)
      .then((detail) => {
        setDetails((prev) => ({ ...prev, [groupId]: detail }));
      })
      .catch(() => {
        setDetails((prev) => ({ ...prev, [groupId]: 'error' }));
      });
  }, []);

  const handleAccordionChange = useCallback(
    (values: string[]) => {
      setOpenedItems(values);
      // Lazy-fetch details the first time an item is expanded.
      for (const groupId of values) {
        if (!details[groupId]) loadDetail(groupId);
      }
    },
    [details, loadDetail],
  );

  const handleGroupChanged = useCallback(
    (groupId: string) => {
      loadDetail(groupId);
      refresh();
    },
    [loadDetail, refresh],
  );

  const handleDelete = useCallback(
    async (groupId: string) => {
      await apiDeleteGroup(groupId);
      notifications.show({
        color: 'teal',
        title: 'Group deleted',
        message: 'Group removed and permission references cleaned up.',
        autoClose: 2500,
      });
      setDeleteTarget(null);
      setDetails((prev) => {
        const next = { ...prev };
        delete next[groupId];
        return next;
      });
      refresh();
    },
    [refresh],
  );

  const sortedGroups = useMemo(
    () => [...groups].sort((a, b) => a.name.localeCompare(b.name)),
    [groups],
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

  return (
    <>
      <Group justify="flex-end" mb="md">
        <Button
          color="teal"
          leftSection={<Icon icon="mdi:account-multiple-plus-outline" width={16} />}
          onClick={() => setCreateOpened(true)}
          data-testid="admin-create-group-btn"
        >
          Create group
        </Button>
      </Group>

      {sortedGroups.length === 0 ? (
        <Center mih={200}>
          <Stack align="center" gap="xs">
            <Icon icon="ph:empty-bold" width={48} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed">No groups found.</Text>
          </Stack>
        </Center>
      ) : (
        <Accordion
          radius="md"
          variant="separated"
          multiple
          value={openedItems}
          onChange={handleAccordionChange}
        >
          {sortedGroups.map((group) => {
            const detail = details[group.id];
            const isProtected = PROTECTED_GROUP_NAMES.has(group.name.toLowerCase());
            return (
              <Accordion.Item key={group.id} value={group.id} data-testid="admin-group-item">
                <Accordion.Control>
                  <Group justify="space-between" wrap="nowrap">
                    <Text fw={500} size="lg" style={{ flex: 1, minWidth: 0 }} truncate>
                      {group.name}
                    </Text>
                    <Group gap="xs" wrap="nowrap">
                      {group.sso_managed && (
                        <Tooltip label="Synced from SSO — manual changes may be overwritten at next login.">
                          <Badge color="yellow" variant="light" size="sm" radius="sm">
                            SSO
                          </Badge>
                        </Tooltip>
                      )}
                      <Badge color="gray" variant="light" size="md" radius="sm">
                        {group.member_count} member{group.member_count === 1 ? '' : 's'}
                      </Badge>
                    </Group>
                  </Group>
                </Accordion.Control>
                <Accordion.Panel>
                  {!detail || detail === 'loading' ? (
                    <Center mih={80}>
                      <Loader size="sm" />
                    </Center>
                  ) : detail === 'error' ? (
                    <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
                      Failed to load group details.
                    </Alert>
                  ) : (
                    <Stack gap="md">
                      <GroupManagementCard
                        group={detail}
                        canEditPI
                        onChanged={() => handleGroupChanged(group.id)}
                      />
                      {!isProtected && (
                        <Group gap="xs">
                          <Button
                            color="red"
                            variant="filled"
                            size="xs"
                            leftSection={<Icon icon="tabler:trash" width={14} />}
                            onClick={() => setDeleteTarget(group)}
                            data-testid="admin-delete-group-btn"
                          >
                            Delete group
                          </Button>
                        </Group>
                      )}
                    </Stack>
                  )}
                </Accordion.Panel>
              </Accordion.Item>
            );
          })}
        </Accordion>
      )}

      <DeleteGroupModal
        opened={Boolean(deleteTarget)}
        group={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />

      <CreateGroupModal
        opened={createOpened}
        onClose={() => setCreateOpened(false)}
        onCreated={() => {
          setCreateOpened(false);
          refresh();
        }}
      />
    </>
  );
};

// ---- Create modal ----------------------------------------------------------

interface CreateGroupModalProps {
  opened: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const CreateGroupModal: React.FC<CreateGroupModalProps> = ({ opened, onClose, onCreated }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [piId, setPiId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [users, setUsers] = useState<{ value: string; label: string }[]>([]);

  useEffect(() => {
    if (!opened) return;
    setName('');
    setDescription('');
    setPiId(null);
    setSubmitting(false);
    let cancelled = false;
    listAllUsers()
      .then((list) => {
        if (cancelled) return;
        setUsers(
          list
            .map((u) => ({ value: String(u.id ?? u._id ?? ''), label: u.email }))
            .filter((u) => u.value)
            .sort((a, b) => a.label.localeCompare(b.label)),
        );
      })
      .catch(() => {
        if (!cancelled) setUsers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [opened]);

  const handleCreate = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setSubmitting(true);
    try {
      await createGroup({
        name: trimmed,
        description: description.trim() || undefined,
        pi_id: piId ?? undefined,
      });
      notifications.show({
        color: 'teal',
        title: 'Group created',
        message: `Group "${trimmed}" created.`,
        autoClose: 2500,
      });
      onCreated();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Creation failed',
        message: (err as Error).message,
      });
      setSubmitting(false);
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Create group" size="md" centered>
      <Stack gap="sm">
        <TextInput
          label="Name"
          placeholder="e.g. korbel-lab"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
          data-autofocus
          data-testid="create-group-name"
        />
        <TextInput
          label="Description"
          placeholder="Optional description"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          data-testid="create-group-description"
        />
        <Select
          label="Principal Investigator"
          description="Optional — the P.I. becomes a member and group admin."
          placeholder="Select a user"
          value={piId}
          onChange={setPiId}
          data={users}
          searchable
          clearable
          data-testid="create-group-pi"
        />
        <Group justify="flex-end" gap="xs" mt="sm">
          <Button variant="subtle" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color="teal"
            leftSection={<Icon icon="mdi:plus" width={14} />}
            onClick={handleCreate}
            loading={submitting}
            disabled={!name.trim()}
            data-testid="create-group-submit"
          >
            Create
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default AdminGroupsPanel;
