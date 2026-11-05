import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  CopyButton,
  Group,
  Loader,
  Modal,
  NumberInput,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { createMigrationInvite, listMigrationInvites } from 'depictio-react-core';
import type {
  MigrationInvite,
  MigrationInviteDefaults,
  MigrationInvitePolicy,
} from 'depictio-react-core';

const POLICY_TEXT: Record<MigrationInvitePolicy, string> = {
  single_use:
    'One push: the code works once, then stops. Valid for about an hour by default.',
  lineage:
    'Push + updates: keep the code to send new versions of the same project later. Valid for weeks; to update a project later, choose this one.',
};

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
  const [defaults, setDefaults] = useState<MigrationInviteDefaults | null>(null);
  const [policy, setPolicy] = useState<MigrationInvitePolicy>('single_use');
  const [lock, setLock] = useState(true);
  const [hours, setHours] = useState<number | string>('');
  const [note, setNote] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<(MigrationInvite & { code: string }) | null>(null);

  useEffect(() => {
    if (!opened) {
      // The code must not outlive the dialog.
      setCreated(null);
      setError(null);
      setHours('');
      setNote('');
      setPolicy('single_use');
      return undefined;
    }
    let live = true;
    setLoading(true);
    listMigrationInvites()
      .then((r) => {
        if (!live) return;
        setInboundEnabled(r.inbound_enabled);
        setDefaults(r.defaults);
        setLock(r.defaults.lock_on_import);
      })
      .catch((err) => live && setError(err instanceof Error ? err.message : 'Failed to load.'))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [opened]);

  const defaultHours = defaults
    ? policy === 'single_use'
      ? defaults.single_use_ttl_hours
      : defaults.lineage_ttl_days * 24
    : undefined;
  const maxHours = defaults ? defaults.max_ttl_days * 24 : undefined;

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const invite = await createMigrationInvite({
        policy,
        lock_on_import: lock,
        ...(typeof hours === 'number' ? { expires_in_hours: hours } : {}),
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
            <CopyRow label="Invite code" value={created.code} testId="receive-code" />
            <Alert color="yellow" variant="light" icon={<Icon icon="mdi:alert-outline" />}>
              This code will not be shown again. Copy it now; if it is lost, revoke it and
              create another.
            </Alert>
            <Text size="xs" c="dimmed">
              {created.policy === 'single_use' ? 'One push' : 'Push + updates'}
              {created.lock_on_import ? ', editing locked on import' : ', editable after import'}
            </Text>
          </Stack>
        ) : (
          <>
            <Stack gap={6}>
              <Text size="sm" fw={500}>
                Policy
              </Text>
              <SegmentedControl
                fullWidth
                value={policy}
                onChange={(v) => setPolicy(v as MigrationInvitePolicy)}
                data={[
                  { value: 'single_use', label: 'One push' },
                  { value: 'lineage', label: 'Push + updates' },
                ]}
                data-testid="receive-policy"
              />
              <Text size="xs" c="dimmed">
                {POLICY_TEXT[policy]}
              </Text>
            </Stack>
            <Switch
              label="Lock editing on import"
              description="The imported project is read-only, owners included, until an admin unlocks it."
              checked={lock}
              onChange={(e) => setLock(e.currentTarget.checked)}
              data-testid="receive-lock"
            />
            <NumberInput
              label="Lifetime (hours)"
              description={
                defaultHours !== undefined
                  ? `Optional. Default ${defaultHours} h${maxHours ? `, at most ${maxHours} h` : ''}.`
                  : 'Optional.'
              }
              placeholder={defaultHours !== undefined ? String(defaultHours) : undefined}
              min={1}
              max={maxHours}
              allowDecimal={false}
              value={hours}
              onChange={setHours}
              data-testid="receive-hours"
            />
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
              Create invitation
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
};

export default ReceiveProjectModal;
