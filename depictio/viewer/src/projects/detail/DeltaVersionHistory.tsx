/**
 * Commit history of a data collection's Delta table.
 *
 * Delta has always versioned every write; nothing ever showed it. The question
 * this answers is "did the data I am looking at change, when, and because of
 * what" — which until now could only be answered by reading `_delta_log` by
 * hand.
 *
 * Collapsed by default and fetched on first open (same pattern as DcFileList):
 * the history read touches the object store, so it should not happen for every
 * collection a user merely clicks through.
 */

import React, { useCallback, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Center,
  Code,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDeltaHistory, type DeltaHistoryResponse, type DeltaVersionEntry } from 'depictio-react-core';

import { absTime, compactCount, parseTs, relTime } from '../../monitoring/format';
import { TriggerBadge } from '../../monitoring/TriggerBadge';

/** Delta operation names are verbose ("WRITE", "DELETE", "OPTIMIZE"); show them
 *  as a compact chip with a per-operation colour so a vacuum or an optimize
 *  stands out from an ordinary write. */
const OPERATION_COLOR: Record<string, string> = {
  WRITE: 'blue',
  DELETE: 'red',
  OPTIMIZE: 'grape',
  VACUUM: 'orange',
  'VACUUM START': 'orange',
  'VACUUM END': 'orange',
  RESTORE: 'yellow',
  MERGE: 'teal',
};

/** Write mode as recorded by depictio's own commit metadata, when present. */
const WRITE_MODE_LABEL: Record<string, string> = {
  overwrite: 'full rewrite',
  append: 'appended',
  'replace-runs': 'runs replaced',
};

function timestampOf(entry: DeltaVersionEntry): string | null | undefined {
  return entry.timestamp ?? entry.aggregation_time;
}

const VersionRow: React.FC<{ entry: DeltaVersionEntry; isCurrent: boolean }> = ({
  entry,
  isCurrent,
}) => {
  const meta = entry.metadata || {};
  const writeMode = entry.write_mode || meta['depictio.write_mode'];
  const trigger = entry.trigger || meta['depictio.trigger'];
  const runTags = meta['depictio.run_tags'];
  const ts = timestampOf(entry);
  const operation = entry.operation || '—';

  return (
    <Table.Tr>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          {entry.version != null ? (
            <Badge size="sm" variant={isCurrent ? 'filled' : 'light'} color="green">
              v{entry.version}
            </Badge>
          ) : (
            <Tooltip
              label="Recorded by depictio before Delta versions were captured, so it cannot be matched to a commit."
              multiline
              w={260}
              withArrow
              withinPortal
            >
              <Badge size="sm" variant="outline" color="gray">
                —
              </Badge>
            </Tooltip>
          )}
          {isCurrent && (
            <Text size="xs" c="dimmed">
              current
            </Text>
          )}
        </Group>
      </Table.Td>
      <Table.Td>
        {ts ? (
          <Tooltip label={absTime(ts)} withArrow withinPortal>
            <Text size="xs">{relTime(ts)}</Text>
          </Tooltip>
        ) : (
          <Text size="xs" c="dimmed">
            —
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          <Badge size="xs" variant="light" color={OPERATION_COLOR[operation] ?? 'gray'}>
            {operation}
          </Badge>
          {writeMode && (
            <Tooltip
              label={runTags ? `Runs: ${runTags}` : 'How depictio wrote this commit'}
              withArrow
              withinPortal
              multiline
              maw={420}
            >
              <Text size="xs" c="dimmed">
                {WRITE_MODE_LABEL[writeMode] ?? writeMode}
              </Text>
            </Tooltip>
          )}
        </Group>
      </Table.Td>
      <Table.Td>
        <Text size="xs" ff="monospace">
          {entry.rows_added != null ? `+${compactCount(entry.rows_added)}` : '—'}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="xs" ff="monospace">
          {entry.files_added != null ? `+${compactCount(entry.files_added)}` : '—'}
          {entry.files_removed ? (
            <Text component="span" size="xs" c="dimmed">
              {' '}
              −{compactCount(entry.files_removed)}
            </Text>
          ) : null}
        </Text>
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          {trigger && <TriggerBadge trigger={trigger} />}
          {entry.by_email && (
            <Text size="xs" c="dimmed" truncate maw={180}>
              {entry.by_email}
            </Text>
          )}
          {!trigger && !entry.by_email && (
            <Text size="xs" c="dimmed">
              —
            </Text>
          )}
        </Group>
      </Table.Td>
    </Table.Tr>
  );
};

export const DeltaVersionHistory: React.FC<{ dcId: string }> = ({ dcId }) => {
  const [history, setHistory] = useState<DeltaHistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    // Fetched once per mount: the history only changes when someone ingests,
    // and the panel is not the surface for watching that happen live.
    if (history || loading) return;
    setLoading(true);
    setError(null);
    try {
      setHistory(await fetchDeltaHistory(dcId, 20));
    } catch (err) {
      setError((err as Error).message || 'Failed to load Delta history.');
    } finally {
      setLoading(false);
    }
  }, [dcId, history, loading]);

  const versions = history?.versions ?? [];
  // Sort defensively: the merged response appends Mongo-only rows after the
  // Delta ones, so it is not globally ordered by time.
  const ordered = [...versions].sort((a, b) => {
    const ta = parseTs(timestampOf(a));
    const tb = parseTs(timestampOf(b));
    if (Number.isNaN(ta) && Number.isNaN(tb)) return (b.version ?? -1) - (a.version ?? -1);
    if (Number.isNaN(ta)) return 1;
    if (Number.isNaN(tb)) return -1;
    return tb - ta;
  });

  return (
    <Accordion variant="separated" radius="md" onChange={(v) => v === 'history' && load()}>
      <Accordion.Item value="history">
        <Accordion.Control
          icon={<Icon icon="mdi:history" width={18} color="var(--mantine-color-green-6)" />}
        >
          <Group gap={8}>
            <Text fw={600}>Version history</Text>
            {history && (
              <Text size="xs" c="dimmed">
                {versions.length} commit{versions.length === 1 ? '' : 's'}
              </Text>
            )}
          </Group>
        </Accordion.Control>
        <Accordion.Panel>
          {loading && (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          )}
          {error && (
            <Alert color="red" variant="light" icon={<Icon icon="mdi:alert" width={16} />}>
              {error}
            </Alert>
          )}
          {history && !loading && !error && (
            <Stack gap="xs">
              {history.degraded && (
                <Alert
                  color="yellow"
                  variant="light"
                  icon={<Icon icon="mdi:cloud-off-outline" width={16} />}
                >
                  The object store could not be reached, so this shows only what depictio
                  recorded — commits written outside depictio are missing.
                </Alert>
              )}
              {ordered.length === 0 ? (
                <Text size="sm" c="dimmed">
                  No commits recorded yet.
                </Text>
              ) : (
                <Table.ScrollContainer minWidth={620}>
                  <Table verticalSpacing="xs" striped highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Version</Table.Th>
                        <Table.Th>When</Table.Th>
                        <Table.Th>Operation</Table.Th>
                        <Table.Th>Rows</Table.Th>
                        <Table.Th>Files</Table.Th>
                        <Table.Th>By</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {ordered.map((entry, index) => (
                        <VersionRow
                          key={`${entry.version ?? 'mongo'}-${entry.aggregation_version ?? index}`}
                          entry={entry}
                          isCurrent={
                            entry.version != null && entry.version === history.current_version
                          }
                        />
                      ))}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
              )}
              <Code style={{ fontSize: 11, overflowWrap: 'anywhere' }}>
                {history.delta_table_location}
              </Code>
            </Stack>
          )}
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
};
