import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  Collapse,
  CopyButton,
  Divider,
  Group,
  Loader,
  Paper,
  PasswordInput,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  deleteProjectStorage,
  getProjectStorage,
  setProjectStorage,
  testProjectStorage,
  Z_LAYERS,
} from 'depictio-react-core';
import type { ProjectStorageConfig, ProjectStorageTestResult } from 'depictio-react-core';

import {
  DisabledReason,
  Field,
  GatedButton,
} from '../../components/settings/SettingsSections';
import { formatDateTime } from '../../lib/datetime';

interface StoragePanelProps {
  projectId: string;
  /** Only project owners (or admins) may view/edit storage credentials,
   *  stricter than the page-level `canMutate`, which includes editors. */
  canManage: boolean;
}

const OWNER_ONLY = 'Only project owners can change the storage settings.';

/** A value the reader may want to paste elsewhere (an endpoint, a key id),
 *  laid out like the dashboard identifiers. */
const CopyableValue: React.FC<{ label: string; value: string | null; empty: string }> = ({
  label,
  value,
  empty,
}) => (
  <Group gap="xs" wrap="nowrap" align="center">
    <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      {value ? (
        <Code style={{ overflowWrap: 'anywhere' }}>{value}</Code>
      ) : (
        <Text size="sm" c="dimmed">
          {empty}
        </Text>
      )}
    </Stack>
    {value && (
      <CopyButton value={value} timeout={1500}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? 'Copied' : 'Copy'} withArrow zIndex={Z_LAYERS.tooltip}>
            <ActionIcon
              variant="subtle"
              color={copied ? 'teal' : 'gray'}
              size="sm"
              onClick={copy}
              aria-label={`Copy ${label.toLowerCase()}`}
            >
              <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
            </ActionIcon>
          </Tooltip>
        )}
      </CopyButton>
    )}
  </Group>
);

/** Endpoint and access key, folded by default: connection detail for someone
 *  checking the setup, not something to read on every open. */
const ConnectionDetails: React.FC<{ config: ProjectStorageConfig }> = ({ config }) => {
  const [open, setOpen] = useState(false);
  return (
    <Stack gap="xs" data-testid="storage-details">
      <UnstyledButton
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid="storage-details-toggle"
      >
        <Divider
          labelPosition="left"
          my={4}
          label={
            <Group gap={4} wrap="nowrap">
              <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />
              <span>Connection details</span>
            </Group>
          }
        />
      </UnstyledButton>
      <Collapse in={open}>
        <Stack gap="xs">
          <CopyableValue label="Endpoint" value={config.endpoint_url} empty="Not set" />
          <CopyableValue
            label="Access key ID"
            value={config.access_key_id}
            empty="None: the bucket is read without signing in"
          />
        </Stack>
      </Collapse>
    </Stack>
  );
};

/** Outcome of the last connection test, read out when it lands. */
const TestResult: React.FC<{
  result: ProjectStorageTestResult | null;
  error: string | null;
}> = ({ result, error }) => {
  if (error) {
    return (
      <Alert
        color="red"
        variant="light"
        icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
        title="Could not run the connection test"
        data-testid="storage-test-result"
        data-success="false"
      >
        {error}
      </Alert>
    );
  }
  if (!result) return null;
  return (
    <Alert
      color={result.success ? 'teal' : 'orange'}
      variant="light"
      icon={
        <Icon
          icon={result.success ? 'mdi:check-circle-outline' : 'mdi:alert-circle-outline'}
          width={18}
        />
      }
      title={result.success ? 'Storage connection OK' : 'Storage connection failed'}
      data-testid="storage-test-result"
      data-success={result.success ? 'true' : 'false'}
    >
      <Stack gap={4}>
        <Text size="sm">{result.message}</Text>
        {result.detected_region && (
          <Text size="sm" data-testid="storage-detected-region">
            Region detected: {result.detected_region}. It is saved on this project.
          </Text>
        )}
      </Stack>
    </Alert>
  );
};

/** Edit/create form for the storage config. The secret field is write-only:
 *  when a secret is already stored, leaving it empty keeps it (the PUT body
 *  sends null, which the backend treats as "unchanged"), unless the access
 *  key ID, the endpoint or the bucket changes: the stored secret belongs to
 *  the key and place it was saved with, so the backend refuses to reuse it. */
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
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasSecret = Boolean(existing?.has_secret);
  const typedKey = accessKeyId.trim();
  const keyChanged = typedKey !== (existing?.access_key_id ?? '');
  const placeChanged =
    endpointUrl.trim() !== (existing?.endpoint_url ?? '') ||
    bucket.trim() !== (existing?.bucket ?? '');
  /** A stored secret is kept only for the key, endpoint and bucket it was
   *  saved with. */
  const keepsStoredSecret = hasSecret && Boolean(typedKey) && !keyChanged && !placeChanged;

  const clearFieldError = (name: string) =>
    setFieldErrors((prev) => {
      if (!(name in prev)) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    const endpoint = endpointUrl.trim();
    if (!endpoint) errors.endpoint = 'Enter the address of the storage service.';
    else if (!/^https?:\/\//i.test(endpoint)) {
      errors.endpoint = 'Enter the full address, starting with https://.';
    }
    if (!bucket.trim()) errors.bucket = 'Enter the bucket name.';
    const typedSecret = secret.trim();
    if (typedKey && !typedSecret && !keepsStoredSecret) {
      errors.secret = !hasSecret
        ? 'Enter the secret that goes with this access key ID.'
        : keyChanged
          ? 'Enter the secret for this new access key ID: the stored one belongs to the old key.'
          : 'Enter the secret again: a stored secret is kept only for the endpoint and bucket it was saved with.';
    }
    if (typedSecret && !typedKey) errors.accessKey = 'Enter the access key ID for this secret.';
    return errors;
  };

  const handleSave = async () => {
    const errors = validate();
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await setProjectStorage(projectId, {
        endpoint_url: endpointUrl.trim(),
        bucket: bucket.trim(),
        region: region.trim() || 'us-east-1',
        access_key_id: typedKey || null,
        // Empty means "keep the stored secret": send null so the backend
        // leaves the previously stored (encrypted) value in place. Validation
        // above only lets that through for an unchanged key, endpoint and bucket.
        secret_access_key: secret.trim() || null,
      });
      notifications.show({
        color: 'teal',
        title: 'Storage settings saved',
        message: saved.bucket
          ? `Bucket ${saved.bucket} is attached to this project.`
          : 'The endpoint is attached to this project.',
        autoClose: 3000,
      });
      onSaved(saved);
    } catch (err) {
      setError((err as Error).message || 'The storage settings could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap="md" data-testid="storage-form">
      <TextInput
        label="Endpoint URL"
        description="The address of the S3-compatible storage service, such as https://s3.eu-west-1.amazonaws.com."
        placeholder="https://s3.example.org"
        required
        data-testid="storage-endpoint-input"
        value={endpointUrl}
        onChange={(e) => {
          setEndpointUrl(e.currentTarget.value);
          clearFieldError('endpoint');
        }}
        error={fieldErrors.endpoint}
        disabled={saving}
      />
      <TextInput
        label="Bucket"
        description="The bucket this project's data lives in. The connection test checks that it can be read."
        placeholder="my-bucket"
        required
        data-testid="storage-bucket-input"
        value={bucket}
        onChange={(e) => {
          setBucket(e.currentTarget.value);
          clearFieldError('bucket');
        }}
        error={fieldErrors.bucket}
        disabled={saving}
      />
      <TextInput
        label="Region"
        description="Keep us-east-1 if you are not sure: the connection test finds the bucket's region and saves it."
        placeholder="us-east-1"
        data-testid="storage-region-input"
        value={region}
        onChange={(e) => setRegion(e.currentTarget.value)}
        disabled={saving}
      />
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm" verticalSpacing="md">
        <TextInput
          label="Access key ID"
          description="Leave both keys empty for a bucket anyone may read."
          placeholder="AKIA..."
          data-testid="storage-access-key-input"
          // Keep password managers from filling in the reader's own login.
          autoComplete="off"
          data-1p-ignore
          data-lpignore="true"
          value={accessKeyId}
          onChange={(e) => {
            setAccessKeyId(e.currentTarget.value);
            clearFieldError('accessKey');
            clearFieldError('secret');
          }}
          error={fieldErrors.accessKey}
          disabled={saving}
        />
        <PasswordInput
          label="Secret access key"
          description={
            keepsStoredSecret
              ? 'Leave empty to keep the stored secret.'
              : hasSecret && typedKey && keyChanged
                ? 'A new access key ID needs its own secret: the stored one is replaced.'
                : hasSecret && typedKey
                  ? 'A new endpoint or bucket needs the secret again: the stored one is replaced.'
                : hasSecret
                  ? 'Without an access key ID the stored secret is removed.'
                  : 'Stored encrypted and never shown again.'
          }
          placeholder={keepsStoredSecret ? 'unchanged' : 'Secret access key'}
          data-testid="storage-secret-input"
          // Neither fill in the reader's own password nor offer to save the
          // bucket secret as one.
          autoComplete="new-password"
          data-1p-ignore
          data-lpignore="true"
          value={secret}
          onChange={(e) => {
            setSecret(e.currentTarget.value);
            clearFieldError('secret');
            clearFieldError('accessKey');
          }}
          error={fieldErrors.secret}
          disabled={saving}
        />
      </SimpleGrid>
      {error && (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
          title="The storage settings were not saved"
          data-testid="storage-save-error"
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

/**
 * Project-level S3-compatible storage credentials, as the Storage section of
 * the project settings. The secret is write-only end to end: the backend
 * stores it encrypted and only ever reports `has_secret`, so this panel never
 * displays or re-populates it.
 */
const StoragePanel: React.FC<StoragePanelProps> = ({ projectId, canManage }) => {
  const [config, setConfig] = useState<ProjectStorageConfig | null>(null);
  // Nothing to load for non-owners (see the effect below), so don't flash the
  // loading row at them.
  const [loading, setLoading] = useState(canManage);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProjectStorageTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    // GET /projects/{id}/storage is owner-gated (403 otherwise). Skip the
    // request we know will be refused and show the owner-only state;
    // `canManage` flips once the project and user have loaded, which re-runs
    // this effect for owners.
    if (!canManage) {
      setConfig(null);
      setLoadError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    // getProjectStorage maps 404 to null ("not configured" is a normal state).
    getProjectStorage(projectId)
      .then((c) => {
        if (!cancelled) setConfig(c);
      })
      .catch((err: Error) => {
        if (!cancelled) setLoadError(err.message || 'The storage settings could not be loaded.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, canManage]);

  const clearTest = () => {
    setTestResult(null);
    setTestError(null);
  };

  const handleTest = async () => {
    setTesting(true);
    setJustSaved(false);
    clearTest();
    try {
      const result = await testProjectStorage(projectId);
      setTestResult(result);
      const detected = result.detected_region;
      if (detected) {
        // The server saved the detected region already: show it now, then
        // re-read the config so its other fields (updated time) follow.
        setConfig((c) => (c ? { ...c, region: detected } : c));
        getProjectStorage(projectId)
          .then((c) => {
            if (c) setConfig(c);
          })
          .catch(() => {
            // The region is already shown; the next open re-reads the rest.
          });
      }
    } catch (err) {
      setTestError((err as Error).message || 'The connection test did not run.');
    } finally {
      setTesting(false);
    }
  };

  const handleRemove = async () => {
    setRemoving(true);
    try {
      await deleteProjectStorage(projectId);
      setConfig(null);
      setConfirmingRemove(false);
      setJustSaved(false);
      clearTest();
      notifications.show({
        color: 'teal',
        title: 'Storage settings removed',
        message: 'The endpoint and the keys were deleted.',
        autoClose: 3000,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'The storage settings were not removed',
        message: (err as Error).message,
      });
    } finally {
      setRemoving(false);
    }
  };

  const ownerReason = canManage ? null : OWNER_ONLY;

  let body: React.ReactNode;
  if (loading) {
    body = (
      <Group gap="xs" aria-live="polite">
        <Loader size="xs" />
        <Text size="sm" c="dimmed">
          Loading the storage settings...
        </Text>
      </Group>
    );
  } else if (editing) {
    body = (
      <StorageForm
        projectId={projectId}
        existing={config}
        onSaved={(saved) => {
          setConfig(saved);
          setEditing(false);
          setJustSaved(true);
          clearTest();
        }}
        onCancel={() => setEditing(false)}
      />
    );
  } else if (loadError) {
    body = (
      <Alert
        color="red"
        variant="light"
        icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
        title="Could not load the storage settings"
      >
        {loadError}
      </Alert>
    );
  } else if (config) {
    body = (
      <Stack gap="md">
        <Group gap="xs">
          <Badge
            variant="light"
            size="md"
            color={config.has_secret ? 'teal' : 'gray'}
            leftSection={
              <Icon icon={config.has_secret ? 'mdi:key-chain' : 'mdi:key-remove'} width={14} />
            }
          >
            {config.has_secret ? 'Secret set' : 'No secret'}
          </Badge>
          {config.updated_at && (
            <Text size="xs" c="dimmed">
              Updated {formatDateTime(config.updated_at)}
            </Text>
          )}
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
          <Field label="Bucket">
            <Text size="sm" ff="monospace" data-testid="storage-bucket-value">
              {config.bucket || 'Not set: edit the settings to add it'}
            </Text>
          </Field>
          <Field label="Region">
            <Text size="sm" ff="monospace" data-testid="storage-region-value">
              {config.region}
            </Text>
          </Field>
        </SimpleGrid>
        <ConnectionDetails config={config} />
        <Stack gap={6}>
          <Group gap="xs">
            <GatedButton
              size="xs"
              variant="light"
              data-testid="storage-test-button"
              leftSection={<Icon icon="mdi:connection" width={14} />}
              onClick={handleTest}
              loading={testing}
              reason={ownerReason}
            >
              Test connection
            </GatedButton>
            <GatedButton
              size="xs"
              variant="light"
              data-testid="storage-edit-button"
              leftSection={<Icon icon="mdi:pencil" width={14} />}
              onClick={() => {
                setEditing(true);
                setConfirmingRemove(false);
                setJustSaved(false);
              }}
              reason={ownerReason}
            >
              Edit
            </GatedButton>
            <GatedButton
              size="xs"
              variant="light"
              color="red"
              data-testid="storage-remove-button"
              leftSection={<Icon icon="mdi:delete-outline" width={14} />}
              onClick={() => setConfirmingRemove(true)}
              reason={ownerReason}
            >
              Remove
            </GatedButton>
          </Group>
          <DisabledReason reason={ownerReason} />
          {justSaved && (
            <Text size="xs" c="dimmed" data-testid="storage-saved-hint">
              Saved. Test the connection to check the bucket and detect its region.
            </Text>
          )}
        </Stack>
        {confirmingRemove && (
          <Paper withBorder radius="md" p="sm" data-testid="storage-remove-confirm">
            <Stack gap="xs">
              <Text size="sm" fw={500}>
                Remove the storage settings?
              </Text>
              <Text size="xs" c="dimmed">
                This deletes the endpoint and the keys, the encrypted secret included. Data
                collections that read a private bucket with them stop working until new
                settings are saved.
              </Text>
              <Group justify="flex-end" gap="xs">
                <Button
                  variant="default"
                  size="xs"
                  onClick={() => setConfirmingRemove(false)}
                  disabled={removing}
                >
                  Cancel
                </Button>
                <Button
                  size="xs"
                  color="red"
                  data-testid="storage-remove-confirm-button"
                  leftSection={<Icon icon="mdi:delete-outline" width={14} />}
                  onClick={handleRemove}
                  loading={removing}
                >
                  Remove settings
                </Button>
              </Group>
            </Stack>
          </Paper>
        )}
        <div aria-live="polite">
          <TestResult result={testResult} error={testError} />
        </div>
      </Stack>
    );
  } else {
    body = (
      <Stack gap="md">
        <Group gap="sm" wrap="nowrap" align="flex-start">
          <ThemeIcon variant="light" color="gray" size="lg" radius="md">
            <Icon icon="mdi:cloud-off-outline" width={20} />
          </ThemeIcon>
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text size="sm" fw={500}>
              {canManage ? 'No storage configured' : 'Storage settings are for project owners'}
            </Text>
            <Text size="xs" c="dimmed" lh={1.35}>
              {canManage
                ? 'Without storage settings this project reads only public addresses and the buckets this server lists as public. Add an endpoint, a bucket and its keys to read a private bucket.'
                : 'The owners of this project can attach a private bucket here. Ask one of them if a data collection cannot reach its files.'}
            </Text>
          </Stack>
        </Group>
        <Stack gap={6}>
          <Group>
            <GatedButton
              size="xs"
              data-testid="storage-configure-button"
              leftSection={<Icon icon="mdi:plus" width={14} />}
              onClick={() => setEditing(true)}
              reason={ownerReason}
            >
              Configure storage
            </GatedButton>
          </Group>
          <DisabledReason reason={ownerReason} />
        </Stack>
      </Stack>
    );
  }

  return (
    <Stack gap="lg" data-testid="storage-panel">
      <Text size="sm" c="dimmed">
        Lets this project&apos;s data collections that read a URL, a manifest or a bucket
        prefix reach a private bucket on any S3-compatible service. The keys are used for
        this project only.
      </Text>
      {body}
    </Stack>
  );
};

export default StoragePanel;
