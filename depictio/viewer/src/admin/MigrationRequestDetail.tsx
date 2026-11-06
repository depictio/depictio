import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Center,
  Checkbox,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  Textarea,
  ThemeIcon,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  approveMigrationRequest,
  getMigrationRequest,
  regenerateMigrationThumbnails,
  rejectMigrationRequest,
  revalidateMigrationRequest,
} from 'depictio-react-core';
import type { MigrationDashboardSummary, MigrationRequestDetail } from 'depictio-react-core';

import { formatDateTime } from '../lib/datetime';
import { useTone } from '../monitoring/useTone';
import { DcTypeBadge } from '../projects/dcTypeIcon';

const POLL_MS = 2000;

export const STATUS_COLOR: Record<string, string> = {
  pending: 'yellow',
  importing: 'blue',
  imported: 'green',
  rejected: 'gray',
  failed: 'red',
  superseded: 'gray',
};

export function formatBytes(bytes?: number | null): string {
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

export const modeLabel = (mode?: string) =>
  mode === 'server_side_copy' ? 'Server-side copy' : mode === 'inline' ? 'Inline upload' : '—';

/** A dashboard entry in a report may be a bare name or an object. */
function entryLabel(entry: unknown): string {
  if (typeof entry === 'string') return entry;
  if (entry && typeof entry === 'object') {
    const e = entry as Record<string, unknown>;
    for (const k of ['title', 'name', 'dashboard_title', 'id']) {
      if (typeof e[k] === 'string') return e[k] as string;
    }
  }
  return String(entry);
}

export const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const tone = useTone();
  return (
    <Badge variant="light" color={tone(STATUS_COLOR[status] ?? 'gray')} size="sm">
      {status}
    </Badge>
  );
};

const Fact: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Group justify="space-between" wrap="nowrap" align="baseline" gap="md">
    <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ flexShrink: 0 }}>
      {label}
    </Text>
    <Text size="sm" component="div" ta="right" style={{ minWidth: 0, wordBreak: 'break-word' }}>
      {children}
    </Text>
  </Group>
);

/** A titled block of the request: the same card for every section. */
const Section: React.FC<{
  title: string;
  icon: string;
  testId?: string;
  children: React.ReactNode;
}> = ({ title, icon, testId, children }) => (
  <Paper withBorder radius="sm" p="md" data-testid={testId}>
    <Stack gap="xs">
      <Group gap={6} wrap="nowrap">
        <Icon icon={icon} width={16} aria-hidden />
        <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
          {title}
        </Text>
      </Group>
      {children}
    </Stack>
  </Paper>
);

const DASHBOARD_CHANGE_COLOR: Record<string, string> = {
  added: 'green',
  replaced: 'blue',
  removed: 'red',
};

interface DashboardRow extends MigrationDashboardSummary {
  change: 'added' | 'replaced' | 'removed';
}

/** The report's dashboards, each with what the import does to it. A removed
 *  one is only an id: the bundle no longer holds it. */
function dashboardRowsOf(report: NonNullable<MigrationRequestDetail['report']>): DashboardRow[] {
  const known = new Map((report.dashboards ?? []).map((d) => [d.id, d]));
  const rows: DashboardRow[] = [];
  const add = (ids: unknown[] | undefined, change: DashboardRow['change']) => {
    for (const raw of ids ?? []) {
      const id = typeof raw === 'string' ? raw : entryLabel(raw);
      rows.push({
        id,
        title: known.get(id)?.title ?? null,
        icon: known.get(id)?.icon ?? null,
        icon_color: known.get(id)?.icon_color ?? null,
        parent_dashboard_id: known.get(id)?.parent_dashboard_id ?? null,
        change,
      });
    }
  };
  add(report.dashboards_added, 'added');
  add(report.dashboards_replaced, 'replaced');
  add(report.dashboards_removed, 'removed');
  return rows;
}

interface DetailProps {
  requestId: string;
  onClose: () => void;
  onChanged: () => void;
}

/** Drawer body: loads one request and polls it while the import runs. */
export const RequestDetail: React.FC<DetailProps> = ({ requestId, onClose, onChanged }) => {
  const [detail, setDetail] = useState<MigrationRequestDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [lock, setLock] = useState(true);
  const [makePublic, setMakePublic] = useState(false);
  const [reason, setReason] = useState('');
  const lastStatus = useRef<string | null>(null);
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  const load = useCallback(async () => {
    try {
      const d = await getMigrationRequest(requestId);
      setDetail(d);
      setError(null);
      // The list behind the drawer follows a status change (importing -> imported).
      if (lastStatus.current !== null && lastStatus.current !== d.status) onChangedRef.current();
      lastStatus.current = d.status;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the request.');
    }
  }, [requestId]);

  useEffect(() => {
    lastStatus.current = null;
    setDetail(null);
    void load();
  }, [load]);

  const importing = detail?.status === 'importing';
  useEffect(() => {
    if (!importing) return undefined;
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [importing, load]);

  const openApprove = () => {
    setLock(detail?.lock_imported_default ?? true);
    setMakePublic(false);
    setApproveOpen(true);
  };

  const fail = (title: string, err: unknown) =>
    notifications.show({
      color: 'red',
      title,
      message: err instanceof Error ? err.message : 'Unknown error',
    });

  const handleApprove = async () => {
    setBusy(true);
    try {
      await approveMigrationRequest(requestId, { lock, make_public: makePublic });
      setApproveOpen(false);
      notifications.show({ message: 'Import started.' });
      await load();
      onChanged();
    } catch (err) {
      fail('Could not approve', err);
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    setBusy(true);
    try {
      await rejectMigrationRequest(requestId, reason.trim());
      setRejectOpen(false);
      setReason('');
      notifications.show({ message: 'Request rejected.' });
      await load();
      onChanged();
    } catch (err) {
      fail('Could not reject', err);
    } finally {
      setBusy(false);
    }
  };

  const handleThumbnails = async () => {
    setBusy(true);
    try {
      const res = await regenerateMigrationThumbnails(requestId);
      notifications.show({
        message:
          res.queued > 0
            ? `Thumbnails queued for ${res.queued} dashboard${res.queued === 1 ? '' : 's'}. They appear in a minute.`
            : 'No dashboard to capture.',
      });
    } catch (err) {
      fail('Could not queue thumbnails', err);
    } finally {
      setBusy(false);
    }
  };

  const handleRevalidate = async () => {
    setBusy(true);
    try {
      const res = await revalidateMigrationRequest(requestId);
      setDetail((d) => (d ? { ...d, report: res.report } : d));
      notifications.show({ message: 'Re-validated against the current state.' });
      onChanged();
    } catch (err) {
      fail('Could not re-validate', err);
    } finally {
      setBusy(false);
    }
  };

  if (error && !detail) {
    return (
      <Alert color="red" variant="light">
        {error}
      </Alert>
    );
  }
  if (!detail) {
    return (
      <Center mih={120}>
        <Loader />
      </Center>
    );
  }

  const report = detail.report ?? {};
  const errors = report.errors ?? [];
  const warnings = report.warnings ?? [];
  const counts = Object.entries(report.document_counts ?? {});
  const dataCollections = report.data_collections ?? [];
  const dashboardRows = dashboardRowsOf(report);
  const isPending = detail.status === 'pending';
  const approveBlocked = errors.length > 0;

  return (
    <Stack gap="md" data-testid="migration-detail">
      <Group justify="space-between">
        <Title order={4}>{detail.project_name}</Title>
        <Group gap="xs" wrap="nowrap">
          {detail.status === 'imported' && detail.result?.project_id && (
            <Button
              component="a"
              href={`/projects/${detail.result.project_id}`}
              size="compact-sm"
              variant="light"
              leftSection={<Icon icon="mdi:open-in-new" width={14} />}
              data-testid="migration-open-project"
            >
              Open project
            </Button>
          )}
          <StatusBadge status={detail.status} />
        </Group>
      </Group>

      <Section title="Origin" icon="mdi:source-branch-sync" testId="migration-origin">
        <Fact label="Source">{detail.source_name}</Fact>
        {detail.source_instance && <Fact label="Instance">{detail.source_instance}</Fact>}
        <Fact label="Host / URL">
          {detail.source_url ? (
            <Text component="span" size="sm" ff="monospace" data-testid="migration-source-url">
              {detail.source_url}
            </Text>
          ) : (
            <Text component="span" size="sm" c="dimmed">
              Not reported by the sender (it runs an older version)
            </Text>
          )}
        </Fact>
        {detail.credential_type === 'invite_code' && (
          <Fact label="Invite">
            {detail.invite_note ? `${detail.invite_note} ` : ''}
            {detail.invite_code_hint ? (
              <Text component="span" size="sm" c="dimmed" ff="monospace">
                (code ending {detail.invite_code_hint})
              </Text>
            ) : null}
            {!detail.invite_note && !detail.invite_code_hint ? 'Invite code' : null}
          </Fact>
        )}
        <Fact label="Requester">
          {detail.requester?.name ? `${detail.requester.name} ` : ''}
          {detail.requester?.email ?? '—'}
        </Fact>
        <Fact label="Requester account here">
          {detail.requester_has_account
            ? 'Yes'
            : 'No: an admin will own the project until they sign in'}
        </Fact>
      </Section>

      <Section title="Transfer" icon="mdi:swap-horizontal" testId="migration-transfer">
        <Fact label="Source version">{detail.source_depictio_version ?? '—'}</Fact>
        <Fact label="Target version">{detail.target_depictio_version ?? '—'}</Fact>
        <Fact label="Transfer mode">{modeLabel(detail.transfer_mode)}</Fact>
        <Fact label="Bundle size">{formatBytes(detail.bundle_bytes)}</Fact>
        {typeof report.total_bytes === 'number' && (
          <Fact label="Data size">{formatBytes(report.total_bytes)}</Fact>
        )}
        {typeof report.object_count === 'number' && (
          <Fact label="Objects">{report.object_count}</Fact>
        )}
        <Fact label="Submitted">{formatDateTime(detail.created_at)}</Fact>
        {detail.message && <Fact label="Message">{detail.message}</Fact>}
      </Section>

      {detail.conflict === 're_push' && (
        <Alert color="blue" variant="light" icon={<Icon icon="mdi:source-branch" />}>
          This project was imported from this source before. Approving creates a new version
          of it{detail.existing_locked ? ' (the existing copy is published read-only)' : ''}.
        </Alert>
      )}
      {detail.conflict === 'foreign' && (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          A project with this id already exists here and did not come from this source.
        </Alert>
      )}

      {dataCollections.length > 0 && (
        <Section
          title={`Data collections (${dataCollections.length})`}
          icon="mdi:database-outline"
          testId="migration-data-collections"
        >
          {dataCollections.map((dc, i) => (
            <Group key={dc.id ?? i} gap="sm" wrap="nowrap" align="flex-start">
              <div style={{ flexShrink: 0, minWidth: 120 }}>
                <DcTypeBadge dc={{ config: { type: dc.type ?? undefined } }} />
              </div>
              <div style={{ minWidth: 0 }}>
                <Text size="sm" fw={500} data-testid="migration-dc-tag">
                  {dc.tag ?? dc.id ?? '—'}
                </Text>
                {dc.description && (
                  <Text size="xs" c="dimmed">
                    {dc.description}
                  </Text>
                )}
              </div>
            </Group>
          ))}
        </Section>
      )}

      {dashboardRows.length > 0 && (
        <Section
          title={`Dashboards (${dashboardRows.length})`}
          icon="mdi:view-dashboard-outline"
          testId="migration-dashboards"
        >
          {dashboardRows.map((d) => (
            <Group
              key={d.id}
              gap="sm"
              wrap="nowrap"
              pl={d.parent_dashboard_id ? 'lg' : 0}
              data-testid="migration-dashboard-row"
            >
              <ThemeIcon
                size="md"
                radius="xl"
                color={d.icon_color || 'gray'}
                variant="filled"
                aria-hidden
              >
                <Icon icon={d.icon && d.icon.includes(':') ? d.icon : 'mdi:view-dashboard'} width={16} />
              </ThemeIcon>
              <div style={{ minWidth: 0, flex: 1 }}>
                <Text size="sm" fw={500} truncate>
                  {d.title ?? 'Untitled dashboard'}
                  {d.parent_dashboard_id && (
                    <Text component="span" size="xs" c="dimmed">
                      {' '}
                      (tab)
                    </Text>
                  )}
                </Text>
                <Text size="xs" c="dimmed" ff="monospace" data-testid="migration-dashboard-id">
                  {d.id}
                </Text>
              </div>
              <Badge variant="light" size="sm" color={DASHBOARD_CHANGE_COLOR[d.change]}>
                {d.change}
              </Badge>
            </Group>
          ))}
          {detail.status === 'imported' && (
            <Stack gap={6} mt="xs" align="flex-start">
              <Text size="xs" c="dimmed">
                A bundle carries no thumbnails: imported dashboards show none until captured.
              </Text>
              <Button
                size="compact-sm"
                variant="light"
                loading={busy}
                onClick={() => void handleThumbnails()}
                leftSection={<Icon icon="mdi:image-refresh-outline" width={14} />}
                data-testid="migration-thumbnails"
              >
                Regenerate thumbnails
              </Button>
            </Stack>
          )}
        </Section>
      )}

      {counts.length > 0 && (
        <Section title="Documents" icon="mdi:file-document-multiple-outline" testId="migration-documents">
          {counts.map(([k, v]) => (
            <Fact key={k} label={k.replace(/_/g, ' ')}>
              {v}
            </Fact>
          ))}
        </Section>
      )}

      {errors.length > 0 && (
        <Alert color="red" variant="light" title="Errors" data-testid="migration-errors">
          <Stack gap={2}>
            {errors.map((e, i) => (
              <Text key={i} size="sm">
                {e}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}
      {warnings.length > 0 && (
        <Alert color="yellow" variant="light" title="Warnings" data-testid="migration-warnings">
          <Stack gap={2}>
            {warnings.map((w, i) => (
              <Text key={i} size="sm">
                {w}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      {detail.status === 'importing' && (
        <Group gap="xs" data-testid="migration-importing">
          <Loader size="xs" />
          <Text size="sm">Importing…</Text>
        </Group>
      )}
      {detail.status === 'rejected' && detail.decision?.reason && (
        <Alert color="gray" variant="light" title="Rejected">
          {detail.decision.reason}
        </Alert>
      )}
      {detail.status === 'failed' && detail.error && (
        <Alert color="red" variant="light" title="Import failed">
          {detail.error}
        </Alert>
      )}
      {detail.status === 'imported' && detail.result && (
        <Alert color="green" variant="light" title="Imported">
          Project imported{detail.result.locked ? ', published read-only' : ''}
          {detail.result.made_public ? ', public' : ''}.
        </Alert>
      )}

      <Group justify="space-between">
        <Button
          variant="default"
          onClick={() => void handleRevalidate()}
          loading={busy}
          disabled={!isPending}
          leftSection={<Icon icon="mdi:refresh" width={16} />}
          data-testid="migration-revalidate"
        >
          Revalidate
        </Button>
        <Group gap="xs">
          <Button variant="subtle" color="gray" onClick={onClose}>
            Close
          </Button>
          <Button
            color="red"
            variant="light"
            disabled={!isPending || busy}
            onClick={() => setRejectOpen(true)}
            data-testid="migration-reject"
          >
            Reject
          </Button>
          <Button
            disabled={!isPending || busy || approveBlocked}
            onClick={openApprove}
            data-testid="migration-approve"
          >
            Approve
          </Button>
        </Group>
      </Group>

      <Modal
        opened={approveOpen}
        onClose={() => setApproveOpen(false)}
        title="Approve and import"
        centered
        data-testid="migration-approve-modal"
      >
        <Stack gap="md">
          <Checkbox
            label="Lock editing (read-only)"
            description="Nobody can change its dashboards or data here, owners included, until an admin unlocks it."
            checked={lock}
            onChange={(e) => setLock(e.currentTarget.checked)}
            data-testid="migration-approve-lock"
          />
          <Checkbox
            label="Make public"
            description="Everyone on this instance can view it. Who can edit is unchanged."
            checked={makePublic}
            onChange={(e) => setMakePublic(e.currentTarget.checked)}
            data-testid="migration-approve-public"
          />
          <Group justify="flex-end">
            <Button variant="subtle" color="gray" onClick={() => setApproveOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={busy}
              onClick={() => void handleApprove()}
              data-testid="migration-approve-confirm"
            >
              Import
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={rejectOpen}
        onClose={() => setRejectOpen(false)}
        title="Reject request"
        centered
        data-testid="migration-reject-modal"
      >
        <Stack gap="md">
          <Textarea
            label="Reason"
            description="Shown to the sender. Required."
            value={reason}
            maxLength={1000}
            autosize
            minRows={3}
            onChange={(e) => setReason(e.currentTarget.value)}
            data-testid="migration-reject-reason"
          />
          <Group justify="flex-end">
            <Button variant="subtle" color="gray" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button
              color="red"
              loading={busy}
              disabled={reason.trim() === ''}
              onClick={() => void handleReject()}
              data-testid="migration-reject-confirm"
            >
              Reject
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};
