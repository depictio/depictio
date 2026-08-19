import React, { useEffect, useState } from 'react';
import { Autocomplete, Button, Group, Modal, Stack, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { createGroup, listAllUsers } from 'depictio-react-core';
import type { GroupDetail } from 'depictio-react-core';

interface CreateGroupModalProps {
  opened: boolean;
  onClose: () => void;
  /** Receives the freshly created group so the caller can select it. */
  onCreated: (group: GroupDetail) => void;
}

const CreateGroupModal: React.FC<CreateGroupModalProps> = ({ opened, onClose, onCreated }) => {
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
        message:
          created.pending_pi_email
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
        <Autocomplete
          label="Principal Investigator"
          description="Optional — becomes a member and group admin. An address with no account yet is applied at their first sign-in."
          placeholder="pi@example.com"
          value={piEmail}
          onChange={setPiEmail}
          data={users.map((u) => u.email)}
          limit={20}
          comboboxProps={{ withinPortal: true }}
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

export default CreateGroupModal;
