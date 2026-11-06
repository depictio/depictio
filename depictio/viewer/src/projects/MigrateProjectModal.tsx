import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  PasswordInput,
  SegmentedControl,
  Select,
  Stack,
  Stepper,
  Text,
  Textarea,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  Z_LAYERS,
  checkPush,
  getPush,
  getPushDestinations,
  startPush,
} from 'depictio-react-core';
import type {
  MigrationPush,
  MigrationTarget,
  PushDestination,
  PushDestinations,
  PushPreflightResult,
} from 'depictio-react-core';

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

/** One line of the pre-flight summary: an icon, what it means, a detail. */
const Fact: React.FC<{
  icon: string;
  color?: string;
  title: string;
  children?: React.ReactNode;
  testId?: string;
}> = ({ icon, color = 'gray', title, children, testId }) => (
  <Group gap="sm" wrap="nowrap" align="flex-start" data-testid={testId}>
    <ThemeIcon variant="light" color={color} size="lg" radius="md">
      <Icon icon={icon} width={20} height={20} />
    </ThemeIcon>
    <Stack gap={0} style={{ minWidth: 0 }}>
      <Text size="sm" fw={600}>
        {title}
      </Text>
      {children && (
        <Text size="sm" c="dimmed">
          {children}
        </Text>
      )}
    </Stack>
  </Group>
);

const REMOTE_COLOR: Record<string, string> = {
  pending: 'yellow',
  importing: 'blue',
  imported: 'green',
  rejected: 'red',
  failed: 'red',
  expired: 'gray',
  superseded: 'gray',
};

const REMOTE_TEXT: Record<string, string> = {
  pending: 'Waiting for an administrator on the target to review it.',
  importing: 'Being imported on the target.',
  imported: 'Imported on the target.',
  rejected: 'Rejected by an administrator on the target.',
  failed: 'The import failed on the target.',
  expired: 'The request expired before it was reviewed.',
  superseded: 'Replaced by a newer push.',
};

/** A 409 on start means this project already has a push under way. */
function pushErrorText(err: unknown, fallback: string): string {
  const status = (err as { status?: number } | null)?.status;
  if (status === 409) {
    return 'A push of this project is already in progress. Wait for it to finish, then try again.';
  }
  return err instanceof Error ? err.message : fallback;
}

export interface MigrateProjectModalProps {
  opened: boolean;
  onClose: () => void;
  projectId: string;
  projectName?: string;
}

/**
 * Publish a project to another Depictio instance: pick a registered target, or
 * enter a destination URL and the invite code its admin issued, run the
 * pre-flight, submit. The push builds and uploads in the background; the modal
 * follows it until it is submitted, then shows what the destination made of it.
 * The invite code lives in component state only; it is never persisted.
 */
const MigrateProjectModal: React.FC<MigrateProjectModalProps> = ({
  opened,
  onClose,
  projectId,
  projectName,
}) => {
  const targets = usePushTargets(opened);
  const [destinations, setDestinations] = useState<PushDestinations | null>(null);
  const [mode, setMode] = useState<'target' | 'url' | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [url, setUrl] = useState('');
  const [code, setCode] = useState('');
  const [preflight, setPreflight] = useState<PushPreflightResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [starting, setStarting] = useState(false);
  const [push, setPush] = useState<MigrationPush | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const pushId = useRef<string | null>(null);

  const adhocEnabled = destinations?.enabled === true;
  const hasTargets = targets.length > 0;

  useEffect(() => {
    if (!opened) return undefined;
    let live = true;
    getPushDestinations()
      .then((d) => live && setDestinations(d))
      .catch(() => live && setDestinations({ enabled: false, domains: [], recent: [] }));
    return () => {
      live = false;
    };
  }, [opened]);

  // Open on the mode that can work: registered targets first, else URL + code.
  useEffect(() => {
    if (!opened || mode !== null || destinations === null) return;
    if (hasTargets) setMode('target');
    else if (adhocEnabled) setMode('url');
  }, [opened, mode, destinations, hasTargets, adhocEnabled]);

  // A single target needs no choosing.
  useEffect(() => {
    if (opened && targetId === null && targets.length === 1) setTargetId(targets[0].id);
  }, [opened, targets, targetId]);

  // Fresh state each time the modal opens (and the code never lingers).
  useEffect(() => {
    if (opened) return;
    setPreflight(null);
    setError(null);
    setMessage('');
    setPush(null);
    setMode(null);
    setUrl('');
    setCode('');
    pushId.current = null;
  }, [opened]);

  const destination: PushDestination | null =
    mode === 'target' && targetId
      ? { target_id: targetId }
      : mode === 'url' && url.trim() && code.trim()
        ? { destination_url: url.trim(), invite_code: code.trim() }
        : null;

  const runCheck = useCallback(
    async (dest: PushDestination, isLive: () => boolean) => {
      setChecking(true);
      setError(null);
      setPreflight(null);
      try {
        const r = await checkPush(projectId, dest);
        if (isLive()) setPreflight(r);
      } catch (err) {
        if (isLive()) setError(pushErrorText(err, 'Pre-flight failed.'));
      } finally {
        if (isLive()) setChecking(false);
      }
    },
    [projectId],
  );

  // A registered target is checked as soon as it is chosen.
  useEffect(() => {
    if (!opened || mode !== 'target' || !targetId) {
      if (mode === 'target') setPreflight(null);
      return undefined;
    }
    let live = true;
    void runCheck({ target_id: targetId }, () => live);
    return () => {
      live = false;
    };
  }, [opened, mode, targetId, runCheck]);

  // An edited URL or code invalidates the last check.
  useEffect(() => {
    if (mode === 'url') setPreflight(null);
  }, [mode, url, code]);

  const refreshPush = useCallback(async () => {
    if (!pushId.current) return;
    try {
      setPush(await getPush(pushId.current));
    } catch (err) {
      setError(pushErrorText(err, 'Failed to read the push status.'));
    }
  }, []);

  const inFlight = push !== null && push.status !== 'submitted' && push.status !== 'failed';
  useEffect(() => {
    if (!inFlight) return undefined;
    const t = setInterval(() => void refreshPush(), POLL_MS);
    return () => clearInterval(t);
  }, [inFlight, refreshPush]);

  const handlePush = async () => {
    if (!destination) return;
    setStarting(true);
    setError(null);
    try {
      const res = await startPush(projectId, destination, message.trim() || undefined);
      pushId.current = res.push_id;
      setPush({ id: res.push_id, project_id: projectId, status: res.status });
      // The code has done its job; do not keep it around.
      setCode('');
    } catch (err) {
      setError(pushErrorText(err, 'Failed to start the push.'));
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
  const invite = preflight?.remote_info?.invite ?? null;
  const canPush =
    !!preflight &&
    preflight.can_push &&
    !preflight.in_flight &&
    !foreign &&
    blockingErrors.length === 0;
  const targetName =
    preflight?.target.name ??
    targets.find((t: MigrationTarget) => t.id === targetId)?.name ??
    (mode === 'url' ? url.trim() : '');

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
          {invite?.imports_immediately || p.credential_type === 'invite_code'
            ? `Sent to ${targetName}. It is imported there without review.`
            : `Submitted to ${targetName}. An administrator there reviews it before it is imported.`}
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

  const blocked = blockingErrors.length > 0 || foreign;
  // One message for a blocked send: the reasons the API gives overlap.
  const blockedText = foreign
    ? invite
      ? 'This project already exists there and was not brought by this code. Use the code that brought it.'
      : 'A different project with this id already exists there.'
    : blockingErrors[0];

  const renderReport = (r: PushPreflightResult) =>
    blocked ? (
      <Alert
        color="red"
        variant="light"
        icon={<Icon icon="mdi:alert-circle-outline" width={20} />}
        title={`${targetName || 'The destination'} cannot receive this project`}
        data-testid="migrate-errors"
      >
        {blockedText}
      </Alert>
    ) : (
    <Stack gap="md" data-testid="migrate-preflight">
      <Alert
        color="green"
        variant="light"
        icon={<Icon icon="mdi:check-circle-outline" width={20} />}
        title={`${targetName || 'The destination'} is ready`}
      >
        Nothing has been sent yet.
      </Alert>

      <Stack gap="sm">
        <Text size="xs" tt="uppercase" fw={700} c="dimmed">
          What will be sent
        </Text>
        <Fact icon="mdi:database-outline" title={`${formatBytes(r.total_bytes)} in ${r.object_count} files`}>
          {r.transfer_mode === 'server_side_copy'
            ? 'Copied from storage to storage, without going through this server.'
            : 'Uploaded from this server to the destination.'}
        </Fact>
      </Stack>

      {(invite || pre) && !foreign && (
        <Stack gap="sm" data-testid="migrate-invite-info">
          <Text size="xs" tt="uppercase" fw={700} c="dimmed">
            What happens there
          </Text>
          <Fact
            icon={invite ? 'mdi:flash-outline' : 'mdi:account-check-outline'}
            color={invite ? 'green' : 'yellow'}
            title={invite ? 'Imported right away' : 'Waits for an administrator'}
          >
            {invite
              ? 'The code you pasted authorises the import: nobody has to approve it.'
              : 'An administrator on the destination reviews the project before it is imported.'}
          </Fact>
          {invite && (
            <Fact
              icon={invite.lock_on_import ? 'mdi:lock-outline' : 'mdi:lock-open-variant-outline'}
              color={invite.lock_on_import ? 'orange' : 'gray'}
              title={invite.lock_on_import ? 'Read-only there' : 'Editable there'}
            >
              {invite.lock_on_import
                ? 'Nobody can change the copy on the destination until an administrator there unlocks it.'
                : 'People with access on the destination can change the copy.'}
            </Fact>
          )}
          {invite && (
            <Fact
              icon={
                invite.project_name && invite.project_id === projectId
                  ? 'mdi:update'
                  : 'mdi:plus-circle-outline'
              }
              title={
                invite.project_name && invite.project_id === projectId
                  ? 'Updates the copy it already has'
                  : 'Creates the project there'
              }
            >
              {invite.project_name && invite.project_id === projectId
                ? 'This code already brought this project: this send becomes a new version of it.'
                : 'This code is then tied to this project, and sends its later updates.'}
            </Fact>
          )}
        </Stack>
      )}
      {preflight?.in_flight && (
        <Alert color="yellow" variant="light" data-testid="migrate-in-flight">
          A send of this project is already in progress. Wait for it to finish before
          sending again.
        </Alert>
      )}
      {pre?.conflict === 're_push' && (
        <Alert color="blue" variant="light" data-testid="migrate-re-push">
          This will become a new version on the target.
        </Alert>
      )}
      {pre?.requester_has_account === false && (
        <Alert color="yellow" variant="light" data-testid="migrate-no-account">
          You have no account on the target yet: an admin will own it until you sign in there.
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
      title={`Send ${projectName ? `"${projectName}" ` : 'project '}to another instance`}
      centered
      size="lg"
      className="depictio-form-modal"
      // Opened from the project settings dialog, which sits at the overlay layer.
      zIndex={Z_LAYERS.nestedOverlay}
      data-testid="migrate-project-modal"
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Send a copy of this project, its data and its dashboards, to another Depictio
          instance. Nothing leaves this instance until you press Send.
        </Text>
        <Stepper
          active={push ? 3 : preflight ? 2 : 0}
          size="sm"
          iconSize={30}
          allowNextStepsSelect={false}
          data-testid="migrate-steps"
        >
          <Stepper.Step
            label="Destination"
            description="Where it goes"
            icon={<Icon icon="mdi:link-variant" width={16} />}
          />
          <Stepper.Step
            label="Check"
            description="Can it receive?"
            icon={<Icon icon="mdi:shield-check-outline" width={16} />}
            color={preflight && blocked ? 'red' : undefined}
            completedIcon={
              preflight && blocked ? (
                <Icon icon="mdi:close" width={16} />
              ) : undefined
            }
          />
          <Stepper.Step
            label="Send"
            description="Copy and import"
            icon={<Icon icon="mdi:transfer-up" width={16} />}
          />
        </Stepper>
        {!push && (
          <>
            {hasTargets && adhocEnabled && (
              <SegmentedControl
                fullWidth
                value={mode ?? 'target'}
                onChange={(v) => setMode(v as 'target' | 'url')}
                data={[
                  { value: 'target', label: 'Registered target' },
                  { value: 'url', label: 'URL + invite code' },
                ]}
                data-testid="migrate-mode"
              />
            )}
            {destinations !== null && !hasTargets && !adhocEnabled && (
              <Alert color="yellow" variant="light" data-testid="migrate-no-destination">
                No destination is available: no target is registered and sending to a URL is
                disabled on this instance.
              </Alert>
            )}
            {mode === 'target' && (
              <Select
                label="Target instance"
                placeholder="Choose a target"
                data={targets.map((t) => ({ value: t.id, label: `${t.name} (${t.url})` }))}
                value={targetId}
                onChange={setTargetId}
                allowDeselect={false}
                data-testid="migrate-target-select"
              />
            )}
            {mode === 'url' && (
              <Stack gap="xs">
                <Autocomplete
                  label="Destination URL"
                  leftSection={<Icon icon="mdi:link-variant" width={16} />}
                  placeholder="https://depictio.example.org"
                  description={
                    (destinations?.domains.length ?? 0) > 0
                      ? `Allowed domains: ${destinations?.domains.join(', ')}`
                      : 'The address of the instance that issued the invite code.'
                  }
                  data={destinations?.recent ?? []}
                  value={url}
                  onChange={setUrl}
                  autoComplete="off"
                  data-testid="migrate-url"
                />
                <PasswordInput
                  label="Invite code"
                  leftSection={<Icon icon="mdi:key-outline" width={16} />}
                  description="Issued by an administrator of the destination. Never stored here; keep it to send this project's updates later."
                  placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
                  value={code}
                  onChange={(e) => setCode(e.currentTarget.value)}
                  autoComplete="off"
                  data-testid="migrate-code"
                />
                <Group justify="flex-end">
                  <Button
                    size="sm"
                    variant="default"
                    leftSection={<Icon icon="mdi:shield-check-outline" width={16} />}
                    disabled={!destination || checking}
                    onClick={() => destination && void runCheck(destination, () => true)}
                    data-testid="migrate-check"
                  >
                    Check destination
                  </Button>
                </Group>
              </Stack>
            )}
            {checking && (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="sm" c="dimmed">
                  Checking the destination…
                </Text>
              </Group>
            )}
            {preflight && renderReport(preflight)}
            {preflight && (
              <Textarea
                label={preflight.remote_info?.invite ? 'Message' : 'Message to the reviewer'}
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
              Send
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
};

export default MigrateProjectModal;
