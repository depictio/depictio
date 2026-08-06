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
  staticTierExplanation,
  STATIC_TIER_BADGE_LABEL,
  STATIC_TIER_BADGE_COLOR,
} from 'depictio-react-core';
import type {
  StaticExportPreflight,
  StaticExportSizeEstimate,
  StaticExportTierRow,
} from 'depictio-react-core';

/** 'live' is deliberately absent from the shared maps — the in-bundle badge
 *  only renders non-live tiers. The preflight table shows every component, so
 *  the modal supplies the live entry itself. */
const TIER_LABEL: Record<string, string> = { live: 'Live', ...STATIC_TIER_BADGE_LABEL };
const TIER_COLOR: Record<string, string> = { live: 'green', ...STATIC_TIER_BADGE_COLOR };

/** Vocabulary for a row the preflight cannot settle (see `isProvisional`).
 *  One word, because it shares the narrow Tier column with 'Live'/'Frozen';
 *  the note spells out that the verdict comes with the build. */
const UNDECIDED_LABEL = 'Undecided';
const UNDECIDED_COLOR = 'gray';
const UNDECIDED_NOTE =
  'Depictio tries to redraw this chart in your browser while it builds the bundle. ' +
  'If it succeeds the chart stays interactive; if not, it ships as a snapshot of the whole dataset.';

/**
 * Whether the build can still overturn this row's verdict.
 *
 * Expected to be false on every row now: the endpoint runs the bind-and-refill
 * builder for real before it answers, so a figure's tier is a verdict rather
 * than a guess. This path survives for a viewer talking to an older API, which
 * classified data-free — it called EVERY figure frozen/binding_miss and let the
 * build upgrade the ones it could redraw, promising far more frozen tiles than
 * a bundle actually ships (on the reference dashboards, 18 predicted binding
 * misses against 5 real ones). Those rows read as undecided rather than frozen.
 *
 * The endpoint states it with `provisional`; the inferred fallback identifies
 * exactly the rows an older one could not settle.
 */
function isProvisional(row: StaticExportTierRow): boolean {
  if (typeof row.provisional === 'boolean') return row.provisional;
  return (
    row.component_type === 'figure' && row.tier === 'frozen' && row.reason === 'binding_miss'
  );
}

/** Link tiers (A = fully resolved, B = partially resolved, inert = shipped
 *  disabled). Distinct axis from component tiers, hence a separate map. */
const LINK_TIER_COLOR: Record<string, string> = { A: 'green', B: 'yellow', inert: 'gray' };

const BYTES_PER_MB = 1024 * 1024;

/**
 * Whole megabytes, never a decimal.
 *
 * The preflight sizes the data from row/column counts before anything is
 * compressed, so the figure runs about twice the file a reader actually gets.
 * A tenth of a megabyte on top of an error bar that wide would be invented
 * precision; and since the number is a ceiling, rounding a fraction up to 1 MB
 * still overstates rather than understates.
 */
function approxMB(bytes: number): string {
  return `${Math.max(1, Math.round(bytes / BYTES_PER_MB))} MB`;
}

/** Why every size in this modal is prefixed "up to". Said once, next to the
 *  number, because a reader who takes the estimate for a measurement will
 *  think the export lied to them when a 40 MB prediction downloads as 18 MB. */
const SIZE_UPPER_BOUND_NOTE =
  'That is an upper bound: the data is sized before it is compressed, so the file you get is usually smaller.';

/**
 * What the size estimate means for the reader, before they commit to a build.
 *
 * Three verdicts, same voice as the tier notes: what you will end up with, and
 * what is awkward about it. `would_be_refused` is a warning rather than a
 * block — the ceiling is enforced against the REAL bytes mid-build, and this
 * prediction overshoots, so a bundle the preflight calls too large can still
 * squeeze under. Disabling Export here would refuse builds the server would
 * have accepted; the reader is told what is likely and left to decide.
 */
const SizeEstimate: React.FC<{ size: StaticExportSizeEstimate }> = ({ size }) => {
  const total = size.estimated_total_bytes;
  if (typeof total !== 'number') return null;
  const upTo = `up to about ${approxMB(total)}`;

  if (size.verdict === 'would_be_refused') {
    return (
      <Alert
        color="red"
        variant="light"
        icon={<Icon icon="mdi:alert-circle" />}
        title="Probably too large to export"
        data-testid="export-size-estimate"
        data-size-verdict={size.verdict}
      >
        <Text size="sm">
          This dashboard would build a file of {upTo}, past the{' '}
          {size.hard_limit_mb ? `${size.hard_limit_mb} MB ` : ''}
          limit this server allows, so the build is likely to be refused. Fewer or narrower
          components would bundle less data, or an administrator can raise the limit.{' '}
          {SIZE_UPPER_BOUND_NOTE}
        </Text>
      </Alert>
    );
  }

  if (size.verdict === 'over_soft_limit') {
    return (
      <Alert
        color="yellow"
        variant="light"
        icon={<Icon icon="mdi:alert-outline" />}
        title="Large file"
        data-testid="export-size-estimate"
        data-size-verdict={size.verdict}
      >
        <Text size="sm">
          This dashboard builds a file of {upTo}. It works, but a file that size is awkward to
          send by mail, and nothing appears on screen until the whole of it has loaded.{' '}
          {SIZE_UPPER_BOUND_NOTE}
        </Text>
      </Alert>
    );
  }

  return (
    <Text
      size="xs"
      c="dimmed"
      data-testid="export-size-estimate"
      data-size-verdict={size.verdict ?? 'unknown'}
    >
      Expect a file of {upTo}. {SIZE_UPPER_BOUND_NOTE}
    </Text>
  );
};

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

  // Counts are recomputed from the rows rather than read from `preflight.counts`
  // so the badges and the table agree on what is settled: the endpoint's counts
  // include the undecided figures as frozen.
  const rows: StaticExportTierRow[] = preflight?.tiers ?? [];
  const undecidedCount = rows.filter(isProvisional).length;
  const decidedCounts = { live: 0, partial: 0, frozen: 0, omitted: 0 };
  for (const row of rows) {
    if (!isProvisional(row) && row.tier in decidedCounts) decidedCounts[row.tier] += 1;
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Export static dashboard"
      // The tier table is the body of this modal: component title, tier chip
      // and a per-row note, times one row per component (74 of them on the
      // ampliseq family). At `lg` the note column wrapped to three lines and
      // the table dominated the viewport; `xl` gives the note room to breathe.
      size="xl"
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
            {/* Seconds, not milliseconds: the preflight loads each data
                collection and tries to redraw every figure in order to answer
                with a verdict rather than a guess. Say so, or the wait reads
                as the modal being stuck. */}
            <Text size="sm" c="dimmed">
              Redrawing every chart to see which ones stay interactive…
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
                  {TIER_LABEL[tier]}: {decidedCounts[tier]}
                </Badge>
              ))}
              {undecidedCount > 0 && (
                <Badge
                  color={UNDECIDED_COLOR}
                  variant="outline"
                  style={{ textTransform: 'none' }}
                  data-testid="undecided-count-badge"
                >
                  {UNDECIDED_LABEL}: {undecidedCount}
                </Badge>
              )}
            </Group>

            {undecidedCount > 0 && (
              // The counts above are only the settled rows, so say what the
              // rest are: promising "24 frozen" and shipping 9 is the failure
              // mode this replaces.
              <Text size="xs" c="dimmed">
                {undecidedCount} chart{undecidedCount > 1 ? 's are' : ' is'} not decided yet: the
                build redraws each one in your browser where it can and falls back to a snapshot
                where it cannot. The counts above cover the {rows.length - undecidedCount}{' '}
                component{rows.length - undecidedCount === 1 ? '' : 's'} already decided.
              </Text>
            )}

            <Table.ScrollContainer minWidth={480}>
              <Table verticalSpacing="xs" striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Component</Table.Th>
                    <Table.Th>Type</Table.Th>
                    {/* Fixed: auto layout hands the Note column everything and
                        ellipsises the tier badge down to "Und…". */}
                    <Table.Th w={104}>Tier</Table.Th>
                    <Table.Th>Note</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((row) => {
                    const undecided = isProvisional(row);
                    return (
                      <Table.Tr key={row.component_id}>
                        <Table.Td>{row.title || row.component_id}</Table.Td>
                        <Table.Td>{row.component_type || '—'}</Table.Td>
                        {/* nowrap: the Note column otherwise squeezes this one
                            until Mantine ellipsises the badge label ("Dec…"). */}
                        <Table.Td style={{ whiteSpace: 'nowrap' }}>
                          <Badge
                            size="xs"
                            variant={undecided ? 'outline' : 'light'}
                            color={undecided ? UNDECIDED_COLOR : (TIER_COLOR[row.tier] ?? 'gray')}
                            style={{ textTransform: 'none' }}
                            data-static-tier={undecided ? 'provisional' : row.tier}
                          >
                            {undecided ? UNDECIDED_LABEL : (TIER_LABEL[row.tier] ?? row.tier)}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          {/* Never the producer's `detail` and never the raw
                              `reason` token: the note says what the reader will
                              lose, in the words the bundle's own badge uses. */}
                          <Text size="xs" c="dimmed">
                            {undecided
                              ? UNDECIDED_NOTE
                              : (staticTierExplanation(row.tier, row.reason) ?? '')}
                          </Text>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
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

        {/* Last thing above the Export button rather than up with the counts:
            the tier table is long enough that a reader reaches the button by
            scrolling past everything else, and a size warning they scrolled
            over is a size warning they did not read. */}
        {preflight?.size_estimate && <SizeEstimate size={preflight.size_estimate} />}

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
