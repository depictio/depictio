/**
 * "Before | Now" for one component (#1397): the same tile drawn twice, as the
 * reader last saw it and as it is, with the keys that changed listed below.
 *
 * Read-only. Each pane sits in its own `DataVersionProvider` and an empty
 * change-marks context (no dot, no overlay inside the panes), and nothing here
 * writes or moves a pin on the page itself. It never mounts the editor's
 * version history components: a link to History is a URL (`historyHref`).
 *
 * Before = the earlier dashboard version's definition plus the Delta commit the
 * diff compared from (see `beforePane` for the cases where that is a guess).
 * Now = the live document at the latest data.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Anchor, Box, Group, Loader, Modal, Paper, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import {
  bulkComputeCards,
  ChangeMarksProviderBase,
  ComponentRenderer,
  DataVersionProvider,
  DiffSummaryChip,
  EMPTY_CHANGE_MARKS,
  dataVersionBody,
  useBrandScopeAttributes,
  useComponentDiff,
  Z_LAYERS,
} from 'depictio-react-core';
import type { DataVersionState, InteractiveFilter, StoredMetadata } from 'depictio-react-core';

import { beforePane, diffTables, NOW_STATE, type DiffTableSection } from './compare';
import { historyHref } from './describe';

const PANE_HEIGHT = 360;
/** Mantine's modal transition is 200 ms. */
const ENTER_MS = 250;
const NARROW_QUERY = '(max-width: 40em)';

interface Props {
  opened: boolean;
  onClose: () => void;
  /** The component as it is now. */
  metadata: StoredMetadata | null;
  /** The tab on screen. */
  dashboardId: string | null;
  filters: InteractiveFilter[];
  /** The dashboard version the reader's baseline saw. */
  baselineVersionId: string | null;
  canEdit: boolean;
}

const record = (m: StoredMetadata | null): Record<string, unknown> => (m ?? {}) as Record<string, unknown>;

/**
 * One pane: the component rendered under a version state. A card's value is
 * fetched here (the dashboard's bulk pass is not around the modal).
 */
const ComparePane: React.FC<{
  metadata: StoredMetadata;
  dashboardId: string | null;
  filters: InteractiveFilter[];
  state: DataVersionState;
  ready: boolean;
  testId: string;
}> = ({ metadata, dashboardId, filters, state, ready, testId }) => {
  const index = String(record(metadata).index ?? '');
  const isCard = record(metadata).component_type === 'card';
  const stateKey = JSON.stringify(state);
  const filtersKey = JSON.stringify(filters);
  const [value, setValue] = useState<unknown>(undefined);
  const [secondary, setSecondary] = useState<Record<string, unknown>>({});
  const [cardLoading, setCardLoading] = useState(false);

  useEffect(() => {
    if (!ready || !isCard || !dashboardId || !index) return;
    let cancelled = false;
    setCardLoading(true);
    bulkComputeCards(
      dashboardId,
      filters,
      [index],
      undefined,
      undefined,
      dataVersionBody(state),
    )
      .then((res) => {
        if (cancelled) return;
        setValue(res.values?.[index]);
        setSecondary((res.secondary_values?.[index] as Record<string, unknown>) || {});
      })
      .catch(() => {
        if (!cancelled) setValue(undefined);
      })
      .finally(() => {
        if (!cancelled) setCardLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, isCard, dashboardId, index, stateKey, filtersKey]);

  return (
    <Box style={{ height: PANE_HEIGHT, minHeight: PANE_HEIGHT }} data-testid={testId}>
      {ready ? (
        // The panes are read-only views: no marks, no dot, no overlay inside.
        <ChangeMarksProviderBase value={EMPTY_CHANGE_MARKS}>
          <DataVersionProvider {...state} dashboardId={dashboardId}>
            <ComponentRenderer
              // Renderers cache by component id: remount per version state.
              key={`${index}-${stateKey}`}
              metadata={metadata}
              filters={filters}
              dashboardId={dashboardId ?? undefined}
              cardValue={value}
              cardSecondaryValues={secondary}
              cardLoading={cardLoading}
            />
          </DataVersionProvider>
        </ChangeMarksProviderBase>
      ) : (
        <Group justify="center" h={PANE_HEIGHT}>
          <Loader size="sm" />
        </Group>
      )}
    </Box>
  );
};

const PaneHeading: React.FC<{ label: string; note?: string }> = ({ label, note }) => (
  <Stack gap={0}>
    <Text fw={600} size="sm">
      {label}
    </Text>
    {note && (
      <Text size="xs" c="dimmed">
        {note}
      </Text>
    )}
  </Stack>
);

const DiffTable: React.FC<{ section: DiffTableSection }> = ({ section }) => (
  <Stack gap={4} data-testid={`compare-table-${section.id}`}>
    <Text size="xs" fw={600} c="dimmed" tt="uppercase">
      {section.title} ({section.rows.length + section.more})
    </Text>
    <Box style={{ overflowX: 'auto' }}>
      <Table withTableBorder withColumnBorders fz="xs" verticalSpacing={2} horizontalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            {section.columns.map((c, i) => (
              <Table.Th key={`${c}-${i}`}>{c}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {section.rows.map((row, r) => (
            <Table.Tr key={r}>
              {row.map((cell, c) => (
                <Table.Td key={c}>{cell}</Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Box>
    {section.more > 0 && (
      <Text size="xs" c="dimmed">
        and {section.more} more
      </Text>
    )}
  </Stack>
);

const CompareModal: React.FC<Props> = ({
  opened,
  onClose,
  metadata,
  dashboardId,
  filters,
  baselineVersionId,
  canEdit,
}) => {
  const brandScope = useBrandScopeAttributes();
  const narrow = useMediaQuery(NARROW_QUERY, false, { getInitialValueInEffect: false });
  const index = String(record(metadata).index ?? '');
  const componentType = record(metadata).component_type as string | undefined;
  const dcId = record(metadata).dc_id ? String(record(metadata).dc_id) : null;

  // Plotly measures its box at mount: render once the enter transition is over.
  // A timer, not `onEnterTransitionEnd`: the modal is mounted already open, so
  // no enter transition runs and that callback never fires.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!opened) {
      setReady(false);
      return undefined;
    }
    const timer = window.setTimeout(() => setReady(true), ENTER_MS);
    return () => window.clearTimeout(timer);
  }, [opened]);

  const diffState = useComponentDiff({
    dashboardId: dashboardId ?? undefined,
    componentId: index,
    comparing: opened && Boolean(metadata),
    filters: filters as unknown[],
  });
  const { diff, loading, error } = diffState;
  const decided = Boolean(diff) || Boolean(error);

  const before = useMemo(
    () => beforePane(componentType, dcId, diff, baselineVersionId),
    [componentType, dcId, diff, baselineVersionId],
  );
  const tables = useMemo(() => diffTables(diff), [diff]);

  const title = metadata?.title ? String(metadata.title) : '';
  const href =
    baselineVersionId && dashboardId
      ? historyHref({ version_id: baselineVersionId, tab_id: dashboardId, kind: 'component_edited' }, dashboardId, canEdit)
      : null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="80rem"
      fullScreen={narrow}
      zIndex={Z_LAYERS.overlay}
      // Portaled to <body>: put back inside the dashboard's brand scope.
      className={brandScope?.className}
      data-mantine-color-scheme={brandScope?.['data-mantine-color-scheme']}
      title={
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          <Icon icon="mdi:view-split-vertical" width={18} aria-hidden />
          <Text fw={600}>Before | Now</Text>
          {title && (
            <Text size="sm" c="dimmed" truncate>
              {title}
            </Text>
          )}
        </Group>
      }
      data-testid="compare-modal"
    >
      {metadata && (
        <Stack gap="sm">
          {diff?.definition_changed && (
            <Alert color="blue" variant="light" py={6} data-testid="compare-definition-changed">
              This component was edited since your last visit. The Before pane shows the earlier definition.
            </Alert>
          )}
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            <Stack gap={6}>
              <PaneHeading
                label="Before (your last visit)"
                note={before.kind === 'render' ? before.note : undefined}
              />
              <Paper withBorder radius="md" p="xs">
                {before.kind === 'unavailable' ? (
                  <Stack justify="center" align="center" h={PANE_HEIGHT} data-testid="compare-before-unavailable">
                    <Text size="sm" c="dimmed" ta="center" maw={420}>
                      {before.note}
                    </Text>
                  </Stack>
                ) : decided ? (
                  <ComparePane
                    metadata={metadata}
                    dashboardId={dashboardId}
                    filters={filters}
                    state={before.state}
                    ready={ready}
                    testId="compare-before"
                  />
                ) : (
                  <Group justify="center" h={PANE_HEIGHT}>
                    <Loader size="sm" />
                  </Group>
                )}
              </Paper>
            </Stack>
            <Stack gap={6}>
              <PaneHeading label="Now" />
              <Paper withBorder radius="md" p="xs">
                <ComparePane
                  metadata={metadata}
                  dashboardId={dashboardId}
                  filters={filters}
                  state={NOW_STATE}
                  ready={ready}
                  testId="compare-now"
                />
              </Paper>
            </Stack>
          </SimpleGrid>

          <Group gap="sm" justify="space-between" wrap="wrap">
            <DiffSummaryChip diff={diff} loading={loading} error={error} always />
            {href && (
              <Anchor href={href} size="sm" data-testid="compare-open-history">
                <Group gap={4} wrap="nowrap">
                  <Icon icon="mdi:history" width={14} aria-hidden />
                  Open in History
                </Group>
              </Anchor>
            )}
          </Group>

          {tables.length > 0 && (
            <SimpleGrid cols={{ base: 1, md: tables.length > 1 ? 2 : 1 }} spacing="md" data-testid="compare-tables">
              {tables.map((section) => (
                <DiffTable key={section.id} section={section} />
              ))}
            </SimpleGrid>
          )}
        </Stack>
      )}
    </Modal>
  );
};

export default CompareModal;
