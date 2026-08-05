import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  preflightStaticExport,
  dispatchStaticExport,
  pollStaticExport,
  downloadStaticExport,
  STATIC_TIER_BADGE_LABEL,
  STATIC_TIER_BADGE_COLOR,
} from 'depictio-react-core';
import type { StaticExportPreflight } from 'depictio-react-core';

/** 'live' is deliberately absent from the shared maps — the in-bundle badge
 *  only renders non-live tiers. The preflight table shows every component, so
 *  the modal supplies the live entry itself. */
const TIER_LABEL: Record<string, string> = { live: 'Live', ...STATIC_TIER_BADGE_LABEL };
const TIER_COLOR: Record<string, string> = { live: 'green', ...STATIC_TIER_BADGE_COLOR };

/** Link tiers (A = fully resolved, B = partially resolved, inert = shipped
 *  disabled). Distinct axis from component tiers, hence a separate map. */
const LINK_TIER_COLOR: Record<string, string> = { A: 'green', B: 'yellow', inert: 'gray' };

const POLL_FIRST_MS = 800;
const POLL_INTERVAL_MS = 1500;
/** Matches the backend build task's time_limit (900 s) — past that the job
 *  can no longer succeed, so keep the modal from polling forever. */
const POLL_TIMEOUT_MS = 15 * 60 * 1000;

interface ExportStaticModalProps {
  opened: boolean;
  onClose: () => void;
  dashboardId: string | null;
  /** Used for the downloaded filename; falls back to the dashboard id. */
  dashboardTitle?: string | null;
}

/**
 * Owner-gated "Export static" flow: on open, preflight the dashboard and show
 * the per-component liveness verdict (live / partial / frozen / omitted) plus
 * the cross-DC link plan; on confirm, dispatch the Celery build, poll until
 * terminal, then download the single-file HTML bundle.
 */
const ExportStaticModal: React.FC<ExportStaticModalProps> = ({
  opened,
  onClose,
  dashboardId,
  dashboardTitle,
}) => {
  const [preflight, setPreflight] = useState<StaticExportPreflight | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Set on close/unmount so in-flight promises and the poll loop go quiet
  // instead of setting state on a closed modal. The server-side build keeps
  // running — reopening and re-exporting is cheap (idempotent job dispatch).
  const cancelledRef = useRef(false);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Preflight on open; reset transient state whenever the modal reopens.
  useEffect(() => {
    if (!opened || !dashboardId) return;
    cancelledRef.current = false;
    setPreflight(null);
    setErrorMessage(null);
    setExporting(false);
    setPreflightLoading(true);
    preflightStaticExport(dashboardId)
      .then((pf) => {
        if (!cancelledRef.current) setPreflight(pf);
      })
      .catch((err: unknown) => {
        if (!cancelledRef.current) {
          setErrorMessage(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelledRef.current) setPreflightLoading(false);
      });
    return () => {
      cancelledRef.current = true;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    };
  }, [opened, dashboardId]);

  const handleExport = async () => {
    if (!dashboardId) return;
    setExporting(true);
    setErrorMessage(null);
    const startedAt = Date.now();

    const fail = (message: string) => {
      if (cancelledRef.current) return;
      setErrorMessage(message);
      setExporting(false);
    };

    const finish = async (jobId: string) => {
      try {
        const safeName = (dashboardTitle || dashboardId).replace(/[^a-zA-Z0-9._-]+/g, '_');
        await downloadStaticExport(jobId, `depictio-${safeName}.html`);
        if (cancelledRef.current) return;
        notifications.show({
          color: 'green',
          title: 'Static export ready',
          message: 'The dashboard bundle was downloaded as a single HTML file.',
        });
        onClose();
      } catch (err) {
        fail(err instanceof Error ? err.message : String(err));
      }
    };

    try {
      const job = await dispatchStaticExport(dashboardId);
      if (cancelledRef.current) return;
      if (job.status === 'failed') {
        fail(job.error || 'Static export failed');
        return;
      }
      if (job.status === 'done') {
        await finish(job.job_id);
        return;
      }
      const tick = async () => {
        if (cancelledRef.current) return;
        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          fail(
            'Static export timed out after 15 minutes. The build may still finish server-side — try again later.',
          );
          return;
        }
        try {
          const status = await pollStaticExport(job.job_id);
          if (cancelledRef.current) return;
          if (status.status === 'done') {
            await finish(status.job_id);
          } else if (status.status === 'failed') {
            fail(status.error || 'Static export failed');
          } else {
            pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
          }
        } catch (err) {
          fail(err instanceof Error ? err.message : String(err));
        }
      };
      pollTimerRef.current = setTimeout(tick, POLL_FIRST_MS);
    } catch (err) {
      fail(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Export static dashboard"
      size="lg"
      centered
      closeOnClickOutside={false}
    >
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          Builds a self-contained HTML snapshot of this dashboard that works without a
          Depictio server. Components that need the backend degrade as shown below.
        </Text>

        {preflightLoading && (
          <Group justify="center" gap="xs" py="md">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              Analyzing components…
            </Text>
          </Group>
        )}

        {errorMessage && (
          <Alert
            color="red"
            variant="light"
            icon={<Icon icon="mdi:alert-circle" />}
            title="Export failed"
          >
            {/* Errors can be long multi-line hints — wrap, never truncate. */}
            <Text size="sm" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {errorMessage}
            </Text>
          </Alert>
        )}

        {preflight && (
          <>
            <Group gap="xs">
              {(['live', 'partial', 'frozen', 'omitted'] as const).map((tier) => (
                <Badge
                  key={tier}
                  color={TIER_COLOR[tier]}
                  variant="light"
                  style={{ textTransform: 'none' }}
                >
                  {TIER_LABEL[tier]}: {preflight.counts[tier] ?? 0}
                </Badge>
              ))}
            </Group>

            <Table.ScrollContainer minWidth={480}>
              <Table verticalSpacing="xs" striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Component</Table.Th>
                    <Table.Th>Type</Table.Th>
                    <Table.Th>Tier</Table.Th>
                    <Table.Th>Note</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {preflight.tiers.map((row) => (
                    <Table.Tr key={row.component_id}>
                      <Table.Td>{row.title || row.component_id}</Table.Td>
                      <Table.Td>{row.component_type || '—'}</Table.Td>
                      <Table.Td>
                        <Badge
                          size="xs"
                          variant="light"
                          color={TIER_COLOR[row.tier] ?? 'gray'}
                          style={{ textTransform: 'none' }}
                          data-static-tier={row.tier}
                        >
                          {TIER_LABEL[row.tier] ?? row.tier}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {row.detail || row.reason || ''}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>

            {preflight.links.length > 0 && (
              <>
                <Text size="sm" fw={500}>
                  Cross-DC links
                </Text>
                <Table.ScrollContainer minWidth={480}>
                  <Table verticalSpacing="xs" striped>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Link</Table.Th>
                        <Table.Th>Resolver</Table.Th>
                        <Table.Th>Tier</Table.Th>
                        <Table.Th>Entries</Table.Th>
                        <Table.Th>Note</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {preflight.links.map((link) => (
                        <Table.Tr key={link.link_id}>
                          <Table.Td>
                            {link.source} → {link.target}
                          </Table.Td>
                          <Table.Td>{link.resolver}</Table.Td>
                          <Table.Td>
                            <Badge
                              size="xs"
                              variant="light"
                              color={LINK_TIER_COLOR[link.tier] ?? 'gray'}
                              style={{ textTransform: 'none' }}
                            >
                              {link.enabled ? link.tier : `${link.tier} (disabled)`}
                            </Badge>
                          </Table.Td>
                          <Table.Td>{link.entries}</Table.Td>
                          <Table.Td>
                            <Text size="xs" c="dimmed">
                              {link.note || ''}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
              </>
            )}
          </>
        )}

        {exporting && (
          <Group gap="xs">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              Building bundle… this can take a few minutes for large dashboards.
            </Text>
          </Group>
        )}

        <Group justify="flex-end" gap="xs" mt="sm">
          {/* Cancel stays enabled during the build: closing only stops the
              client-side polling, the server keeps building. */}
          <Button variant="subtle" onClick={onClose}>
            Cancel
          </Button>
          <Button
            color="violet"
            leftSection={<Icon icon="mdi:export-variant" width={14} />}
            onClick={handleExport}
            loading={exporting}
            disabled={!dashboardId || !preflight || exporting}
            data-testid="confirm-export-static-btn"
          >
            Export
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default ExportStaticModal;
