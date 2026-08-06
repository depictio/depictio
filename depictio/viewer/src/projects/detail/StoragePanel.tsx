import React, { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  PasswordInput,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  deleteProjectStorage,
  getProjectStorage,
  setProjectStorage,
  testProjectStorage,
} from 'depictio-react-core';
import type { ProjectStorageConfig } from 'depictio-react-core';

interface StoragePanelProps {
  projectId: string;
  /** Only project owners (or admins) may view/edit storage credentials —
   *  stricter than the page-level `canMutate`, which includes editors. */
  canManage: boolean;
}

/** One "label: value" line of the configured-state summary. */
const ConfigRow: React.FC<{ label: string; value: string | null }> = ({
  label,
  value,
}) => (
  <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
    <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
      {label}
    </Text>
    <Text size="xs" fw={500} ff="monospace" truncate>
      {value || '—'}
    </Text>
  </Group>
);

/** Edit/create form for the storage config. The secret field is write-only:
 *  when a secret is already stored, leaving it empty keeps it (the PUT body
 *  sends null, which the backend treats as "unchanged"). */
const StorageForm: React.FC<{
  projectId: string;
  existing: ProjectStorageConfig | null;
  onSaved: (config: ProjectStorageConfig) => void;
  onCancel: () => void;
}> = ({ projectId, existing, onSaved, onCancel }) => {
  const [endpointUrl, setEndpointUrl] = useState(existing?.endpoint_url ?? '');
  const [bucket, setBucket] = useState(existing?.bucket ?? '');
  const [region, setRegion] = useState(existing?.region ?? 'us-east-1');
  const [accessKeyId, setAccessKeyId] = useState(existing?.access_key_id ?? '');
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasSecret = Boolean(existing?.has_secret);

  const handleSave = async () => {
    if (!endpointUrl.trim()) {
      setError('Endpoint URL is required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await setProjectStorage(projectId, {
        endpoint_url: endpointUrl.trim(),
        bucket: bucket.trim() || null,
        region: region.trim() || 'us-east-1',
        access_key_id: accessKeyId.trim() || null,
        // Empty string means "keep the stored secret" — send null so the
        // backend leaves the previously stored (encrypted) value in place.
        secret_access_key: secret.trim() || null,
      });
      notifications.show({
        color: 'teal',
        title: 'Storage configuration saved',
        message: `Endpoint ${saved.endpoint_url} is attached to this project.`,
        autoClose: 3000,
      });
      onSaved(saved);
    } catch (err) {
      setError((err as Error).message || 'Failed to save storage configuration.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap="sm" pt="sm">
      <TextInput
        label="Endpoint URL"
        placeholder="https://s3.example.org"
        required
        data-testid="storage-endpoint-input"
        value={endpointUrl}
        onChange={(e) => setEndpointUrl(e.currentTarget.value)}
        disabled={saving}
      />
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        <TextInput
          label="Bucket"
          placeholder="my-bucket"
          value={bucket}
          onChange={(e) => setBucket(e.currentTarget.value)}
          disabled={saving}
        />
        <TextInput
          label="Region"
          placeholder="us-east-1"
          value={region}
          onChange={(e) => setRegion(e.currentTarget.value)}
          disabled={saving}
        />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        <TextInput
          label="Access key ID"
          placeholder="AKIA…"
          value={accessKeyId}
          onChange={(e) => setAccessKeyId(e.currentTarget.value)}
          disabled={saving}
        />
        <PasswordInput
          label="Secret access key"
          placeholder={hasSecret ? 'unchanged' : 'Secret access key'}
          description={
            hasSecret
              ? 'Leave empty to keep the stored secret.'
              : 'Stored encrypted; never shown again.'
          }
          data-testid="storage-secret-input"
          value={secret}
          onChange={(e) => setSecret(e.currentTarget.value)}
          disabled={saving}
        />
      </SimpleGrid>
      {error && (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle" width={16} />}
        >
          {error}
        </Alert>
      )}
      <Group justify="flex-end" gap="xs">
        <Button variant="default" size="xs" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button
          size="xs"
          data-testid="storage-save-button"
          leftSection={<Icon icon="mdi:content-save-outline" width={14} />}
          onClick={handleSave}
          loading={saving}
        >
          Save
        </Button>
      </Group>
    </Stack>
  );
};

/** Project-level S3-compatible storage credentials. The secret is write-only
 *  end to end — the backend stores it encrypted and only ever reports
 *  `has_secret`, so this panel never displays or re-populates it. */
const StoragePanel: React.FC<StoragePanelProps> = ({ projectId, canManage }) => {
  const [config, setConfig] = useState<ProjectStorageConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [confirmRemoveOpened, setConfirmRemoveOpened] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    // getProjectStorage maps 404 → null ("not configured" is a normal state).
    getProjectStorage(projectId)
      .then((c) => {
        if (!cancelled) setConfig(c);
      })
      .catch((err: Error) => {
        // 401/403 (non-owner) or transport errors land here — render the
        // panel read-only with the message instead of toasting.
        if (!cancelled) setLoadError(err.message || 'Failed to load storage configuration.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const handleTest = async () => {
    setTesting(true);
    try {
      const result = await testProjectStorage(projectId);
      notifications.show({
        color: result.success ? 'teal' : 'orange',
        title: result.success ? 'Storage connection OK' : 'Storage connection failed',
        message: result.message,
        autoClose: result.success ? 4000 : 8000,
      });
    } catch (err) {
      notifications.show({
        color: 'orange',
        title: 'Storage connection test failed',
        message: (err as Error).message,
        autoClose: 8000,
      });
    } finally {
      setTesting(false);
    }
  };

  const handleRemove = async () => {
    setRemoving(true);
    try {
      await deleteProjectStorage(projectId);
      setConfig(null);
      setConfirmRemoveOpened(false);
      notifications.show({
        color: 'teal',
        title: 'Storage configuration removed',
        message: 'The stored credentials were deleted.',
        autoClose: 3000,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Failed to remove storage configuration',
        message: (err as Error).message,
      });
    } finally {
      setRemoving(false);
    }
  };

  return (
    <Paper withBorder radius="md" p="sm" data-testid="storage-panel">
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <Icon
            icon="mdi:cloud-key-outline"
            width={20}
            color="var(--mantine-color-teal-6)"
          />
          <Title order={4}>Storage</Title>
          {config && (
            <Badge
              variant="light"
              size="sm"
              color={config.has_secret ? 'teal' : 'gray'}
              leftSection={
                <Icon
                  icon={config.has_secret ? 'mdi:key-chain' : 'mdi:key-remove'}
                  width={12}
                />
              }
            >
              {config.has_secret ? 'Secret set' : 'No secret'}
            </Badge>
          )}
        </Group>
        {!loading && !editing && canManage && (
          <Group gap="xs" wrap="nowrap">
            {config && (
              <>
                <Button
                  size="xs"
                  variant="light"
                  data-testid="storage-test-button"
                  leftSection={<Icon icon="mdi:connection" width={14} />}
                  onClick={handleTest}
                  loading={testing}
                >
                  Test connection
                </Button>
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<Icon icon="mdi:pencil" width={14} />}
                  onClick={() => setEditing(true)}
                >
                  Edit
                </Button>
                <Button
                  size="xs"
                  variant="light"
                  color="red"
                  leftSection={<Icon icon="mdi:delete-outline" width={14} />}
                  onClick={() => setConfirmRemoveOpened(true)}
                >
                  Remove
                </Button>
              </>
            )}
            {!config && !loadError && (
              <Button
                size="xs"
                leftSection={<Icon icon="mdi:plus" width={14} />}
                onClick={() => setEditing(true)}
              >
                Configure storage
              </Button>
            )}
          </Group>
        )}
      </Group>

      {loading ? (
        <Group gap="xs" pt="sm">
          <Loader size="xs" />
          <Text size="sm" c="dimmed">
            Loading storage configuration…
          </Text>
        </Group>
      ) : editing ? (
        <StorageForm
          projectId={projectId}
          existing={config}
          onSaved={(saved) => {
            setConfig(saved);
            setEditing(false);
          }}
          onCancel={() => setEditing(false)}
        />
      ) : loadError ? (
        canManage ? (
          <Alert
            mt="sm"
            color="red"
            variant="light"
            icon={<Icon icon="mdi:alert-circle" width={16} />}
          >
            {loadError}
          </Alert>
        ) : (
          <Text size="sm" c="dimmed" pt="xs">
            Storage settings are managed by the project owners.
          </Text>
        )
      ) : config ? (
        <Stack gap={4} pt="xs">
          <ConfigRow label="Endpoint" value={config.endpoint_url} />
          <ConfigRow label="Bucket" value={config.bucket} />
          <ConfigRow label="Region" value={config.region} />
          <ConfigRow label="Access key" value={config.access_key_id} />
          {config.updated_at && (
            <Text size="xs" c="dimmed">
              Updated {config.updated_at}
            </Text>
          )}
        </Stack>
      ) : (
        <Text size="sm" c="dimmed" pt="xs">
          Attach S3-compatible credentials so this project's remote data
          collections can read private buckets.
          {!canManage && ' Only project owners can configure storage.'}
        </Text>
      )}

      <Modal
        opened={confirmRemoveOpened}
        onClose={() => !removing && setConfirmRemoveOpened(false)}
        title="Remove storage configuration?"
        centered
        size="sm"
      >
        <Stack gap="md">
          <Text size="sm">
            This deletes the stored endpoint and credentials (including the
            encrypted secret). Remote data collections relying on them will no
            longer be able to read private buckets.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button
              variant="default"
              size="xs"
              onClick={() => setConfirmRemoveOpened(false)}
              disabled={removing}
            >
              Cancel
            </Button>
            <Button
              size="xs"
              color="red"
              leftSection={<Icon icon="mdi:delete-outline" width={14} />}
              onClick={handleRemove}
              loading={removing}
            >
              Remove
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
};

export default StoragePanel;
