import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Group,
  Modal,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { TOKEN_SCOPES, type TokenScope } from 'depictio-react-core';

import { SectionHeader } from '../components/settings/SettingsSections';

interface CreateTokenModalProps {
  opened: boolean;
  onClose: () => void;
  /** Submit handler — should throw with a user-readable Error message on
   *  failure (e.g. duplicate name). Modal captures and displays the message
   *  via the inline alert. Resolved on success → modal closes via parent. */
  onSubmit: (name: string, scopes: TokenScope[] | null) => Promise<void>;
  existingNames: string[];
}

type AccessMode = 'full' | 'agent' | 'custom';

/** Scopes of the "Agent (MCP)" preset: read, comment and write reports. */
const AGENT_SCOPES: TokenScope[] = ['read', 'annotate', 'report'];

const SCOPE_LABELS: Record<TokenScope, { label: string; description: string }> = {
  read: {
    label: 'Read',
    description: 'Browse projects, dashboards and component data (always included).',
  },
  annotate: {
    label: 'Annotate',
    description: 'Open comment threads and reply to them.',
  },
  report: {
    label: 'Report',
    description: 'Run AI analyses and write reports.',
  },
  edit_dashboard: {
    label: 'Edit dashboards',
    description: 'Create, edit and import dashboards, including AI generation.',
  },
  ingest: {
    label: 'Ingest data',
    description: 'Create projects from runs and upload data.',
  },
};

function sameScopes(a: TokenScope[], b: TokenScope[]): boolean {
  return a.length === b.length && a.every((s) => b.includes(s));
}

/** Names a new CLI configuration and its access (full, or a set of scopes for an
 *  agent token), and posts to /auth/me/tokens via the parent's onSubmit handler.
 *  Headed like the Account settings sections it opens from. */
const CreateTokenModal: React.FC<CreateTokenModalProps> = ({
  opened,
  onClose,
  onSubmit,
  existingNames,
}) => {
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [mode, setMode] = useState<AccessMode>('full');
  const [scopes, setScopes] = useState<TokenScope[]>(AGENT_SCOPES);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!opened) {
      setName('');
      setNameError(null);
      setMode('full');
      setScopes(AGENT_SCOPES);
      setError(null);
      setSubmitting(false);
    }
  }, [opened]);

  const handleModeChange = (value: string) => {
    const next = value as AccessMode;
    setMode(next);
    if (next === 'agent') setScopes(AGENT_SCOPES);
  };

  const handleScopesChange = (values: string[]) => {
    // ``read`` is implied by every scope, so it stays checked.
    const next = Array.from(new Set<TokenScope>(['read', ...(values as TokenScope[])]));
    setScopes(next);
    setMode(sameScopes(next, AGENT_SCOPES) ? 'agent' : 'custom');
  };

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError('Give the configuration a name.');
      return;
    }
    if (existingNames.includes(trimmed)) {
      setNameError('A configuration already has this name.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(trimmed, mode === 'full' ? null : scopes);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create configuration.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      title={
        <SectionHeader
          icon="mdi:console-line"
          title="New CLI configuration"
          subtitle="A token and its settings, for the depictio CLI"
        />
      }
    >
      <Stack
        gap="md"
        data-testid="create-cli-token-modal"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !submitting) {
            e.preventDefault();
            void handleSave();
          }
        }}
      >
        <TextInput
          label="Name"
          description="To tell your configurations apart, for example the machine it runs on."
          placeholder="laptop, cluster, CI"
          data-autofocus
          value={name}
          onChange={(e) => {
            setName(e.currentTarget.value);
            setNameError(null);
          }}
          error={nameError}
          disabled={submitting}
          data-testid="cli-config-name-input"
        />

        <Stack gap="xs">
          <Text size="sm" fw={500}>
            Access
          </Text>
          <SegmentedControl
            value={mode}
            onChange={handleModeChange}
            disabled={submitting}
            data={[
              { value: 'full', label: 'Full access' },
              { value: 'agent', label: 'Agent (MCP)' },
              { value: 'custom', label: 'Custom' },
            ]}
            data-testid="cli-config-access-mode"
          />
          {mode === 'full' ? (
            <Text size="xs" c="dimmed">
              The token can do everything your account can. Use it for the CLI.
            </Text>
          ) : (
            <Checkbox.Group
              value={scopes}
              onChange={handleScopesChange}
              description="Scoped tokens cannot manage tokens, users, backups or deletions."
              data-testid="cli-config-scopes"
            >
              <Stack gap="xs" mt="xs">
                {TOKEN_SCOPES.map((scope) => (
                  <Checkbox
                    key={scope}
                    value={scope}
                    label={SCOPE_LABELS[scope].label}
                    description={SCOPE_LABELS[scope].description}
                    disabled={submitting || scope === 'read'}
                  />
                ))}
              </Stack>
            </Checkbox.Group>
          )}
        </Stack>

        {error && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" width={18} />}>
            {error}
          </Alert>
        )}

        <Group justify="flex-end" gap="xs" mt="xs">
          <Button variant="subtle" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSave} loading={submitting} data-testid="save-cli-config-btn">
            Create
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default CreateTokenModal;
