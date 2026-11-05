import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  CopyButton,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { createMigrationInvite, listMigrationInvites } from 'depictio-react-core';
import { formatDateTime } from '../lib/datetime';
import type {
  MigrationInvite,
} from 'depictio-react-core';

const VALIDITY: { value: string; label: string; hours: number }[] = [
  { value: '1', label: '1 day', hours: 24 },
  { value: '30', label: '30 days', hours: 720 },
  { value: '365', label: '1 year', hours: 8760 },
];

const CopyRow: React.FC<{ label: string; value: string; testId: string }> = ({
  label,
  value,
  testId,
}) => (
  <TextInput
    label={label}
    value={value}
    readOnly
    ff="monospace"
    onFocus={(e) => e.currentTarget.select()}
    data-testid={testId}
    rightSection={
      <CopyButton value={value} timeout={1500}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? 'Copied' : 'Copy'} withinPortal>
            <Button
              size="compact-xs"
              variant="subtle"
              color={copied ? 'teal' : 'gray'}
              onClick={copy}
              aria-label={`Copy ${label.toLowerCase()}`}
            >
              <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
            </Button>
          </Tooltip>
        )}
      </CopyButton>
    }
    rightSectionWidth={44}
  />
);

export interface ReceiveProjectModalProps {
  opened: boolean;
  onClose: () => void;
  /** Called after an invite was created, so a listing behind the modal refreshes. */
  onCreated?: (invite: MigrationInvite) => void;
}

/**
 * Admin of the receiving instance: issue an invite code. The owner of a project
 * on another instance pastes this instance's URL and the code into "Publish
 * to…"; the import starts right away, with no review. The code is shown once.
 */
const ReceiveProjectModal: React.FC<ReceiveProjectModalProps> = ({
  opened,
  onClose,
  onCreated,
}) => {
  const [loading, setLoading] = useState(false);
  const [inboundEnabled, setInboundEnabled] = useState(true);
  const [lock, setLock] = useState(true);
  const [validity, setValidity] = useState('30');
  const [note, setNote] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<(MigrationInvite & { code: string }) | null>(null);

  useEffect(() => {
    if (!opened) {
      // The code must not outlive the dialog.
      setCreated(null);
      setError(null);
      setNote('');
      return undefined;
    }
    let live = true;
    setLoading(true);
    listMigrationInvites()
      .then((r) => {
        if (!live) return;
        setInboundEnabled(r.inbound_enabled);
        setLock(r.defaults.lock_on_import);
        // The default lifetime, when it is one of the choices.
        const days = String(r.defaults.ttl_days);
        setValidity(VALIDITY.some((v) => v.value === days) ? days : '30');
      })
      .catch((err) => live && setError(err instanceof Error ? err.message : 'Failed to load.'))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [opened]);

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const invite = await createMigrationInvite({
        lock_on_import: lock,
        expires_in_hours: VALIDITY.find((v) => v.value === validity)?.hours ?? 720,
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      setCreated(invite);
      onCreated?.(invite);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create the invitation.');
    } finally {
      setCreating(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Receive a project"
      centered
      size="md"
      data-testid="receive-project-modal"
    >
      <Stack gap="md">
        {loading ? (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              Loading…
            </Text>
          </Group>
        ) : !inboundEnabled ? (
          <Alert color="yellow" variant="light" data-testid="receive-disabled">
            This instance does not accept pushed projects. Set
            DEPICTIO_MIGRATION_INBOUND_ENABLED to allow it.
          </Alert>
        ) : created ? (
          <Stack gap="sm" data-testid="receive-created">
            <Text size="sm">
              Send these two values to the owner of the project. In their project, they choose
              Publish to… and paste both.
            </Text>
            <CopyRow
              label="Instance URL"
              value={window.location.origin}
              testId="receive-url"
            />
            <CopyRow label="Code" value={created.code} testId="receive-code" />
            <Text size="xs" c="dimmed">
              The first project sent with this code is imported. The same code then publishes
              that project's updates until{' '}
              {created.expires_at ? formatDateTime(created.expires_at) : 'it is revoked'}. It is
              shown only once.
            </Text>
          </Stack>
        ) : (
          <>
            <Switch
              label="Lock editing on import"
              description="The imported project is read-only, owners included, until an admin unlocks it."
              checked={lock}
              onChange={(e) => setLock(e.currentTarget.checked)}
              data-testid="receive-lock"
            />
            <Stack gap={6}>
              <Text size="sm" fw={500}>
                Valid for
              </Text>
              <SegmentedControl
                fullWidth
                value={validity}
                onChange={setValidity}
                data={VALIDITY.map(({ value, label }) => ({ value, label }))}
                data-testid="receive-validity"
              />
            </Stack>
            <TextInput
              label="Note"
              description="Optional. Who this is for; shown in the list of invitations."
              maxLength={200}
              value={note}
              onChange={(e) => setNote(e.currentTarget.value)}
              data-testid="receive-note"
            />
          </>
        )}
        {error && (
          <Alert color="red" variant="light" data-testid="receive-error">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="subtle" color="gray" onClick={onClose}>
            {created ? 'Done' : 'Cancel'}
          </Button>
          {!created && inboundEnabled && (
            <Button
              loading={creating}
              disabled={loading}
              onClick={() => void handleCreate()}
              leftSection={<Icon icon="mdi:key-plus" width={16} />}
              data-testid="receive-create"
            >
              Create code
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
};

export default ReceiveProjectModal;
