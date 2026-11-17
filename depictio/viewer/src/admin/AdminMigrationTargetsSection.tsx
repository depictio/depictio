import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  PasswordInput,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  createMigrationTarget,
  deleteMigrationTarget,
  listMigrationTargets,
} from 'depictio-react-core';
import type { MigrationTarget } from 'depictio-react-core';

import { SettingsSection } from '../components/settings/SettingsSections';

/**
 * Admin Settings > "Push targets": the other Depictio instances this one may
 * push projects to. Targets from the deployment environment are read-only;
 * targets added here (when the instance allows it) can be removed. The pairing
 * key is write-only: the server never returns it, only a short fingerprint.
 */
const AdminMigrationTargetsSection: React.FC<{ readOnly?: boolean }> = ({ readOnly = false }) => {
  const [targets, setTargets] = useState<MigrationTarget[]>([]);
  const [allowUi, setAllowUi] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [key, setKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await listMigrationTargets();
      setTargets(res.targets);
      setAllowUi(res.allow_ui_targets);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load push targets.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const canAdd = name.trim() !== '' && url.trim() !== '' && key.length >= 32;

  const handleAdd = async () => {
    setSaving(true);
    try {
      await createMigrationTarget({ name: name.trim(), url: url.trim(), pairing_key: key });
      setName('');
      setUrl('');
      setKey('');
      notifications.show({ message: 'Push target added.' });
      await load();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not add the target',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (t: MigrationTarget) => {
    setDeleting(t.id);
    try {
      await deleteMigrationTarget(t.id);
      notifications.show({ message: `Removed ${t.name}.` });
      await load();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not remove the target',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setDeleting(null);
    }
  };

  return (
    <SettingsSection
      value="push-targets"
      icon="mdi:transfer-up"
      title="Push targets"
      subtitle="Other Depictio instances that projects can be pushed to for review"
      testId="admin-settings-push-targets"
    >
      <Stack gap="md">
        {loading ? (
          <Loader size="sm" />
        ) : error ? (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        ) : targets.length === 0 ? (
          <Text size="sm" c="dimmed" data-testid="push-targets-empty">
            No push targets configured.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={560}>
            <Table fz="sm" withTableBorder data-testid="push-targets-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Name</Table.Th>
                  <Table.Th>URL</Table.Th>
                  <Table.Th>Defined in</Table.Th>
                  <Table.Th>Key</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {targets.map((t) => (
                  <Table.Tr key={t.id} data-testid="push-target-row">
                    <Table.Td>{t.name}</Table.Td>
                    <Table.Td>
                      <Text size="sm" style={{ wordBreak: 'break-all' }}>
                        {t.url}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" color="gray" size="sm">
                        {t.source === 'env' ? 'Environment' : 'UI'}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      {t.key_fingerprint ? <Code>{t.key_fingerprint}</Code> : '—'}
                    </Table.Td>
                    <Table.Td>
                      {t.source === 'ui' && (
                        <Tooltip label="Remove this target" withinPortal>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            aria-label={`Remove ${t.name}`}
                            disabled={readOnly}
                            loading={deleting === t.id}
                            onClick={() => void handleDelete(t)}
                            data-testid="push-target-delete"
                          >
                            <Icon icon="tabler:trash" width={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}

        {allowUi && (
          <Stack gap="xs" data-testid="push-target-form">
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Add a target
            </Text>
            <Group grow align="flex-start">
              <TextInput
                label="Name"
                value={name}
                onChange={(e) => setName(e.currentTarget.value)}
                disabled={readOnly || saving}
                data-testid="push-target-name"
              />
              <TextInput
                label="URL"
                placeholder="https://depictio.example.org"
                value={url}
                onChange={(e) => setUrl(e.currentTarget.value)}
                disabled={readOnly || saving}
                data-testid="push-target-url"
              />
            </Group>
            <PasswordInput
              label="Pairing key"
              description="Issued by the target instance's administrator (at least 32 characters). Stored encrypted; never shown again."
              value={key}
              onChange={(e) => setKey(e.currentTarget.value)}
              disabled={readOnly || saving}
              autoComplete="off"
              data-testid="push-target-key"
            />
            <Group justify="flex-end">
              <Button
                onClick={() => void handleAdd()}
                loading={saving}
                disabled={readOnly || !canAdd}
                leftSection={<Icon icon="mdi:plus" width={16} />}
                data-testid="push-target-add"
              >
                Add target
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </SettingsSection>
  );
};

export default AdminMigrationTargetsSection;
