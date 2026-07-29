/**
 * One component, seen at every version of the dashboard it lives on.
 *
 * The version drawer answers "what did the *dashboard* look like?". Often the
 * real question is narrower: this chart moved, or its numbers changed, and you
 * want to see just it across time without restoring anything or opening five
 * preview tabs.
 *
 * Two things vary between versions, and both are honoured:
 *
 *   **the component** — its config as stored in that version's snapshot, so a
 *   changed column, aggregation or visualisation type shows up;
 *   **its data** — pinned to the Delta commit that version recorded, so the
 *   numbers are the ones that were on screen at the time.
 *
 * Pinning only the layout would be the more obvious build and the more
 * misleading result: an old chart definition drawn over today's data is a view
 * that never existed.
 *
 * Read-only throughout. Nothing here writes, and the pin is scoped to the
 * modal — closing it leaves the dashboard behind exactly as it was.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Switch,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  bulkComputeCards,
  ComponentRenderer,
  DataVersionProvider,
  dataVersionBody,
  fetchDashboardVersion,
  type DashboardVersionDetail,
  type DashboardVersionSummary,
  type InteractiveFilter,
  type StoredMetadata,
} from 'depictio-react-core';

import { absDateTime, versionTitle } from './format';

interface ComponentVersionModalProps {
  opened: boolean;
  onClose: () => void;
  /** The component being compared, as it exists now. */
  metadata: StoredMetadata | null;
  dashboardId: string | null;
  /** Timeline for this dashboard family, newest first. */
  versions: DashboardVersionSummary[];
  loadingVersions?: boolean;
}

/** The component's own id — the handle used to find it in each snapshot. */
function componentIndex(metadata: StoredMetadata | null): string {
  return metadata ? String((metadata as Record<string, unknown>).index ?? '') : '';
}

/** Find this component inside a stored version, across every tab.
 *
 * Returns null when the version predates the component, which is a normal
 * outcome worth stating rather than an error: it is exactly the answer to
 * "when did this first appear?". */
function componentInVersion(
  version: DashboardVersionDetail,
  index: string,
): StoredMetadata | null {
  for (const tab of version.tabs || []) {
    for (const component of tab.stored_metadata || []) {
      const candidate = component as Record<string, unknown>;
      if (String(candidate.index ?? '') === index) return component as StoredMetadata;
    }
  }
  return null;
}

/** The Delta commit this version recorded for the component's collection.
 *  `undefined` when the collection had no recorded provenance, which the UI
 *  reports rather than silently drawing live data. */
function pinnedVersionFor(
  version: DashboardVersionDetail,
  dcId: string,
): number | undefined {
  for (const stamp of version.data_collections || []) {
    if (String(stamp.dc_id) !== dcId) continue;
    if (stamp.version_kind === 'delta' && typeof stamp.delta_version === 'number') {
      return stamp.delta_version;
    }
    return undefined;
  }
  return undefined;
}

const ComponentVersionModal: React.FC<ComponentVersionModalProps> = ({
  opened,
  onClose,
  metadata,
  dashboardId,
  versions,
  loadingVersions,
}) => {
  const index = componentIndex(metadata);
  const dcId = metadata
    ? String((metadata as Record<string, unknown>).dc_id ?? '')
    : '';

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DashboardVersionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // On by default: the point of the comparison is the view as it *was*.
  // Switchable off to isolate the other axis — "did the chart change, or did
  // the data?" is two questions, and this separates them.
  const [useHistoricalData, setUseHistoricalData] = useState(true);

  // Default to the newest version so the modal opens on something rather than
  // an empty pane.
  useEffect(() => {
    if (!opened) return;
    if (selectedId || versions.length === 0) return;
    setSelectedId(versions[0].version_id);
  }, [opened, versions, selectedId]);

  // Reset between components: leaving the previous component's version
  // selected would show the wrong thing for a moment on reopen.
  useEffect(() => {
    if (!opened) {
      setSelectedId(null);
      setDetail(null);
      setError(null);
    }
  }, [opened]);

  useEffect(() => {
    if (!opened || !selectedId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchDashboardVersion(selectedId)
      .then((res) => {
        if (!cancelled) setDetail(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [opened, selectedId]);

  const historical = useMemo(
    () => (detail && index ? componentInVersion(detail, index) : null),
    [detail, index],
  );

  const dataVersion = useMemo(() => {
    if (!detail || !dcId || !useHistoricalData) return undefined;
    return pinnedVersionFor(detail, dcId);
  }, [detail, dcId, useHistoricalData]);

  // Scoped to this modal only. The dashboard behind it keeps whatever it was
  // showing — the comparison is a lens, not a mode switch.
  const pins = useMemo(
    () => (dcId && typeof dataVersion === 'number' ? { [dcId]: dataVersion } : {}),
    [dcId, dataVersion],
  );

  // A card's value comes from the dashboard's bulk-compute pass, not from the
  // renderer. The modal has no such parent, so without this a card renders as
  // a permanent "…" — the one component type the whole feature is most likely
  // to be used on, since a changed number is what prompts the question.
  const [cardValue, setCardValue] = useState<unknown>(undefined);
  const [cardSecondary, setCardSecondary] = useState<Record<string, unknown>>({});
  const [cardLoading, setCardLoading] = useState(false);
  const isCard =
    String((historical as Record<string, unknown> | null)?.component_type ?? '') === 'card';

  useEffect(() => {
    if (!opened || !isCard || !dashboardId || !index) return;
    let cancelled = false;
    setCardLoading(true);
    bulkComputeCards(dashboardId, [], [index], {
      ...dataVersionBody({ pins }),
      // The card's *definition* is versioned too — a changed column or
      // aggregation must be honoured, or the value shown would be today's
      // question asked of yesterday's data.
      component_overrides: { [index]: historical as Record<string, unknown> },
    })
      .then((res) => {
        if (cancelled) return;
        setCardValue(res.values?.[index]);
        setCardSecondary((res.secondary_values?.[index] as Record<string, unknown>) || {});
      })
      .catch(() => {
        if (!cancelled) setCardValue(undefined);
      })
      .finally(() => {
        if (!cancelled) setCardLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // `pins` is content-stable via useMemo; stringified so a same-shaped
    // object doesn't re-trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, isCard, dashboardId, index, JSON.stringify(pins), historical]);

  const selected = versions.find((v) => v.version_id === selectedId) || null;
  const dataUnavailable =
    useHistoricalData && Boolean(detail) && Boolean(dcId) && dataVersion === undefined;

  const body = (() => {
    if (loadingVersions || (loading && !detail)) {
      return (
        <Group justify="center" py="xl">
          <Loader size="sm" />
        </Group>
      );
    }
    if (versions.length === 0) {
      return (
        <Alert color="gray" variant="light" icon={<Icon icon="mdi:history" width={16} />}>
          No versions recorded yet. One is written the next time this dashboard is
          saved.
        </Alert>
      );
    }
    if (error) {
      return (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" width={16} />}>
          {error}
        </Alert>
      );
    }
    if (!historical) {
      return (
        <Alert color="gray" variant="light" icon={<Icon icon="mdi:eye-off-outline" width={16} />}>
          This component did not exist in {selected ? versionTitle(selected) : 'this version'}.
          It was added later.
        </Alert>
      );
    }

    return (
      <DataVersionProvider pins={pins}>
        <Box style={{ minHeight: 260 }}>
          <ComponentRenderer
            // Remount per (version, data) pair. The renderers cache by
            // component id, and reusing the instance across versions would
            // show the previous version's figure until the next fetch lands.
            key={`${selectedId}-${dataVersion ?? 'live'}`}
            metadata={historical}
            filters={[] as InteractiveFilter[]}
            dashboardId={dashboardId ?? undefined}
            cardValue={cardValue}
            cardSecondaryValues={cardSecondary}
            cardLoading={cardLoading}
          />
        </Box>
      </DataVersionProvider>
    );
  })();

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={
        <Group gap={8}>
          <Icon icon="mdi:compare-horizontal" width={18} />
          <Text fw={600}>Component history</Text>
          {metadata?.title && (
            <Text size="sm" c="dimmed" truncate>
              {String(metadata.title)}
            </Text>
          )}
        </Group>
      }
      data-testid="component-version-modal"
    >
      <Stack gap="sm">
        {versions.length > 0 && (
          <ScrollArea type="hover" scrollbarSize={6} offsetScrollbars>
            <SegmentedControl
              size="xs"
              value={selectedId ?? ''}
              onChange={setSelectedId}
              data={versions.map((v) => ({
                value: v.version_id,
                label: `v${v.seq}`,
              }))}
            />
          </ScrollArea>
        )}

        {selected && (
          <Paper withBorder radius="md" p="xs">
            <Group justify="space-between" wrap="nowrap" gap="sm">
              <Stack gap={2} style={{ minWidth: 0 }}>
                <Text size="sm" fw={600} truncate>
                  {versionTitle(selected)}
                </Text>
                <Group gap={6} wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    {absDateTime(selected.created_at)}
                  </Text>
                  {typeof dataVersion === 'number' && (
                    <Badge size="xs" color="yellow" variant="light">
                      data v{dataVersion}
                    </Badge>
                  )}
                </Group>
              </Stack>
              <Switch
                size="xs"
                checked={useHistoricalData}
                onChange={(e) => setUseHistoricalData(e.currentTarget.checked)}
                label="Historical data"
                labelPosition="left"
                styles={{ label: { whiteSpace: 'nowrap' } }}
                data-testid="component-version-data-toggle"
              />
            </Group>
          </Paper>
        )}

        {dataUnavailable && (
          <Alert color="yellow" variant="light" icon={<Icon icon="mdi:alert" width={16} />}>
            This version recorded no dataset version for the component's data
            collection, so the component below is drawn from{' '}
            <strong>current data</strong>. Its layout and configuration are from
            the selected version.
          </Alert>
        )}

        {body}
      </Stack>
    </Modal>
  );
};

export default ComponentVersionModal;
