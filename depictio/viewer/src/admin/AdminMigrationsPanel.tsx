import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Center,
  Checkbox,
  Drawer,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  approveMigrationRequest,
  getMigrationRequest,
  listMigrationRequests,
  rejectMigrationRequest,
  retryMigrationRequest,
  revalidateMigrationRequest,
} from 'depictio-react-core';
import type { MigrationRequestDetail, MigrationRequestSummary } from 'depictio-react-core';

import { formatDateTime } from '../lib/datetime';
import { useTone } from '../monitoring/useTone';
import AdminMigrationInvitesView from './AdminMigrationInvitesView';
import AdminMigrationSentView from './AdminMigrationSentView';

const POLL_MS = 2000;

const STATUS_FILTERS = [
  { value: '', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'importing', label: 'Importing' },
  { value: 'imported', label: 'Imported' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'failed', label: 'Failed' },
  { value: 'superseded', label: 'Superseded' },
];

const STATUS_COLOR: Record<string, string> = {
  pending: 'yellow',
  importing: 'blue',
  imported: 'green',
  rejected: 'gray',
  failed: 'red',
  superseded: 'gray',
};

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

const modeLabel = (mode?: string) =>
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

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
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

const DashboardList: React.FC<{ label: string; items?: unknown[] }> = ({ label, items }) =>
  items && items.length > 0 ? (
    <Fact label={label}>{items.map(entryLabel).join(', ')}</Fact>
  ) : null;

interface DetailProps {
  requestId: string;
  onClose: () => void;
  onChanged: () => void;
}

/** Drawer body: loads one request and polls it while the import runs. */
const RequestDetail: React.FC<DetailProps> = ({ requestId, onClose, onChanged }) => {
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
  const isPending = detail.status === 'pending';
  const approveBlocked = errors.length > 0;

  return (
    <Stack gap="md" data-testid="migration-detail">
      <Group justify="space-between">
        <Title order={4}>{detail.project_name}</Title>
        <StatusBadge status={detail.status} />
      </Group>

      <Paper withBorder radius="sm" p="md">
        <Stack gap="xs">
          <Fact label="Source">{detail.source_name}</Fact>
          <Fact label="Requester">
            {detail.requester?.name ? `${detail.requester.name} ` : ''}
            {detail.requester?.email ?? '—'}
          </Fact>
          <Fact label="Requester account here">
            {detail.requester_has_account
              ? 'Yes'
              : 'No: an admin will own the project until they sign in'}
          </Fact>
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
        </Stack>
      </Paper>

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

      {counts.length > 0 && (
        <Paper withBorder radius="sm" p="md">
          <Stack gap="xs">
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Documents
            </Text>
            {counts.map(([k, v]) => (
              <Fact key={k} label={k.replace(/_/g, ' ')}>
                {v}
              </Fact>
            ))}
          </Stack>
        </Paper>
      )}

      {((report.dashboards_added?.length ?? 0) > 0 ||
        (report.dashboards_replaced?.length ?? 0) > 0 ||
        (report.dashboards_removed?.length ?? 0) > 0) && (
        <Paper withBorder radius="sm" p="md">
          <Stack gap="xs">
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Dashboards
            </Text>
            <DashboardList label="Added" items={report.dashboards_added} />
            <DashboardList label="Replaced" items={report.dashboards_replaced} />
            <DashboardList label="Removed" items={report.dashboards_removed} />
          </Stack>
        </Paper>
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

/**
 * Requests: projects other Depictio instances pushed here. A pairing-key push
 * waits for review: an admin inspects the validation report, then approves (the
 * import runs in the background) or rejects with a reason. An invite-code push
 * imports at once; it shows here too, and a failed one can be retried.
 */
const RequestsView: React.FC = () => {
  const [requests, setRequests] = useState<MigrationRequestSummary[]>([]);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

  const handleRetry = async (id: string) => {
    setRetrying(id);
    try {
      await retryMigrationRequest(id);
      notifications.show({ message: 'Import started again.' });
      await load();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not retry',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setRetrying(null);
    }
  };

  const load = useCallback(async () => {
    try {
      setRequests(await listMigrationRequests(status || undefined));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load migration requests.');
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={4}>Migration requests</Title>
        <Group gap="xs">
          <Select
            size="xs"
            w={170}
            allowDeselect={false}
            aria-label="Filter by status"
            data={STATUS_FILTERS}
            value={status}
            onChange={(v) => setStatus(v ?? '')}
            data-testid="migrations-status-filter"
          />
          <Button
            size="xs"
            variant="default"
            onClick={() => void load()}
            leftSection={<Icon icon="mdi:refresh" width={14} />}
          >
            Refresh
          </Button>
        </Group>
      </Group>

      {loading ? (
        <Center mih={120}>
          <Loader />
        </Center>
      ) : error ? (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      ) : requests.length === 0 ? (
        <Center mih={120}>
          <Text c="dimmed" size="sm" data-testid="migrations-empty">
            No migration requests.
          </Text>
        </Center>
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table withTableBorder highlightOnHover fz="sm" data-testid="migrations-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Status</Table.Th>
                <Table.Th>Source</Table.Th>
                <Table.Th>Requester</Table.Th>
                <Table.Th>Project</Table.Th>
                <Table.Th>Mode</Table.Th>
                <Table.Th>Size</Table.Th>
                <Table.Th>Submitted</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {requests.map((r) => (
                <Table.Tr
                  key={r.id}
                  style={{ cursor: 'pointer' }}
                  onClick={() => setSelected(r.id)}
                  data-testid="migration-row"
                  data-status={r.status}
                >
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      <StatusBadge status={r.status} />
                      {r.credential_type === 'invite_code' && (
                        <Badge color="grape" variant="outline" size="xs">
                          invite
                        </Badge>
                      )}
                      {r.error_count > 0 && (
                        <Badge color="red" variant="outline" size="xs">
                          {r.error_count} err
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>{r.source_name}</Table.Td>
                  <Table.Td>{r.requester?.email ?? r.requester?.name ?? '—'}</Table.Td>
                  <Table.Td>{r.project_name}</Table.Td>
                  <Table.Td>{modeLabel(r.transfer_mode)}</Table.Td>
                  <Table.Td>{formatBytes(r.bundle_bytes)}</Table.Td>
                  <Table.Td>
                    {formatDateTime(r.created_at)}
                    {r.status === 'failed' && r.error && (
                      <Text size="xs" c="red" style={{ wordBreak: 'break-word' }}>
                        {r.error}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td onClick={(e) => e.stopPropagation()}>
                    {r.retryable && (
                      <Button
                        size="compact-xs"
                        variant="light"
                        loading={retrying === r.id}
                        onClick={() => void handleRetry(r.id)}
                        leftSection={<Icon icon="mdi:reload" width={14} />}
                        data-testid="migration-retry"
                      >
                        Retry
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <Drawer
        opened={selected !== null}
        onClose={() => setSelected(null)}
        position="right"
        size="lg"
        title="Migration request"
      >
        {selected && (
          <RequestDetail
            requestId={selected}
            onClose={() => setSelected(null)}
            onChanged={() => void load()}
          />
        )}
      </Drawer>
    </Stack>
  );
};

/**
 * Admin > Migrations: what other instances pushed here (Requests), the codes
 * that let them (Invitations), and what this instance pushed out (Sent).
 */
const AdminMigrationsPanel: React.FC = () => {
  const [tab, setTab] = useState<string>('requests');
  return (
    <Tabs value={tab} onChange={(v) => v && setTab(v)} keepMounted={false}>
      <Tabs.List mb="md">
        <Tabs.Tab value="requests" data-testid="migrations-tab-requests">
          Requests
        </Tabs.Tab>
        <Tabs.Tab value="invitations" data-testid="migrations-tab-invitations">
          Invitations
        </Tabs.Tab>
        <Tabs.Tab value="sent" data-testid="migrations-tab-sent">
          Sent
        </Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="requests">
        <RequestsView />
      </Tabs.Panel>
      <Tabs.Panel value="invitations">
        <AdminMigrationInvitesView />
      </Tabs.Panel>
      <Tabs.Panel value="sent">
        <AdminMigrationSentView />
      </Tabs.Panel>
    </Tabs>
  );
};

export default AdminMigrationsPanel;
