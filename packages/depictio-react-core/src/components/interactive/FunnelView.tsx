/**
 * Funnel overview modal (issue #939).
 *
 * Shows the cascading restriction of the applied filters as a whole: the
 * initial row count of every delta-backed data collection, then — for each
 * active filter, in application order — the rows remaining per DC once that
 * filter (and every one before it) is applied. Each stage renders one
 * Progress bar per DC, scaled against that DC's initial row count, so the
 * "funnel" narrows visually from top to bottom.
 *
 * Data comes from `POST /dashboards/funnel_values/{id}` with
 * `include_stages: true`; it is fetched when the modal opens and refetched
 * when the filter state changes while open. Colors are Mantine theme tokens.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Center,
  Divider,
  Group,
  Loader,
  Modal,
  Progress,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  fetchFunnelValues,
  FunnelStage,
  FunnelValuesResponse,
  InteractiveFilter,
} from '../../api';

const formatValue = (value: unknown): string => {
  if (Array.isArray(value)) return value.map(String).join(', ');
  if (value === null || value === undefined) return '';
  return String(value);
};

const DcRow: React.FC<{
  label: string;
  rows: number | null;
  initial: number | null;
}> = ({ label, rows, initial }) => {
  const pct =
    rows !== null && initial !== null && initial > 0 ? (rows / initial) * 100 : null;
  return (
    <Group gap="sm" wrap="nowrap" align="center">
      <Text size="xs" c="dimmed" style={{ width: 140, flexShrink: 0 }} truncate>
        {label}
      </Text>
      <Box style={{ flex: 1 }}>
        {pct === null ? (
          <Text size="xs" c="dimmed">
            n/a
          </Text>
        ) : (
          <Tooltip label={`${rows} of ${initial} rows remain`} withArrow>
            <Progress
              value={pct}
              size="lg"
              radius="sm"
              color={rows === 0 ? 'orange' : 'teal'}
              aria-label={`${label}: ${rows} of ${initial} rows`}
            />
          </Tooltip>
        )}
      </Box>
      <Text
        size="xs"
        fw={600}
        c={rows === 0 ? 'orange' : undefined}
        style={{ width: 90, textAlign: 'right', flexShrink: 0 }}
      >
        {rows === null ? '—' : `${rows} rows`}
      </Text>
    </Group>
  );
};

const StageBlock: React.FC<{
  stage: FunnelStage;
  position: number;
  initialRows: Record<string, number | null>;
  dcLabels: Record<string, string>;
}> = ({ stage, position, initialRows, dcLabels }) => {
  const dcIds = Object.keys(stage.rows_by_dc);
  return (
    <Stack gap={6}>
      <Group gap="xs" wrap="nowrap">
        <Badge size="sm" variant="filled" color="teal" circle>
          {position}
        </Badge>
        <Text size="sm" fw={600} truncate>
          {stage.label || stage.column_name || stage.index}
        </Text>
        <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>
          {formatValue(stage.value)}
        </Text>
      </Group>
      <Stack gap={4} pl="xl">
        {dcIds.map((dc) => (
          <DcRow
            key={dc}
            label={dcLabels[dc] || dc.slice(0, 8)}
            rows={stage.rows_by_dc[dc]}
            initial={initialRows[dc] ?? null}
          />
        ))}
      </Stack>
    </Stack>
  );
};

export interface FunnelViewProps {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  /** The shell's (debounced) filter list — the same one the components use. */
  filters: InteractiveFilter[];
}

const FunnelView: React.FC<FunnelViewProps> = ({ opened, onClose, dashboardId, filters }) => {
  const [data, setData] = useState<FunnelValuesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filterKey = useMemo(() => JSON.stringify(filters), [filters]);

  useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchFunnelValues(dashboardId, filters, [], true, controller.signal)
      .then((res) => setData(res))
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // filterKey stands in for the filters array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, dashboardId, filterKey]);

  const initialRows = data?.initial_rows_by_dc ?? {};
  const stages = data?.stages ?? [];
  const dcLabels = data?.dc_labels ?? {};
  const initialDcIds = Object.keys(initialRows);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="lg"
      title={
        <Group gap="xs">
          <Icon icon="mdi:chart-sankey" width={18} height={18} />
          <Text fw={600}>Filter funnel</Text>
        </Group>
      }
    >
      {loading && (
        <Center py="xl">
          <Loader size="sm" />
        </Center>
      )}
      {!loading && error && (
        <Alert color="orange" title="Funnel unavailable">
          {error}
        </Alert>
      )}
      {!loading && !error && data && (
        <Stack gap="md">
          {stages.length === 0 ? (
            <Text size="sm" c="dimmed">
              No active filters — apply a filter to see how it narrows the data.
            </Text>
          ) : (
            <>
              <Stack gap={6}>
                <Group gap="xs" wrap="nowrap">
                  <Badge size="sm" variant="light" color="gray" circle>
                    0
                  </Badge>
                  <Text size="sm" fw={600}>
                    Unfiltered
                  </Text>
                </Group>
                <Stack gap={4} pl="xl">
                  {initialDcIds.map((dc) => (
                    <DcRow
                      key={dc}
                      label={dcLabels[dc] || dc.slice(0, 8)}
                      rows={initialRows[dc]}
                      initial={initialRows[dc]}
                    />
                  ))}
                </Stack>
              </Stack>
              <Divider
                label="filters applied in order"
                labelPosition="center"
              />
              {stages.map((stage, i) => (
                <StageBlock
                  key={`${stage.index ?? i}`}
                  stage={stage}
                  position={i + 1}
                  initialRows={initialRows}
                  dcLabels={dcLabels}
                />
              ))}
              <Text size="xs" c="dimmed">
                Row counts cover delta-backed data collections; cross-DC
                filters are translated through the project's links. MultiQC
                collections have no row table and are not charted here.
              </Text>
            </>
          )}
        </Stack>
      )}
    </Modal>
  );
};

export default FunnelView;
