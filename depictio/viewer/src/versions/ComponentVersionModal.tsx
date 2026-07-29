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
 * Three things can be done from here:
 *
 *   **Travel the data independently** — the version sets a default commit, but
 *   any commit can be chosen against any version's config. "Did the chart
 *   change or did the data?" is two questions; this is how they are separated.
 *   **Compare against current** — the past and present stacked vertically, so
 *   the difference is read rather than remembered across a click.
 *   **Restore just this component** — without reverting the rest of the
 *   dashboard, which is what a full version restore would do.
 *
 * Restore is the only thing here that writes, and it confirms first.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import {
  bulkComputeCards,
  ComponentRenderer,
  DataVersionProvider,
  dataVersionBody,
  fetchDashboardVersion,
  restoreComponentFromVersion,
  type DashboardVersionDetail,
  type DashboardVersionSummary,
  type InteractiveFilter,
  type StoredMetadata,
} from 'depictio-react-core';

import { absDateTime, versionTitle } from './format';
import { pinsForComponent, resolveDataVersion, type DataOverride } from './dataVersionChoice';
import { describeCommit, useDatasetHistories } from './useDatasetHistories';

interface ComponentVersionModalProps {
  opened: boolean;
  onClose: () => void;
  /** The component being compared, as it exists now. */
  metadata: StoredMetadata | null;
  dashboardId: string | null;
  /** Timeline for this dashboard family, newest first. */
  versions: DashboardVersionSummary[];
  loadingVersions?: boolean;
  /** Whether restoring is offered. Time travel is a read, but restore writes,
   *  so it appears only where the caller can edit — the same gate the version
   *  drawer applies to its own restore. */
  canRestore?: boolean;
  /** Called after a component is restored so the host can refetch. */
  onRestored?: () => void;
}

/** Sentinel for "the commit this version recorded". Mantine's Select needs a
 *  string, and an empty value is indistinguishable from nothing selected. */
const VERSION_DEFAULT = '__version__';
/** Sentinel for "today's data", overriding whatever the version recorded. */
const LIVE = '__live__';

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

/**
 * One rendered component, with whatever card value it needs.
 *
 * Extracted because the compare view shows two of these at once, against
 * different configs *and* different data. Sharing one fetch between them would
 * mean the panes could only ever differ in layout.
 */
const VersionedComponent: React.FC<{
  metadata: StoredMetadata;
  dashboardId: string | null;
  index: string;
  pins: Record<string, number | null>;
  /** Height is fixed by the caller rather than left to the content.
   *  Plotly measures its container at mount; inside a modal that is still
   *  animating open, that measurement is zero or near-zero and the figure
   *  keeps the collapsed size until something forces a resize — which is why
   *  the component only looked right *after* switching versions. */
  height: number;
  ready: boolean;
}> = ({ metadata, dashboardId, index, pins, height, ready }) => {
  const isCard = String((metadata as Record<string, unknown>).component_type ?? '') === 'card';

  // A card's value comes from the dashboard's bulk-compute pass, not from the
  // renderer. The modal has no such parent, so without this a card renders as
  // a permanent "…" — the one component type the whole feature is most likely
  // to be used on, since a changed number is what prompts the question.
  const [cardValue, setCardValue] = useState<unknown>(undefined);
  const [cardSecondary, setCardSecondary] = useState<Record<string, unknown>>({});
  const [cardLoading, setCardLoading] = useState(false);
  const pinKey = JSON.stringify(pins);

  useEffect(() => {
    if (!ready || !isCard || !dashboardId || !index) return;
    let cancelled = false;
    setCardLoading(true);
    bulkComputeCards(dashboardId, [], [index], {
      ...dataVersionBody({ pins }),
      // The card's *definition* is versioned too — a changed column or
      // aggregation must be honoured, or the value shown would be today's
      // question asked of yesterday's data.
      component_overrides: { [index]: metadata as Record<string, unknown> },
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, isCard, dashboardId, index, pinKey, metadata]);

  return (
    <DataVersionProvider pins={pins}>
      <Box style={{ height, minHeight: height }}>
        {ready ? (
          <ComponentRenderer
            // Remount per (config, data) pair. The renderers cache by component
            // id, and reusing the instance would show the previous version's
            // figure until the next fetch lands.
            key={`${index}-${pinKey}-${String((metadata as Record<string, unknown>).last_updated ?? '')}`}
            metadata={metadata}
            filters={[] as InteractiveFilter[]}
            dashboardId={dashboardId ?? undefined}
            cardValue={cardValue}
            cardSecondaryValues={cardSecondary}
            cardLoading={cardLoading}
          />
        ) : (
          // Held back one frame rather than rendered into a box that is still
          // sizing. See `height` above.
          <Group justify="center" h={height}>
            <Loader size="sm" />
          </Group>
        )}
      </Box>
    </DataVersionProvider>
  );
};

const ComponentVersionModal: React.FC<ComponentVersionModalProps> = ({
  opened,
  onClose,
  metadata,
  dashboardId,
  versions,
  loadingVersions,
  canRestore = false,
  onRestored,
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
  /** Explicit per-commit override, when the user picks one from the dataset
   *  select. Null means "follow the version", which is the default. */
  const [dataOverride, setDataOverride] = useState<DataOverride>(undefined);
  const [compare, setCompare] = useState(false);
  const [restoreLayout, setRestoreLayout] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [confirmRestore, setConfirmRestore] = useState(false);

  // Mantine's modal animates in, and a figure that measures its container
  // during that animation gets a near-zero height and keeps it. Rendering is
  // held until the transition has ended, which is what makes the component fit
  // on *first* open rather than only after switching versions.
  const [ready, setReady] = useState(false);
  const readyTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!opened) {
      setReady(false);
      if (readyTimer.current) window.clearTimeout(readyTimer.current);
      return;
    }
    readyTimer.current = window.setTimeout(() => setReady(true), 220);
    return () => {
      if (readyTimer.current) window.clearTimeout(readyTimer.current);
    };
  }, [opened]);

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
      setDataOverride(undefined);
      setCompare(false);
      setRestoreLayout(false);
      setConfirmRestore(false);
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

  /** What the selected version recorded, before any manual override. */
  const versionDataVersion = useMemo(() => {
    if (!detail || !dcId) return undefined;
    return pinnedVersionFor(detail, dcId);
  }, [detail, dcId]);

  /** The commit actually being read. Manual choice wins over the version's
   *  own stamp, which is what makes the two axes independent. */
  const dataVersion = useMemo(
    () => resolveDataVersion({ dataOverride, useHistoricalData, versionDataVersion }),
    [dataOverride, useHistoricalData, versionDataVersion],
  );

  // Scoped to this modal only. The dashboard behind it keeps whatever it was
  // showing — the comparison is a lens, not a mode switch.
  const pins = useMemo(() => pinsForComponent(dcId, dataVersion), [dcId, dataVersion]);

  // Commits available for the manual override. Fetched only while the modal is
  // open and the component actually has a collection.
  const { histories } = useDatasetHistories(
    metadata ? [metadata] : undefined,
    opened && Boolean(dcId),
  );
  const history = histories.find((h) => h.dcId === dcId);

  const selected = versions.find((v) => v.version_id === selectedId) || null;
  const dataUnavailable =
    useHistoricalData &&
    dataOverride === undefined &&
    Boolean(detail) &&
    Boolean(dcId) &&
    versionDataVersion === undefined;

  const handleRestore = useCallback(async () => {
    if (!selectedId || !index) return;
    setRestoring(true);
    try {
      const result = await restoreComponentFromVersion(selectedId, index, restoreLayout);
      notifications.show({
        color: 'green',
        title: result.readded ? 'Component restored' : 'Component reverted',
        message: result.readded
          ? 'It had been deleted and is back on the dashboard.'
          : `Restored from ${selected ? versionTitle(selected) : 'the selected version'}. Everything else is untouched.`,
      });
      setConfirmRestore(false);
      onClose();
      onRestored?.();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Restore failed',
        message: (err as Error)?.message || String(err),
      });
    } finally {
      setRestoring(false);
    }
  }, [selectedId, index, restoreLayout, selected, onClose, onRestored]);

  /** Height of one rendered pane. Halved when comparing so both fit without
   *  the modal scrolling, which would defeat a side-by-side read. */
  const paneHeight = compare ? 240 : 320;

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

    const past = (
      <VersionedComponent
        metadata={historical}
        dashboardId={dashboardId}
        index={index}
        pins={pins}
        height={paneHeight}
        ready={ready}
      />
    );

    if (!compare || !metadata) return past;

    // Stacked rather than side by side: these are the same component at two
    // points in time, and a vertical stack keeps both at full width so their
    // axes line up and the difference is the only thing that moves.
    return (
      <Stack gap={4}>
        <Group gap={6}>
          <Badge size="xs" color="yellow" variant="light">
            {selected ? versionTitle(selected) : 'Selected version'}
          </Badge>
          {typeof dataVersion === 'number' && (
            <Text size="xs" c="dimmed">
              data v{dataVersion}
            </Text>
          )}
        </Group>
        <Paper withBorder radius="md" p={4}>
          {past}
        </Paper>

        <Group gap={6} mt={4}>
          <Badge size="xs" color="blue" variant="light">
            Current
          </Badge>
          <Text size="xs" c="dimmed">
            live data
          </Text>
        </Group>
        <Paper withBorder radius="md" p={4}>
          <VersionedComponent
            metadata={metadata}
            dashboardId={dashboardId}
            index={index}
            // Deliberately unpinned: "current" means the component and the data
            // as they are now, which is the thing being compared against.
            pins={{}}
            height={paneHeight}
            ready={ready}
          />
        </Paper>
      </Stack>
    );
  })();

  const dataSelectValue =
    dataOverride === undefined
      ? VERSION_DEFAULT
      : dataOverride === null
        ? LIVE
        : String(dataOverride);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size={compare ? '80rem' : 'xl'}
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
              onChange={(value) => {
                setSelectedId(value);
                // A commit chosen for the previous version is not meaningful
                // against this one; fall back to what this version recorded.
                setDataOverride(undefined);
              }}
              data={versions.map((v) => ({
                value: v.version_id,
                label: v.label ? `v${v.seq} · ${v.label}` : `v${v.seq}`,
              }))}
            />
          </ScrollArea>
        )}

        {selected && (
          <Paper withBorder radius="md" p="xs">
            <Stack gap={8}>
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
                <Group gap="sm" wrap="nowrap">
                  <Switch
                    size="xs"
                    checked={compare}
                    onChange={(e) => setCompare(e.currentTarget.checked)}
                    label="Compare"
                    labelPosition="left"
                    styles={{ label: { whiteSpace: 'nowrap' } }}
                    data-testid="component-version-compare-toggle"
                  />
                  <Switch
                    size="xs"
                    checked={useHistoricalData}
                    onChange={(e) => {
                      setUseHistoricalData(e.currentTarget.checked);
                      // The toggle and the select answer the same question;
                      // leaving a stale override would make the toggle inert.
                      setDataOverride(undefined);
                    }}
                    label="Historical data"
                    labelPosition="left"
                    styles={{ label: { whiteSpace: 'nowrap' } }}
                    data-testid="component-version-data-toggle"
                  />
                </Group>
              </Group>

              {/* Dataset travel, independent of the version. The version sets
                  the default; this overrides it, which is how "same chart,
                  different data" and "different chart, same data" are both
                  reachable. */}
              {dcId && history && history.commits.length > 0 && (
                <Select
                  size="xs"
                  label="Data version"
                  data={[
                    {
                      value: VERSION_DEFAULT,
                      label:
                        typeof versionDataVersion === 'number'
                          ? `This version's data (v${versionDataVersion})`
                          : "This version's data (none recorded)",
                    },
                    {
                      value: LIVE,
                      label:
                        history.currentVersion !== null
                          ? `Current data (v${history.currentVersion})`
                          : 'Current data',
                    },
                    ...history.commits.map((commit) => {
                      const detailText = describeCommit(commit);
                      return {
                        value: String(commit.version),
                        label: `v${commit.version}${detailText ? ` — ${detailText}` : ''}`,
                      };
                    }),
                  ]}
                  value={dataSelectValue}
                  onChange={(value) => {
                    if (!value || value === VERSION_DEFAULT) setDataOverride(undefined);
                    else if (value === LIVE) setDataOverride(null);
                    else setDataOverride(Number(value));
                  }}
                  comboboxProps={{ withinPortal: true }}
                  allowDeselect={false}
                  data-testid="component-version-data-select"
                />
              )}
            </Stack>
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

        {canRestore && historical && (
          <>
            <Divider />
            {confirmRestore ? (
              <Paper withBorder radius="md" p="sm">
                <Stack gap="xs">
                  <Text size="sm">
                    Restore this component as it was in{' '}
                    <strong>{selected ? versionTitle(selected) : 'the selected version'}</strong>?
                  </Text>
                  <Text size="xs" c="dimmed">
                    Only this component changes. Everything else on the dashboard
                    stays as it is, and the current state is saved to history
                    first, so this can be undone.
                  </Text>
                  <Switch
                    size="xs"
                    checked={restoreLayout}
                    onChange={(e) => setRestoreLayout(e.currentTarget.checked)}
                    label="Also restore its position and size"
                  />
                  <Group justify="flex-end" gap="xs">
                    <Button
                      size="xs"
                      variant="subtle"
                      color="gray"
                      onClick={() => setConfirmRestore(false)}
                      disabled={restoring}
                    >
                      Cancel
                    </Button>
                    <Button
                      size="xs"
                      color="orange"
                      loading={restoring}
                      onClick={handleRestore}
                      data-testid="component-version-restore-confirm"
                    >
                      Restore this component
                    </Button>
                  </Group>
                </Stack>
              </Paper>
            ) : (
              <Group justify="flex-end">
                <Tooltip
                  label="Replaces only this component, leaving the rest of the dashboard alone"
                  withArrow
                  position="left"
                >
                  <Button
                    size="xs"
                    variant="light"
                    color="orange"
                    leftSection={<Icon icon="mdi:restore" width={14} />}
                    onClick={() => setConfirmRestore(true)}
                    data-testid="component-version-restore"
                  >
                    Restore this component
                  </Button>
                </Tooltip>
              </Group>
            )}
          </>
        )}
      </Stack>
    </Modal>
  );
};

export default ComponentVersionModal;
