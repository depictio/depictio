import React, { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { restoreBackup, validateBackup } from 'depictio-react-core';
import type { BackupRestoreResult, BackupValidationResult } from 'depictio-react-core';

/**
 * Restore flow modal: validate → typed confirm → restore → result.
 *
 * Restore is a per-collection wipe-and-replace, so the confirm step requires
 * typing RESTORE (mirrors the Maintenance tab's DELETE confirmation). The
 * server refuses backups that fail Pydantic validation; invalid backups never
 * even render the confirm UI here — the CLI's --skip-validation escape hatch
 * is deliberately not exposed in the UI.
 */
const CONFIRM_PHRASE = 'RESTORE';

export interface RestoreTarget {
  backupId: string;
  filename: string;
  /** Legacy backups without a .sha256 sidecar restore with allow_unverified. */
  hasChecksum: boolean;
  /** Present when the upload endpoint already validated the file. */
  initialValidation?: BackupValidationResult | null;
}

interface RestoreBackupModalProps {
  opened: boolean;
  target: RestoreTarget | null;
  onClose: () => void;
  /** Called after a successful restore so the parent can refresh. */
  onRestored: () => void;
}

type Step = 'validating' | 'results' | 'restoring' | 'done' | 'error';

const RestoreBackupModal: React.FC<RestoreBackupModalProps> = ({
  opened,
  target,
  onClose,
  onRestored,
}) => {
  const [step, setStep] = useState<Step>('validating');
  const [validation, setValidation] = useState<BackupValidationResult | null>(null);
  const [restoreResult, setRestoreResult] = useState<BackupRestoreResult | null>(null);
  const [confirmText, setConfirmText] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!opened || !target) return;
    setConfirmText('');
    setErrorMessage(null);
    setRestoreResult(null);
    if (target.initialValidation) {
      setValidation(target.initialValidation);
      setStep('results');
      return;
    }
    setValidation(null);
    setStep('validating');
    let cancelled = false;
    validateBackup(target.backupId)
      .then((result) => {
        if (cancelled) return;
        setValidation(result);
        setStep('results');
      })
      .catch((err) => {
        if (cancelled) return;
        setErrorMessage(err instanceof Error ? err.message : 'Validation failed');
        setStep('error');
      });
    return () => {
      cancelled = true;
    };
  }, [opened, target]);

  const busy = step === 'restoring';

  const handleRestore = async () => {
    if (!target) return;
    setStep('restoring');
    setErrorMessage(null);
    try {
      const result = await restoreBackup(target.backupId, {
        dryRun: false,
        allowUnverified: !target.hasChecksum,
      });
      setRestoreResult(result);
      if (result.success) {
        setStep('done');
        onRestored();
      } else {
        setErrorMessage(result.message);
        setStep('error');
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Restore failed');
      setStep('error');
    }
  };

  const renderValidationSummary = (v: BackupValidationResult) => {
    const collections = Object.entries(v.collections_validated ?? {});
    return (
      <Stack gap="sm">
        <Group gap="xs">
          {v.valid ? (
            <Badge color="green" variant="light" data-testid="backup-validation-valid">
              Validation passed
            </Badge>
          ) : (
            <Badge color="red" variant="light" data-testid="backup-validation-invalid">
              Validation failed
            </Badge>
          )}
          <Text size="sm" c="dimmed">
            {v.valid_documents}/{v.total_documents} documents valid
          </Text>
        </Group>

        {collections.length > 0 && (
          <Table
            withTableBorder
            withColumnBorders
            fz="xs"
            data-testid="backup-validation-table"
          >
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Collection</Table.Th>
                <Table.Th>Documents</Table.Th>
                <Table.Th>Valid</Table.Th>
                <Table.Th>Invalid</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {collections.map(([name, stats]) => (
                <Table.Tr key={name}>
                  <Table.Td>{name}</Table.Td>
                  <Table.Td>{stats.total}</Table.Td>
                  <Table.Td>{stats.valid}</Table.Td>
                  <Table.Td>
                    {stats.invalid > 0 ? (
                      <Text component="span" c="red" fw={600} size="xs">
                        {stats.invalid}
                      </Text>
                    ) : (
                      stats.invalid
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}

        {v.warnings?.length > 0 && (
          <Alert color="yellow" variant="light" icon={<Icon icon="mdi:alert" />}>
            <Stack gap={2}>
              {v.warnings.map((w, i) => (
                <Text key={i} size="xs">
                  {w}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}

        {v.errors?.length > 0 && (
          <Alert
            color="red"
            variant="light"
            icon={<Icon icon="mdi:alert-circle" />}
            title="Validation errors"
            data-testid="backup-validation-errors"
          >
            <ScrollArea.Autosize mah={180}>
              <Stack gap={2}>
                {v.errors.map((e, i) => (
                  <Text key={i} size="xs" ff="monospace">
                    {e}
                  </Text>
                ))}
              </Stack>
            </ScrollArea.Autosize>
          </Alert>
        )}
      </Stack>
    );
  };

  const renderBody = () => {
    if (!target) return null;

    if (step === 'validating') {
      return (
        <Center mih={140}>
          <Group gap="sm" data-testid="backup-validation-status">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              Validating backup {target.backupId}…
            </Text>
          </Group>
        </Center>
      );
    }

    if (step === 'done' && restoreResult) {
      const count = Object.keys(restoreResult.restored_collections ?? {}).length;
      return (
        <Stack gap="sm">
          <Alert
            color="green"
            variant="light"
            icon={<Icon icon="mdi:check-circle" />}
            title="Restore completed"
            data-testid="backup-restore-success"
          >
            Restored {restoreResult.total_restored} documents across {count} collection
            {count === 1 ? '' : 's'}.
          </Alert>
          <Group justify="flex-end">
            <Button onClick={onClose}>Close</Button>
          </Group>
        </Stack>
      );
    }

    if (step === 'error') {
      return (
        <Stack gap="sm">
          <Alert
            color="red"
            variant="light"
            icon={<Icon icon="mdi:alert-circle" />}
            title="Restore not performed"
            data-testid="backup-restore-error"
          >
            {errorMessage ?? 'Unknown error'}
          </Alert>
          {restoreResult && restoreResult.errors?.length > 0 && (
            <ScrollArea.Autosize mah={140}>
              <Stack gap={2}>
                {restoreResult.errors.map((e, i) => (
                  <Text key={i} size="xs" ff="monospace" c="red">
                    {e}
                  </Text>
                ))}
              </Stack>
            </ScrollArea.Autosize>
          )}
          <Group justify="flex-end" gap="xs">
            {validation && (
              <Button variant="subtle" onClick={() => setStep('results')}>
                Back
              </Button>
            )}
            <Button onClick={onClose}>Close</Button>
          </Group>
        </Stack>
      );
    }

    // 'results' and 'restoring'
    return (
      <Stack gap="sm">
        {validation && renderValidationSummary(validation)}

        {!target.hasChecksum && (
          <Alert color="yellow" variant="light" icon={<Icon icon="mdi:shield-alert" />}>
            This backup has no integrity checksum; the restore will proceed unverified.
          </Alert>
        )}

        {validation?.valid ? (
          <>
            <Alert
              color="red"
              variant="light"
              icon={<Icon icon="mdi:alert" />}
              title="This cannot be undone."
            >
              Every listed collection will be wiped and replaced by the backup contents —
              including collections the backup stores as empty. Active sessions survive
              (tokens are never part of backups).
            </Alert>

            <TextInput
              label={`Type ${CONFIRM_PHRASE} to confirm`}
              placeholder={CONFIRM_PHRASE}
              value={confirmText}
              onChange={(e) => setConfirmText(e.currentTarget.value)}
              disabled={busy}
              autoFocus
              data-testid="backup-restore-confirm-input"
            />

            <Group justify="flex-end" gap="xs" mt="sm">
              <Button variant="subtle" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button
                color="red"
                leftSection={<Icon icon="mdi:backup-restore" width={14} />}
                onClick={handleRestore}
                loading={busy}
                disabled={confirmText.trim() !== CONFIRM_PHRASE || busy}
                data-testid="backup-restore-confirm-button"
              >
                Restore backup
              </Button>
            </Group>
          </>
        ) : (
          <>
            <Alert color="red" variant="light" icon={<Icon icon="mdi:cancel" />}>
              This backup cannot be restored while it fails validation. Fix the backup
              file and upload it again.
            </Alert>
            <Group justify="flex-end">
              <Button onClick={onClose}>Close</Button>
            </Group>
          </>
        )}
      </Stack>
    );
  };

  return (
    <Modal
      opened={opened}
      onClose={() => !busy && onClose()}
      title={target ? `Restore backup ${target.backupId}` : 'Restore backup'}
      size="lg"
      centered
      closeOnClickOutside={false}
      data-testid="backup-restore-modal"
    >
      {renderBody()}
    </Modal>
  );
};

export default RestoreBackupModal;
