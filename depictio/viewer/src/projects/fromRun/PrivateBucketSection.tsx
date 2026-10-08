/**
 * The "Private bucket" part of the run tab's Source step: the connection
 * details of the bucket an `s3://` run folder is in, when the server cannot
 * read it on its own.
 *
 * It opens by itself when reading the folder is refused, or on purpose with
 * the "This bucket needs credentials" switch. The access key and its secret
 * are required: a bucket read without credentials is one the server's
 * administrator lists, never one named here. "Test connection" tries the
 * settings against the bucket (nothing is stored) and fills the region in
 * from the answer. The settings stay in the run tab's state: they are sent
 * with every read of a folder in this bucket, and stored as the project's
 * storage settings only when the project is created.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  Box,
  Code,
  Group,
  Paper,
  PasswordInput,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { runStorageFromFields, testRunStorage } from 'depictio-react-core';
import type {
  ProjectStorageTestResult,
  RunStorageFieldErrors,
  RunStorageFields,
} from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../components/settings/SettingsSections';

type TestState =
  | { status: 'idle' }
  | { status: 'testing' }
  | { status: 'done'; result: ProjectStorageTestResult }
  | { status: 'error'; error: string };

interface PrivateBucketSectionProps {
  /** The run folder, an `s3://` location in `bucket`. */
  location: string;
  bucket: string;
  open: boolean;
  /** Reading the folder was refused: the bucket is not public. */
  refused: boolean;
  onOpenChange: (open: boolean) => void;
  fields: RunStorageFields;
  onFieldsChange: (fields: RunStorageFields) => void;
  fieldErrors: RunStorageFieldErrors;
  /** Fill the region in from a successful test. */
  onRegionDetected: (region: string) => void;
  /** A test reached the bucket: the folder can be read again with these
   *  settings. */
  onConnected: () => void;
  /** Why private buckets are unavailable here; null when they are. */
  disabledReason: string | null;
}

const TestResult: React.FC<{ test: TestState }> = ({ test }) => {
  if (test.status === 'idle' || test.status === 'testing') return null;
  const success = test.status === 'done' && test.result.success;
  const message = test.status === 'done' ? test.result.message : test.error;
  return (
    <Group
      gap="xs"
      wrap="nowrap"
      align="flex-start"
      data-testid="run-private-bucket-test-result"
      data-success={success ? 'true' : 'false'}
    >
      <ThemeIcon variant="light" size="sm" radius="xl" color={success ? 'teal' : 'red'}>
        <Icon icon={success ? 'mdi:check-circle-outline' : 'mdi:alert-circle-outline'} width={14} />
      </ThemeIcon>
      <Stack gap={0} style={{ minWidth: 0 }}>
        <Text size="sm" fw={600}>
          {success
            ? 'Connected'
            : test.status === 'error'
              ? 'The connection test did not run'
              : 'The connection failed'}
        </Text>
        <Text size="sm" c="dimmed" style={{ overflowWrap: 'anywhere' }}>
          {message}
        </Text>
        {success && test.status === 'done' && test.result.detected_region && (
          <Text size="xs" c="dimmed" data-testid="run-private-bucket-detected-region">
            Region found: {test.result.detected_region}.
          </Text>
        )}
      </Stack>
    </Group>
  );
};

export const PrivateBucketSection: React.FC<PrivateBucketSectionProps> = ({
  location,
  bucket,
  open,
  refused,
  onOpenChange,
  fields,
  onFieldsChange,
  fieldErrors,
  onRegionDetected,
  onConnected,
  disabledReason,
}) => {
  const [test, setTest] = useState<TestState>({ status: 'idle' });
  /** A missing key or secret is marked on its field only after a first
   *  test: on an untouched form, or while the reader is between the two
   *  fields, it would nag. Until then the reason under the button says what
   *  is missing. */
  const [showKeyErrors, setShowKeyErrors] = useState(false);
  /** Bumped by every edit and folder change: a test answering after it no
   *  longer describes the settings shown. */
  const testRun = useRef(0);

  useEffect(() => {
    testRun.current += 1;
    setTest({ status: 'idle' });
  }, [location]);

  const disabled = Boolean(disabledReason);
  const testing = test.status === 'testing';

  const change = (name: keyof RunStorageFields, value: string) => {
    testRun.current += 1;
    setTest({ status: 'idle' });
    onFieldsChange({ ...fields, [name]: value });
  };

  const errorFor = (name: keyof RunStorageFields): string | undefined => {
    const error = fieldErrors[name];
    if (!error) return undefined;
    const keyField = name === 'accessKeyId' || name === 'secretAccessKey';
    return keyField && !showKeyErrors ? undefined : error;
  };

  /** What the settings lack, the access key and its secret included. */
  const firstError = Object.values(fieldErrors)[0] ?? null;
  const testReason = disabledReason ?? firstError;

  const handleTest = async () => {
    setShowKeyErrors(true);
    const storage = runStorageFromFields(fields);
    if (disabled || !storage || firstError) return;
    testRun.current += 1;
    const run = testRun.current;
    setTest({ status: 'testing' });
    try {
      const result = await testRunStorage(location, storage);
      if (run !== testRun.current) return;
      setTest({ status: 'done', result });
      if (result.success) {
        if (result.detected_region) onRegionDetected(result.detected_region);
        onConnected();
      }
    } catch (err) {
      if (run !== testRun.current) return;
      setTest({ status: 'error', error: (err as Error).message || 'The connection test did not run.' });
    }
  };

  return (
    <Stack gap="xs" data-testid="run-private-bucket">
      <Switch
        size="sm"
        label="This bucket needs credentials"
        checked={open}
        disabled={disabled}
        onChange={(event) => onOpenChange(event.currentTarget.checked)}
        data-testid="run-private-bucket-toggle"
      />
      {disabled && !open && <DisabledReason reason={disabledReason} />}

      {open && (
        <Paper withBorder radius="md" p="md" data-testid="run-private-bucket-section">
          <Stack gap="sm">
            <Group gap="sm" wrap="nowrap" align="flex-start">
              <ThemeIcon variant="light" color="gray" size="lg" radius="md">
                <Icon icon="mdi:cloud-lock-outline" width={20} />
              </ThemeIcon>
              <Stack gap={2} style={{ minWidth: 0 }}>
                <Group gap="xs" wrap="wrap">
                  <Text fw={600}>Private bucket</Text>
                  <Code data-testid="run-private-bucket-name">{bucket}</Code>
                </Group>
                <Text size="sm" c="dimmed" lh={1.4} data-testid="run-private-bucket-explanation">
                  {refused
                    ? 'This bucket is not public, so give its access key and secret.'
                    : 'Give the access key and secret of this bucket if it is not public.'}{' '}
                  These details become this project&apos;s storage settings, which you can change
                  later in Project settings, Storage.
                </Text>
              </Stack>
            </Group>

            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm" verticalSpacing="sm">
              <TextInput
                label="Endpoint"
                description="The address of the storage service, such as https://s3.example.org."
                placeholder="Leave empty for Amazon S3"
                value={fields.endpointUrl}
                onChange={(e) => change('endpointUrl', e.currentTarget.value)}
                error={errorFor('endpointUrl')}
                disabled={disabled}
                spellCheck={false}
                autoComplete="off"
                data-testid="run-private-bucket-endpoint"
              />
              <TextInput
                label="Region"
                description="Optional: the connection test fills it in."
                placeholder="us-east-1"
                value={fields.region}
                onChange={(e) => change('region', e.currentTarget.value)}
                error={errorFor('region')}
                disabled={disabled}
                spellCheck={false}
                autoComplete="off"
                data-testid="run-private-bucket-region"
              />
              <TextInput
                label="Access key"
                withAsterisk
                placeholder="AKIA..."
                value={fields.accessKeyId}
                onChange={(e) => change('accessKeyId', e.currentTarget.value)}
                error={errorFor('accessKeyId')}
                disabled={disabled}
                spellCheck={false}
                autoComplete="off"
                data-testid="run-private-bucket-access-key"
              />
              <PasswordInput
                label="Secret"
                withAsterisk
                placeholder="Secret access key"
                value={fields.secretAccessKey}
                onChange={(e) => change('secretAccessKey', e.currentTarget.value)}
                error={errorFor('secretAccessKey')}
                disabled={disabled}
                autoComplete="new-password"
                data-testid="run-private-bucket-secret"
              />
            </SimpleGrid>

            <Stack gap={6}>
              <Group gap="sm" wrap="wrap">
                <GatedButton
                  size="xs"
                  variant="light"
                  leftSection={<Icon icon="mdi:connection" width={14} />}
                  onClick={handleTest}
                  loading={testing}
                  reason={testReason}
                  data-testid="run-private-bucket-test"
                >
                  Test connection
                </GatedButton>
              </Group>
              <DisabledReason reason={testReason} icon="mdi:information-outline" />
            </Stack>

            <Box aria-live="polite" role="status">
              <TestResult test={test} />
            </Box>
          </Stack>
        </Paper>
      )}
    </Stack>
  );
};
