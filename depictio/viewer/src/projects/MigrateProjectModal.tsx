import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Text,
  Textarea,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { getPush, pushPreflight, startPush } from 'depictio-react-core';
import type { MigrationPush, MigrationTarget, PushPreflightResult } from 'depictio-react-core';

import { usePushTargets } from './usePushTargets';

const POLL_MS = 2000;

function formatBytes(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Group justify="space-between" wrap="nowrap" align="baseline" gap="md">
    <Text size="sm" c="dimmed">
      {label}
    </Text>
    <Text size="sm" ta="right" component="div">
      {children}
    </Text>
  </Group>
);

const REMOTE_COLOR: Record<string, string> = {
  pending: 'yellow',
  importing: 'blue',
  imported: 'green',
  rejected: 'red',
  failed: 'red',
  superseded: 'gray',
};

const REMOTE_TEXT: Record<string, string> = {
  pending: 'Waiting for an administrator on the target to review it.',
  importing: 'Being imported on the target.',
  imported: 'Imported on the target.',
  rejected: 'Rejected by an administrator on the target.',
  failed: 'The import failed on the target.',
  superseded: 'Replaced by a newer push.',
};

export interface MigrateProjectModalProps {
  opened: boolean;
  onClose: () => void;
  projectId: string;
  projectName?: string;
}

/**
 * Push a project to another Depictio instance for review: pick a target, run
 * the pre-flight, submit. The push builds and uploads in the background; the
 * modal follows it until it is submitted, then shows what the target made of it.
 */
const MigrateProjectModal: React.FC<MigrateProjectModalProps> = ({
  opened,
  onClose,
  projectId,
  projectName,
}) => {
  const targets = usePushTargets(opened);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<PushPreflightResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [starting, setStarting] = useState(false);
  const [push, setPush] = useState<MigrationPush | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const pushId = useRef<string | null>(null);

  // A single target needs no choosing.
  useEffect(() => {
    if (opened && targetId === null && targets.length === 1) setTargetId(targets[0].id);
  }, [opened, targets, targetId]);

  // Fresh state each time the modal opens.
  useEffect(() => {
    if (opened) return;
    setPreflight(null);
    setError(null);
    setMessage('');
    setPush(null);
    pushId.current = null;
  }, [opened]);

  useEffect(() => {
    if (!opened || !targetId) {
      setPreflight(null);
      return undefined;
    }
    let live = true;
    setChecking(true);
    setError(null);
    setPreflight(null);
    pushPreflight(projectId, targetId)
      .then((r) => live && setPreflight(r))
      .catch((err) => live && setError(err instanceof Error ? err.message : 'Pre-flight failed.'))
      .finally(() => live && setChecking(false));
    return () => {
      live = false;
    };
  }, [opened, targetId, projectId]);

  const refreshPush = useCallback(async () => {
    if (!pushId.current) return;
    try {
      setPush(await getPush(pushId.current));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to read the push status.');
    }
  }, []);

  const inFlight = push !== null && push.status !== 'submitted' && push.status !== 'failed';
  useEffect(() => {
    if (!inFlight) return undefined;
    const t = setInterval(() => void refreshPush(), POLL_MS);
    return () => clearInterval(t);
  }, [inFlight, refreshPush]);

  const handlePush = async () => {
    if (!targetId) return;
    setStarting(true);
    setError(null);
    try {
      const res = await startPush(projectId, targetId, message.trim() || undefined);
      pushId.current = res.push_id;
      setPush({ id: res.push_id, project_id: projectId, status: res.status });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the push.');
    } finally {
      setStarting(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await refreshPush();
    setRefreshing(false);
  };

  const pre = preflight?.preflight;
  const blockingErrors = preflight?.errors ?? [];
  const foreign = pre?.conflict === 'foreign';
  const canPush = !!preflight && preflight.can_push && !foreign && blockingErrors.length === 0;
  const targetName =
    preflight?.target.name ?? targets.find((t: MigrationTarget) => t.id === targetId)?.name ?? '';

  const renderProgress = (p: MigrationPush) => {
    if (p.status === 'failed') {
      return (
        <Alert color="red" variant="light" title="Push failed" data-testid="push-status">
          {p.error ?? 'The push failed.'}
        </Alert>
      );
    }
    if (p.status !== 'submitted') {
      return (
        <Group gap="xs" data-testid="push-status" data-status={p.status}>
          <Loader size="xs" />
          <Text size="sm">
            {p.status === 'uploading' ? 'Uploading to' : 'Building the bundle for'} {targetName}…
          </Text>
        </Group>
      );
    }
    const remote = p.remote_status ?? 'pending';
    return (
      <Stack gap="xs" data-testid="push-status" data-status="submitted" data-remote-status={remote}>
        <Alert color="green" variant="light" icon={<Icon icon="mdi:check-circle" />}>
          Submitted to {targetName}. An administrator there reviews it before it is imported.
        </Alert>
        <Group gap="xs">
          <Text size="sm">Status on the target:</Text>
          <Badge variant="light" color={REMOTE_COLOR[remote] ?? 'gray'}>
            {remote}
          </Badge>
          <Button
            size="compact-xs"
            variant="subtle"
            loading={refreshing}
            onClick={() => void handleRefresh()}
            leftSection={<Icon icon="mdi:refresh" width={14} />}
            data-testid="push-refresh"
          >
            Refresh
          </Button>
        </Group>
        {REMOTE_TEXT[remote] && (
          <Text size="xs" c="dimmed">
            {REMOTE_TEXT[remote]}
          </Text>
        )}
      </Stack>
    );
  };

  const renderReport = (r: PushPreflightResult) => (
    <Stack gap="xs" data-testid="migrate-preflight">
      <Row label="Transfer mode">
        {r.transfer_mode === 'server_side_copy' ? 'Server-side copy' : 'Inline upload'}
      </Row>
      <Row label="Size">{formatBytes(r.total_bytes)}</Row>
      <Row label="Objects">{r.object_count}</Row>
      {pre?.conflict === 're_push' && (
        <Alert color="blue" variant="light" data-testid="migrate-re-push">
          This will become a new version on the target.
        </Alert>
      )}
      {foreign && (
        <Alert color="red" variant="light" data-testid="migrate-foreign">
          A different project with this id already exists on the target. It cannot be
          overwritten from here.
        </Alert>
      )}
      {pre?.existing_locked && (
        <Alert color="gray" variant="light">
          The existing copy on the target is published read-only; it stays so until an
          administrator there decides otherwise.
        </Alert>
      )}
      {pre?.requester_has_account === false && (
        <Alert color="yellow" variant="light" data-testid="migrate-no-account">
          You have no account on the target yet: an admin will own it until you sign in there.
        </Alert>
      )}
      {blockingErrors.length > 0 && (
        <Alert color="red" variant="light" title="Cannot push" data-testid="migrate-errors">
          {blockingErrors.map((e, i) => (
            <Text key={i} size="sm">
              {e}
            </Text>
          ))}
        </Alert>
      )}
      {(preflight?.warnings ?? []).length > 0 && (
        <Alert color="yellow" variant="light" title="Warnings" data-testid="migrate-warnings">
          {(preflight?.warnings ?? []).map((w, i) => (
            <Text key={i} size="sm">
              {w}
            </Text>
          ))}
        </Alert>
      )}
    </Stack>
  );

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Push ${projectName ? `"${projectName}" ` : 'project '}to another instance`}
      centered
      size="md"
      data-testid="migrate-project-modal"
    >
      <Stack gap="md">
        {!push && (
          <>
            <Select
              label="Target instance"
              placeholder="Choose a target"
              data={targets.map((t) => ({ value: t.id, label: `${t.name} (${t.url})` }))}
              value={targetId}
              onChange={setTargetId}
              allowDeselect={false}
              data-testid="migrate-target-select"
            />
            {checking && (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="sm" c="dimmed">
                  Checking the target…
                </Text>
              </Group>
            )}
            {preflight && renderReport(preflight)}
            {preflight && (
              <Textarea
                label="Message to the reviewer"
                description="Optional."
                autosize
                minRows={2}
                maxLength={1000}
                value={message}
                onChange={(e) => setMessage(e.currentTarget.value)}
                data-testid="migrate-message"
              />
            )}
          </>
        )}
        {push && renderProgress(push)}
        {error && (
          <Alert color="red" variant="light" data-testid="migrate-error">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="subtle" color="gray" onClick={onClose}>
            {push ? 'Close' : 'Cancel'}
          </Button>
          {!push && (
            <Button
              loading={starting}
              disabled={!canPush || checking}
              onClick={() => void handlePush()}
              leftSection={<Icon icon="mdi:transfer-up" width={16} />}
              data-testid="migrate-push-button"
            >
              Push
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
};

export default MigrateProjectModal;
