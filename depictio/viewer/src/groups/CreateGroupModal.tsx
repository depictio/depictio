import React, { useEffect, useState } from 'react';
import { Autocomplete, Button, Center, Group, Modal, Stack, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { createGroup, listAllUsers } from 'depictio-react-core';
import type { GroupDetail } from 'depictio-react-core';

import { useListingAccents } from '../lib/useListingAccents';

interface CreateGroupModalProps {
  opened: boolean;
  onClose: () => void;
  /** Receives the freshly created group so the caller can select it. */
  onCreated: (group: GroupDetail) => void;
}

const CreateGroupModal: React.FC<CreateGroupModalProps> = ({ opened, onClose, onCreated }) => {
  // Same chrome as the Create project / Create dashboard dialogs.
  const accent = useListingAccents('projects');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  /** Free text on purpose: a P.I. who has no account yet is designated by
   *  email and claimed at their first sign-in. */
  const [piEmail, setPiEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [users, setUsers] = useState<{ id: string; email: string }[]>([]);

  useEffect(() => {
    if (!opened) return;
    setName('');
    setDescription('');
    setPiEmail('');
    setSubmitting(false);
    let cancelled = false;
    listAllUsers()
      .then((list) => {
        if (cancelled) return;
        setUsers(
          list
            .map((u) => ({ id: String(u.id ?? u._id ?? ''), email: u.email }))
            .filter((u) => u.id && u.email)
            .sort((a, b) => a.email.localeCompare(b.email)),
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
    const email = piEmail.trim().toLowerCase();
    // Known address → a normal designation; anything else is parked on the
    // group server-side and applied when that person first signs in.
    const known = users.find((u) => u.email.toLowerCase() === email);
    setSubmitting(true);
    try {
      const created = await createGroup({
        name: trimmed,
        description: description.trim() || undefined,
        pi_id: known ? known.id : undefined,
        pi_email: !known && email ? email : undefined,
      });
      notifications.show({
        color: 'teal',
        title: 'Group created',
        message: created.pending_pi_email
          ? `Group "${trimmed}" created — ${created.pending_pi_email} becomes P.I. at first sign-in.`
          : `Group "${trimmed}" created.`,
        autoClose: 3500,
      });
      onCreated(created);
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Creation failed',
        message: (err as Error).message,
      });
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!submitting) onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      centered
      size="md"
      withCloseButton
      closeOnClickOutside={false}
      closeOnEscape={!submitting}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      title={null}
      padding="lg"
    >
      <Stack gap="md" data-testid="create-group-modal">
        <Center>
          <Group gap="xs">
            <Icon
              icon="mdi:account-multiple-plus-outline"
              width={28}
              color={`var(--mantine-color-${accent.secondary}-6)`}
            />
            <Title
              order={2}
              c={accent.secondary}
              style={{ fontFamily: 'Virgil', fontWeight: 400 }}
            >
              New group
            </Title>
          </Group>
        </Center>
        <TextInput
          label="Group name"
          description="A short, unique name"
          placeholder="Enter group name"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
          disabled={submitting}
          leftSection={<Icon icon="mdi:account-multiple-outline" width={16} />}
          data-autofocus
          data-testid="create-group-name"
        />
        <TextInput
          label="Description (Optional)"
          description="What the group is for"
          placeholder="Enter description (optional)"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          disabled={submitting}
          leftSection={<Icon icon="mdi:text-box-outline" width={16} />}
          data-testid="create-group-description"
        />
        <Autocomplete
          label="Principal Investigator (Optional)"
          description="Becomes a member and group admin. An address with no account yet is applied at their first sign-in."
          placeholder="pi@example.com"
          value={piEmail}
          onChange={setPiEmail}
          data={users.map((u) => u.email)}
          limit={20}
          disabled={submitting}
          comboboxProps={{ withinPortal: true }}
          leftSection={<Icon icon="mdi:account-star-outline" width={16} />}
          data-testid="create-group-pi"
        />
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color={accent.secondary}
            leftSection={<Icon icon="mdi:plus" width={16} />}
            onClick={handleCreate}
            loading={submitting}
            disabled={!name.trim()}
            data-testid="create-group-submit"
          >
            Create group
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default CreateGroupModal;
