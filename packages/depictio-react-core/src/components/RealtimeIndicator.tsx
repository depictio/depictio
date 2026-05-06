import React, { useState } from 'react';
import {
  ActionIcon,
  Anchor,
  Badge,
  Box,
  Code,
  Divider,
  Group,
  HoverCard,
  Menu,
  ScrollArea,
  Stack,
  Switch,
  Text,
  Tooltip,
  Indicator,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { RealtimeMode, RealtimeStatus } from '../realtime';
import type { RealtimeJournalEntry } from '../hooks/useRealtimeJournal';

interface RealtimeIndicatorProps {
  status: RealtimeStatus;
  mode: RealtimeMode;
  paused: boolean;
  pendingUpdate: boolean;
  onModeChange: (next: RealtimeMode) => void;
  onPausedChange: (next: boolean) => void;
  onAcknowledgePending?: () => void;
  /** Persistent log of captured events (oldest first). Survives reload via
   *  localStorage. Pass ``[]`` to hide the journal section entirely. */
  journal?: RealtimeJournalEntry[];
  /** Wipes the journal — both in-memory state and the localStorage entry. */
  onClearJournal?: () => void;
}

const STATUS_LABELS: Record<RealtimeStatus, string> = {
  connecting: 'Connecting…',
  connected: 'Live',
  disconnected: 'Offline',
};

const STATUS_COLORS: Record<RealtimeStatus, string> = {
  connecting: 'yellow',
  connected: 'teal',
  disconnected: 'gray',
};

/**
 * Status pill + control menu mirroring the disabled Dash plumbing's
 * ``create_live_indicator`` and ``create_realtime_controls``. Shows
 * connection status, an orange dot when an update is pending, and a popover
 * with Manual/Auto toggle and Pause/Resume.
 */
const RealtimeIndicator: React.FC<RealtimeIndicatorProps> = ({
  status,
  mode,
  paused,
  pendingUpdate,
  onModeChange,
  onPausedChange,
  onAcknowledgePending,
  journal,
  onClearJournal,
}) => {
  const [opened, setOpened] = useState(false);
  // Newest first — most recent event is the most interesting.
  const journalNewestFirst = (journal ?? []).slice().reverse();
  const showJournal = journal !== undefined;

  return (
    <Menu opened={opened} onChange={setOpened} position="bottom-end" withinPortal>
      <Menu.Target>
        <Tooltip label={paused ? 'Live updates paused' : STATUS_LABELS[status]} withArrow>
          <ActionIcon
            variant="subtle"
            color={paused ? 'gray' : STATUS_COLORS[status]}
            aria-label="Real-time updates"
          >
            <Indicator
              color="orange"
              size={8}
              processing
              disabled={!pendingUpdate}
              offset={4}
            >
              <Icon
                icon={paused ? 'tabler:plug-connected-x' : 'tabler:plug-connected'}
                width={18}
                height={18}
              />
            </Indicator>
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown miw={240}>
        <Menu.Label>
          <Group justify="space-between" wrap="nowrap">
            <Text size="xs" tt="uppercase" c="dimmed">
              Live updates
            </Text>
            <Badge size="xs" color={STATUS_COLORS[status]} variant="light">
              {STATUS_LABELS[status]}
            </Badge>
          </Group>
        </Menu.Label>
        <Menu.Item closeMenuOnClick={false}>
          <Switch
            checked={mode === 'auto'}
            onChange={(e) => onModeChange(e.currentTarget.checked ? 'auto' : 'manual')}
            label={mode === 'auto' ? 'Auto-refresh on update' : 'Notify on update'}
            size="sm"
          />
        </Menu.Item>
        <Menu.Item closeMenuOnClick={false}>
          <Switch
            checked={paused}
            onChange={(e) => onPausedChange(e.currentTarget.checked)}
            label={paused ? 'Paused' : 'Receiving events'}
            size="sm"
            color="orange"
          />
        </Menu.Item>
        {pendingUpdate && (
          <Menu.Item
            color="orange"
            leftSection={<Icon icon="tabler:refresh" width={14} height={14} />}
            onClick={() => {
              onAcknowledgePending?.();
              setOpened(false);
            }}
          >
            Pending update — click to dismiss
          </Menu.Item>
        )}
        {showJournal && (
          <>
            <Divider my={4} />
            <Menu.Label>
              <Group justify="space-between" wrap="nowrap">
                <Text size="xs" tt="uppercase" c="dimmed">
                  Event log
                </Text>
                <Group gap={6} wrap="nowrap">
                  <Badge size="xs" variant="light" color="gray">
                    {journalNewestFirst.length}
                  </Badge>
                  {onClearJournal && journalNewestFirst.length > 0 && (
                    <Anchor
                      component="button"
                      type="button"
                      size="xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        onClearJournal();
                      }}
                    >
                      Reset
                    </Anchor>
                  )}
                </Group>
              </Group>
            </Menu.Label>
            <Box px="xs" pb="xs">
              {journalNewestFirst.length === 0 ? (
                <Text size="xs" c="dimmed" ta="center" py="xs">
                  No events captured yet.
                </Text>
              ) : (
                <ScrollArea.Autosize mah={220} type="auto" offsetScrollbars>
                  <Stack gap={6}>
                    {journalNewestFirst.map((entry, idx) => (
                      <JournalRow
                        key={`${entry.receivedAt}-${idx}`}
                        entry={entry}
                      />
                    ))}
                  </Stack>
                </ScrollArea.Autosize>
              )}
            </Box>
          </>
        )}
      </Menu.Dropdown>
    </Menu>
  );
};

const JournalRow: React.FC<{ entry: RealtimeJournalEntry }> = ({ entry }) => {
  // The backend's ``_build_event_payload`` packs project / DC tags and a live
  // row-count into ``payload``. Surface the most meaningful fields in the
  // compact row, push everything else into the HoverCard.
  const payload = (entry.payload ?? {}) as Record<string, unknown>;
  const tag =
    typeof payload.data_collection_tag === 'string'
      ? (payload.data_collection_tag as string)
      : undefined;
  const op =
    typeof payload.operation === 'string'
      ? (payload.operation as string)
      : undefined;
  const rowCount =
    typeof payload.row_count === 'number' ? (payload.row_count as number) : undefined;
  const prevRowCount =
    typeof payload.prev_row_count === 'number'
      ? (payload.prev_row_count as number)
      : undefined;
  const rowDelta =
    typeof payload.row_delta === 'number' ? (payload.row_delta as number) : undefined;
  const aggVersion =
    typeof payload.aggregation_version === 'number'
      ? (payload.aggregation_version as number)
      : undefined;
  const deltaVersion =
    typeof payload.delta_version === 'number' ? (payload.delta_version as number) : undefined;
  const idColumn =
    typeof payload.id_column === 'string' ? (payload.id_column as string) : undefined;
  const newIdsSample = Array.isArray(payload.new_ids_sample)
    ? (payload.new_ids_sample as unknown[]).map((v) => String(v))
    : undefined;
  const newIdsTotal =
    typeof payload.new_ids_total === 'number'
      ? (payload.new_ids_total as number)
      : undefined;
  const projectName =
    typeof payload.project_name === 'string' ? (payload.project_name as string) : undefined;
  const workflowTag =
    typeof payload.workflow_tag === 'string' ? (payload.workflow_tag as string) : undefined;
  const dcType =
    typeof payload.data_collection_type === 'string'
      ? (payload.data_collection_type as string)
      : undefined;
  const aggHash =
    typeof payload.aggregation_hash === 'string'
      ? (payload.aggregation_hash as string)
      : undefined;
  const aggTime =
    typeof payload.aggregation_time === 'string'
      ? (payload.aggregation_time as string)
      : undefined;
  const sizeBytes =
    typeof payload.delta_size_bytes === 'number'
      ? (payload.delta_size_bytes as number)
      : undefined;

  const time = (() => {
    try {
      return new Date(entry.receivedAt).toLocaleTimeString();
    } catch {
      return entry.receivedAt;
    }
  })();

  const payloadJson = (() => {
    try {
      return JSON.stringify(payload, null, 2);
    } catch {
      return '<unserialisable>';
    }
  })();

  return (
    <HoverCard
      width={420}
      position="left-start"
      shadow="md"
      withArrow
      openDelay={120}
      closeDelay={80}
      withinPortal
    >
      <HoverCard.Target>
        <Box
          style={{
            borderLeft: `2px solid ${
              rowDelta !== undefined && rowDelta !== 0
                ? rowDelta > 0
                  ? 'var(--mantine-color-teal-5)'
                  : 'var(--mantine-color-orange-5)'
                : 'var(--mantine-color-blue-5)'
            }`,
            paddingLeft: 8,
            cursor: 'help',
          }}
        >
          <Group justify="space-between" wrap="nowrap" gap={6}>
            <Text size="xs" fw={500}>
              {time}
            </Text>
            {/* Prefer row_delta (the actual change) over the absolute row_count.
                Falls back to row_count when there's no prev version (very
                first commit). */}
            {rowDelta !== undefined && rowDelta !== 0 ? (
              <Text
                size="xs"
                fw={600}
                c={rowDelta > 0 ? 'teal.6' : 'orange.6'}
              >
                {rowDelta > 0 ? '+' : ''}
                {rowDelta} {Math.abs(rowDelta) === 1 ? 'row' : 'rows'}
              </Text>
            ) : rowCount !== undefined ? (
              <Text size="xs" fw={500} c="blue.6">
                {rowCount} {rowCount === 1 ? 'row' : 'rows'}
              </Text>
            ) : null}
          </Group>
          <Group gap={6} wrap="nowrap">
            <Text size="xs" c="dimmed" lineClamp={1} style={{ flex: 1, minWidth: 0 }}>
              {tag ? <strong>{tag}</strong> : entry.eventType}
              {op ? ` · ${op}` : ''}
              {aggVersion !== undefined ? ` · v${aggVersion}` : ''}
            </Text>
          </Group>
        </Box>
      </HoverCard.Target>
      <HoverCard.Dropdown p="sm">
        <Stack gap={6}>
          <Group justify="space-between" wrap="nowrap" gap={6}>
            <Badge size="xs" color="blue" variant="light">
              {entry.eventType}
            </Badge>
            <Text size="xs" c="dimmed" ff="monospace">
              {entry.receivedAt}
            </Text>
          </Group>

          {/* Tag → ID rows: human label on top, monospace id underneath. */}
          {(projectName || typeof payload.project_id === 'string') && (
            <TagIdRow
              label="Project"
              tag={projectName}
              id={typeof payload.project_id === 'string' ? (payload.project_id as string) : undefined}
            />
          )}
          {(workflowTag || tag) && (
            <TagIdRow
              label="Workflow / DC"
              tag={
                workflowTag && tag
                  ? `${workflowTag} / ${tag}`
                  : workflowTag || tag
              }
              id={entry.dataCollectionId}
              extra={dcType}
            />
          )}
          {entry.dashboardId && (
            <TagIdRow label="Dashboard" id={entry.dashboardId} />
          )}

          {/* Update content: the headline fields the user actually cares about. */}
          <Divider my={2} />
          {rowDelta !== undefined && rowDelta !== 0 && (
            <Box
              p={6}
              style={{
                backgroundColor:
                  rowDelta > 0
                    ? 'var(--mantine-color-teal-light)'
                    : 'var(--mantine-color-orange-light)',
                borderRadius: 4,
              }}
            >
              <Text size="xs" fw={600}>
                Δ {rowDelta > 0 ? '+' : ''}
                {rowDelta} {Math.abs(rowDelta) === 1 ? 'row' : 'rows'}
                {prevRowCount !== undefined && rowCount !== undefined && (
                  <Text component="span" c="dimmed" fw={400}>
                    {' '}
                    ({prevRowCount} → {rowCount})
                  </Text>
                )}
              </Text>
            </Box>
          )}
          <Group gap="xs" wrap="wrap">
            {rowCount !== undefined && (
              <MetricChip label="rows" value={String(rowCount)} color="blue" />
            )}
            {aggVersion !== undefined && (
              <MetricChip label="version" value={`v${aggVersion}`} color="grape" />
            )}
            {deltaVersion !== undefined && (
              <MetricChip
                label="delta"
                value={`v${deltaVersion}`}
                color="indigo"
              />
            )}
            {sizeBytes !== undefined && (
              <MetricChip label="size" value={formatBytes(sizeBytes)} color="gray" />
            )}
            {op && <MetricChip label="op" value={op} color="teal" />}
          </Group>
          {newIdsSample && newIdsSample.length > 0 && (
            <Box>
              <Text size="xs" c="dimmed">
                New {idColumn ? `${idColumn} values` : 'rows'} (
                {newIdsTotal ?? newIdsSample.length})
              </Text>
              <Group gap={4} wrap="wrap">
                {newIdsSample.map((id) => (
                  <Code key={id} fz="xs">
                    {id}
                  </Code>
                ))}
                {newIdsTotal !== undefined && newIdsTotal > newIdsSample.length && (
                  <Text size="xs" c="dimmed">
                    +{newIdsTotal - newIdsSample.length} more
                  </Text>
                )}
              </Group>
            </Box>
          )}
          {aggTime && (
            <Text size="xs" c="dimmed">
              Aggregated at <Code fz="xs">{aggTime}</Code>
            </Text>
          )}
          {aggHash && (
            <Text size="xs" c="dimmed">
              Hash{' '}
              <Code fz="xs" title={aggHash}>
                {aggHash.slice(0, 12)}…
              </Code>
            </Text>
          )}

          <Divider my={2} />
          <Text size="xs" c="dimmed">
            Raw payload
          </Text>
          <ScrollArea.Autosize mah={180} type="auto" offsetScrollbars>
            <Code
              block
              fz="xs"
              style={{ whiteSpace: 'pre', wordBreak: 'break-word' }}
            >
              {payloadJson}
            </Code>
          </ScrollArea.Autosize>
        </Stack>
      </HoverCard.Dropdown>
    </HoverCard>
  );
};

const TagIdRow: React.FC<{
  label: string;
  tag?: string;
  id?: string;
  extra?: string;
}> = ({ label, tag, id, extra }) => (
  <Box>
    <Group justify="space-between" gap={6} wrap="nowrap">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      {extra && (
        <Text size="xs" c="dimmed" ff="monospace">
          {extra}
        </Text>
      )}
    </Group>
    {tag && (
      <Text size="xs" fw={500}>
        {tag}
      </Text>
    )}
    {id && (
      <Code fz="xs" style={{ wordBreak: 'break-all' }}>
        {id}
      </Code>
    )}
  </Box>
);

const MetricChip: React.FC<{ label: string; value: string; color: string }> = ({
  label,
  value,
  color,
}) => (
  <Badge size="sm" variant="light" color={color}>
    <span style={{ fontWeight: 400, opacity: 0.7 }}>{label} </span>
    <strong>{value}</strong>
  </Badge>
);

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export default RealtimeIndicator;
