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
 *   **Compare against current** — the past and the present side by side
 *   (stacked on a narrow screen), so the difference is read rather than
 *   remembered across a click.
 *   **Restore just this component** — without reverting the rest of the
 *   dashboard, which is what a full version restore would do.
 *
 * Restore is the only thing here that writes, and it confirms first.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import {
  bulkComputeCards,
  ComponentRenderer,
  DataVersionProvider,
  dataVersionBody,
  EDIT_MENU_STYLE,
  fetchDashboardVersion,
  renderDefinitionKey,
  restoreComponentFromVersion,
  useBrandScopeAttributes,
  Z_LAYERS,
  type DashboardVersionDetail,
  type DashboardVersionSummary,
  type InteractiveFilter,
  type StoredMetadata,
} from 'depictio-react-core';

import { absDateTime, kindMeta, versionTitle } from './format';
import {
  buildDataVersionOptions,
  componentInVersion,
  dataOverrideToValue,
  paneRequest,
  resolveDataVersion,
  valueToDataOverride,
  type DataOverride,
  type PaneRequest,
} from './dataVersionChoice';
import { useDatasetHistories, type DatasetHistory } from './useDatasetHistories';

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

/** Below this the modal takes the whole screen: two panes and their pickers
 *  do not fit a phone-sized dialog with margins around it. */
const NARROW_QUERY = '(max-width: 40em)';

/** Dropdowns raised from inside the modal have to clear its layer, or they
 *  open behind the dialog that raised them. */
const COMBOBOX_PROPS = { withinPortal: true, zIndex: Z_LAYERS.tooltip } as const;

/** The component's own id — the handle used to find it in each snapshot. */
function componentIndex(metadata: StoredMetadata | null): string {
  return metadata ? String((metadata as Record<string, unknown>).index ?? '') : '';
}

/** The Delta commit this version recorded for the component's collection.
 *  `undefined` when the collection had no recorded provenance, which the UI
 *  reports rather than silently drawing live data. */
function pinnedVersionFor(
  version: DashboardVersionDetail,
  dcId: string,
): number | undefined {
  const stamp = (version.data_collections || []).find(
    (candidate) => String(candidate.dc_id) === dcId,
  );
  if (stamp?.version_kind === 'delta' && typeof stamp.delta_version === 'number') {
    return stamp.delta_version;
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
  /** Which data, and which version's definition (null for the live one). */
  request: PaneRequest;
  /** Height is fixed by the caller rather than left to the content.
   *  Plotly measures its container at mount; inside a modal that is still
   *  animating open, that measurement is zero or near-zero and the figure
   *  keeps the collapsed size until something forces a resize — which is why
   *  the component only looked right *after* switching versions. */
  height: number;
  ready: boolean;
}> = ({ metadata, dashboardId, index, request, height, ready }) => {
  const { pins, definitionVersionId } = request;
  const isCard = String((metadata as Record<string, unknown>).component_type ?? '') === 'card';

  // A card's value comes from the dashboard's bulk-compute pass, not from the
  // renderer. The modal has no such parent, so without this a card renders as
  // a permanent "…" — the one component type the whole feature is most likely
  // to be used on, since a changed number is what prompts the question.
  const [cardValue, setCardValue] = useState<unknown>(undefined);
  const [cardSecondary, setCardSecondary] = useState<Record<string, unknown>>({});
  const [cardLoading, setCardLoading] = useState(false);
  const pinKey = JSON.stringify(pins);

  // The component's *definition* is versioned too, not just its data. The
  // version's id goes out on every render path (cards via bulk-compute below,
  // figures and tables via the context) and the server reads the definition
  // from that version: the render endpoints otherwise read the live document,
  // so pinning only the data would draw a past version's numbers with today's
  // chart definition. A component deleted since renders from the version too.
  useEffect(() => {
    if (!ready || !isCard || !dashboardId || !index) return;
    let cancelled = false;
    setCardLoading(true);
    bulkComputeCards(
      dashboardId,
      [],
      [index],
      undefined,
      undefined,
      dataVersionBody({ pins, definitionVersionId }),
    )
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
  }, [ready, isCard, dashboardId, index, pinKey, definitionVersionId]);

  return (
    <DataVersionProvider
      pins={pins}
      definitionVersionId={definitionVersionId}
      dashboardId={dashboardId}
    >
      <Box style={{ height, minHeight: height }}>
        {ready ? (
          <ComponentRenderer
            // Remount per (config, data) pair. The renderers cache by component
            // id, and reusing the instance would show the previous version's
            // figure until the next fetch lands.
            key={`${index}-${pinKey}-${renderDefinitionKey(metadata, definitionVersionId)}`}
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


/**
 * Which commit one view of the component reads.
 *
 * The same control serves the single view and both compare panes, so they
 * offer the same choices in the same words (`buildDataVersionOptions`).
 * Pointing both panes at the same commit is the point: with the data held
 * constant, the only difference left between the two charts is the
 * definition, which is how you see what a config change actually did.
 */
const PaneDataPicker: React.FC<{
  history: DatasetHistory | undefined;
  /** Set on a view bound to a stored version: offers that version's own data,
   *  which is then the default. The live pane is bound to none. */
  boundToVersion?: boolean;
  /** The commit the bound version recorded, if any. */
  versionDataVersion?: number;
  value: DataOverride;
  onChange: (value: DataOverride) => void;
  /** Visible label; without one, `ariaLabel` names the control instead. */
  label?: string;
  ariaLabel: string;
  testId: string;
}> = ({
  history,
  boundToVersion = false,
  versionDataVersion,
  value,
  onChange,
  label,
  ariaLabel,
  testId,
}) => {
  if (!history || history.commits.length === 0) return null;

  const options = buildDataVersionOptions({
    commits: history.commits,
    currentVersion: history.currentVersion,
    withVersionDefault: boundToVersion,
    versionDataVersion,
  });

  return (
    <Select
      size="xs"
      label={label}
      data={options}
      value={dataOverrideToValue(value)}
      onChange={(next) => {
        const choice = valueToDataOverride(next);
        // An unbound pane has no "follow the version": its resting state is
        // the latest data.
        onChange(choice === undefined && !boundToVersion ? null : choice);
      }}
      comboboxProps={COMBOBOX_PROPS}
      allowDeselect={false}
      searchable={options.length > 8}
      aria-label={label ? undefined : ariaLabel}
      data-testid={testId}
      style={{ minWidth: 0 }}
    />
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

  const brandScope = useBrandScopeAttributes();
  const narrow = useMediaQuery(NARROW_QUERY, false, { getInitialValueInEffect: false });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DashboardVersionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // On by default: the point of the comparison is the view as it *was*.
  // Switchable off to isolate the other axis — "did the chart change, or did
  // the data?" is two questions, and this separates them.
  const [useHistoricalData, setUseHistoricalData] = useState(true);
  /** Explicit per-commit override, when the user picks one from the dataset
   *  select. `undefined` follows the version (the default); `null` is the
   *  latest data (see `DataOverride`). */
  const [dataOverride, setDataOverride] = useState<DataOverride>(undefined);
  const [compare, setCompare] = useState(false);
  /** The right-hand pane's data, independent of the left.
   *
   * Defaults to live, which is what "compare against current" means. Set it
   * to the same commit as the left pane to hold the data constant, and the
   * only remaining difference between the two charts is the definition —
   * which is how you see what a config change actually did. */
  const [compareOverride, setCompareOverride] = useState<DataOverride>(null);
  const [restoreLayout, setRestoreLayout] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [confirmRestore, setConfirmRestore] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  // Mantine's modal animates in, and a figure that measures its container
  // during that animation gets a near-zero height and keeps it. Rendering is
  // held until the enter transition has ended (`onEnterTransitionEnd` below),
  // which is what makes the component fit on *first* open rather than only
  // after switching versions. Tied to the transition itself rather than a
  // timer, so a reduced-motion setting (no transition) renders at once.
  const [ready, setReady] = useState(false);

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
      setReady(false);
      setSelectedId(null);
      setDetail(null);
      setError(null);
      setUseHistoricalData(true);
      setDataOverride(undefined);
      setCompare(false);
      setCompareOverride(null);
      setRestoreLayout(false);
      setConfirmRestore(false);
      setRestoreError(null);
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
    () => (detail && index && dashboardId ? componentInVersion(detail, dashboardId, index) : null),
    [detail, dashboardId, index],
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
  // showing: the comparison is a lens, not a mode switch. The definition is
  // the version `historical` was read from, which can trail `selectedId` for
  // a moment while the next version's detail loads.
  const definitionVersionId = detail?.version_id ?? selectedId;
  const pastRequest = useMemo(
    () =>
      paneRequest(dcId, { dataOverride, useHistoricalData, versionDataVersion }, definitionVersionId),
    [dcId, dataOverride, useHistoricalData, versionDataVersion, definitionVersionId],
  );

  /** The compare pane reads whatever it was pointed at, defaulting to live.
   *  `useHistoricalData` is deliberately not consulted: that switch describes
   *  the version being examined, and this pane is not it. */
  const compareChoice = useMemo(
    () => ({ dataOverride: compareOverride, useHistoricalData: false, versionDataVersion: undefined }),
    [compareOverride],
  );
  const compareDataVersion = useMemo(() => resolveDataVersion(compareChoice), [compareChoice]);
  const compareRequest = useMemo(
    () => paneRequest(dcId, compareChoice, null),
    [dcId, compareChoice],
  );

  // Commits available for the manual override. Fetched only while the modal is
  // open and the component actually has a collection.
  const { histories } = useDatasetHistories(
    metadata ? [metadata] : undefined,
    opened && Boolean(dcId),
  );
  const history = histories.find((h) => h.dcId === dcId);

  const selected = versions.find((v) => v.version_id === selectedId) || null;
  const selectedIndex = versions.findIndex((v) => v.version_id === selectedId);
  const selectedTitle = selected ? versionTitle(selected) : 'the selected version';
  const selectedKind = selected ? kindMeta(selected.kind) : null;

  // The kind is spelled out in each option, not left to a colour: "Autosave"
  // and "Saved" are what tell two neighbouring versions apart.
  const versionOptions = useMemo(
    () =>
      versions.map((v, position) => ({
        value: v.version_id,
        label: [
          position === 0 ? 'Newest' : null,
          `v${v.seq}`,
          v.label?.trim() || null,
          kindMeta(v.kind).label,
          absDateTime(v.created_at),
        ]
          .filter(Boolean)
          .join(' · '),
      })),
    [versions],
  );

  /** Move to a version, dropping any commit chosen for the previous one.
   *
   * A commit picked against one version is not meaningful against another —
   * carrying it over would silently answer a question the user did not ask. */
  const selectVersion = useCallback((versionId?: string) => {
    if (!versionId) return;
    setSelectedId(versionId);
    setDataOverride(undefined);
  }, []);
  const dataUnavailable =
    useHistoricalData &&
    dataOverride === undefined &&
    Boolean(detail) &&
    Boolean(dcId) &&
    versionDataVersion === undefined;

  const openConfirm = useCallback(() => {
    setRestoreError(null);
    setConfirmRestore(true);
  }, []);
  const closeConfirm = useCallback(() => {
    if (restoring) return;
    setConfirmRestore(false);
    setRestoreError(null);
  }, [restoring]);

  const handleRestore = useCallback(async () => {
    if (!selectedId || !index || !dashboardId) return;
    setRestoring(true);
    setRestoreError(null);
    try {
      const result = await restoreComponentFromVersion(
        selectedId,
        dashboardId,
        index,
        restoreLayout,
      );
      notifications.show({
        color: 'green',
        title: result.readded ? 'Component restored' : 'Component reverted',
        message: result.readded
          ? 'It had been deleted and is back on the dashboard.'
          : `Restored from ${selectedTitle}. Everything else is untouched.`,
      });
      setConfirmRestore(false);
      onClose();
      onRestored?.();
    } catch (err) {
      // Said in the dialog that asked, like main's other confirmations, so the
      // reader can retry or cancel without hunting for a toast.
      setRestoreError((err as Error)?.message || String(err));
    } finally {
      setRestoring(false);
    }
  }, [selectedId, dashboardId, index, restoreLayout, selectedTitle, onClose, onRestored]);

  /** Height of one rendered pane.
   *
   *  Equal in both modes: comparing side by side puts the two panes on one
   *  row, so neither has to shrink to fit, and identical heights are what let
   *  the eye read the difference rather than re-scale for it. */
  const paneHeight = 320;

  const body = (() => {
    if (loadingVersions || (loading && !detail)) {
      return (
        <Group justify="center" py="xl" role="status" aria-label="Loading version">
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
        request={pastRequest}
        height={paneHeight}
        ready={ready}
      />
    );

    if (!compare || !metadata) return past;

    // Side by side, past on the left. Two charts of the same shape are
    // compared by scanning across at a fixed height, and a vertical stack
    // makes that a scroll instead of a glance. Equal columns keep both panes
    // at the same scale, since a difference in size would read as a difference
    // in the data. Below `md` there is no room for two, and they stack.
    const sameData = Boolean(dcId) && dataVersion === compareDataVersion;

    return (
      <Stack gap={6}>
        {/* Only the config differs once both panes read the same commit, so
            say so — otherwise a reader cannot tell whether a difference they
            are looking at came from the definition or the data. */}
        {sameData && (
          <Text size="xs" c="dimmed" ta="center">
            <Icon
              icon="mdi:equal"
              width={12}
              aria-hidden
              style={{ verticalAlign: '-1px', marginRight: 4 }}
            />
            Same data on both sides: any difference below comes from the configuration.
          </Text>
        )}
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          <Stack
            gap={4}
            style={{ minWidth: 0 }}
            role="group"
            aria-label={`${selectedTitle}, as saved`}
          >
            <Group gap={6} wrap="nowrap">
              <Badge size="xs" color="yellow" variant="light" style={{ flexShrink: 0 }}>
                {selected ? versionTitle(selected) : 'Selected version'}
              </Badge>
            </Group>
            <PaneDataPicker
              history={history}
              boundToVersion
              versionDataVersion={versionDataVersion}
              value={dataOverride}
              onChange={setDataOverride}
              ariaLabel={`Data version for ${selectedTitle}`}
              testId="component-version-data-select-past"
            />
            <Paper withBorder radius="md" p={4} style={{ minWidth: 0 }}>
              {past}
            </Paper>
          </Stack>

          <Stack gap={4} style={{ minWidth: 0 }} role="group" aria-label="Current component">
            <Group gap={6} wrap="nowrap">
              <Badge size="xs" color="blue" variant="light" style={{ flexShrink: 0 }}>
                Current
              </Badge>
            </Group>
            <PaneDataPicker
              history={history}
              // No "this version's data" here: this pane is the live component,
              // which is not bound to a stored version.
              value={compareOverride}
              onChange={setCompareOverride}
              ariaLabel="Data version for the current component"
              testId="component-version-data-select-current"
            />
            <Paper withBorder radius="md" p={4} style={{ minWidth: 0 }}>
              <VersionedComponent
                metadata={metadata}
                dashboardId={dashboardId}
                index={index}
                request={compareRequest}
                height={paneHeight}
                ready={ready}
              />
            </Paper>
          </Stack>
        </SimpleGrid>
      </Stack>
    );
  })();

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        size={compare ? '80rem' : 'xl'}
        fullScreen={narrow}
        // Over the dashboard, and above the floating map card, like main's
        // other dashboard modals.
        zIndex={Z_LAYERS.overlay}
        // Portaled to <body>, so put back inside the dashboard's brand scope
        // by hand (see `useBrandScopeAttributes`).
        className={brandScope?.className}
        data-mantine-color-scheme={brandScope?.['data-mantine-color-scheme']}
        onEnterTransitionEnd={() => setReady(true)}
        // Escape is a window listener on every open modal: with the restore
        // confirmation up, it must close that one only.
        closeOnEscape={!confirmRestore}
        title={
          <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
            {/* The icon of the menu item that opens it. */}
            <Icon icon={EDIT_MENU_STYLE.history.icon} width={18} aria-hidden />
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
            // A dropdown, not a segmented control: a dashboard accumulates a
            // version per save, so the strip is a handful of tabs on day one and
            // an unusable horizontal scroll by month three. The select stays one
            // line at any length, is searchable once that matters, and has room
            // for the label and timestamp that tell the versions apart — `v37`
            // on a tab does not.
            //
            // Step buttons flank it because "the one before this" is the most
            // common move in a comparison, and hunting for it in a list is worse
            // than a click.
            <Group gap={6} wrap="nowrap" align="flex-end">
              <Tooltip label="Older version" withArrow openDelay={400} zIndex={Z_LAYERS.tooltip}>
                <ActionIcon
                  variant="default"
                  size="lg"
                  // `versions` is newest-first, so older is a *higher* index.
                  disabled={selectedIndex < 0 || selectedIndex >= versions.length - 1}
                  onClick={() => selectVersion(versions[selectedIndex + 1]?.version_id)}
                  aria-label="Older version"
                  data-testid="component-version-older"
                >
                  <Icon icon="mdi:chevron-left" width={18} aria-hidden />
                </ActionIcon>
              </Tooltip>

              <Select
                size="xs"
                label="Version"
                style={{ flex: 1, minWidth: 0 }}
                data={versionOptions}
                value={selectedId ?? ''}
                onChange={(value) => selectVersion(value ?? undefined)}
                // Searchable past the point where scanning stops being viable.
                searchable={versions.length > 8}
                comboboxProps={COMBOBOX_PROPS}
                allowDeselect={false}
                maxDropdownHeight={280}
                data-testid="component-version-select"
              />

              <Tooltip label="Newer version" withArrow openDelay={400} zIndex={Z_LAYERS.tooltip}>
                <ActionIcon
                  variant="default"
                  size="lg"
                  disabled={selectedIndex <= 0}
                  onClick={() => selectVersion(versions[selectedIndex - 1]?.version_id)}
                  aria-label="Newer version"
                  data-testid="component-version-newer"
                >
                  <Icon icon="mdi:chevron-right" width={18} aria-hidden />
                </ActionIcon>
              </Tooltip>
            </Group>
          )}

          {selected && (
            <Paper withBorder radius="md" p="xs">
              <Stack gap={8}>
                <Group justify="space-between" wrap="wrap" gap="sm">
                  <Stack gap={2} style={{ minWidth: 0 }}>
                    <Text size="sm" fw={600} truncate>
                      {versionTitle(selected)}
                    </Text>
                    <Group gap={6} wrap="wrap">
                      {selectedKind && (
                        // Icon and word both: the kind's colour is a hint,
                        // never the only way to read it.
                        <Badge
                          size="xs"
                          variant="light"
                          color={selectedKind.color}
                          leftSection={<Icon icon={selectedKind.icon} width={10} aria-hidden />}
                          data-testid="component-version-kind"
                        >
                          {selectedKind.label}
                        </Badge>
                      )}
                      <Text size="xs" c="dimmed">
                        {absDateTime(selected.created_at)}
                      </Text>
                      {typeof dataVersion === 'number' && (
                        <Badge size="xs" color="yellow" variant="light">
                          Data v{dataVersion}
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
                    reachable.

                    Hidden while comparing: each pane grows its own picker there,
                    and two controls driving the same state is a way to make the
                    one you are not looking at appear broken. */}
                {!compare && dcId && (
                  <PaneDataPicker
                    history={history}
                    boundToVersion
                    versionDataVersion={versionDataVersion}
                    value={dataOverride}
                    onChange={setDataOverride}
                    label="Data version"
                    ariaLabel="Data version"
                    testId="component-version-data-select"
                  />
                )}
              </Stack>
            </Paper>
          )}

          {dataUnavailable && (
            <Alert color="yellow" variant="light" icon={<Icon icon="mdi:alert" width={16} />}>
              This version recorded no dataset version for the component's data
              collection, so the component below is drawn from its{' '}
              <strong>latest data</strong>. Its layout and configuration are from
              the selected version.
            </Alert>
          )}

          {body}

          {canRestore && historical && (
            <>
              <Divider />
              <Group justify="flex-end">
                <Tooltip
                  label="Replaces only this component, leaving the rest of the dashboard alone"
                  withArrow
                  position="left"
                  zIndex={Z_LAYERS.tooltip}
                >
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<Icon icon="mdi:restore" width={14} aria-hidden />}
                    onClick={openConfirm}
                    data-testid="component-version-restore"
                  >
                    Restore this component
                  </Button>
                </Tooltip>
              </Group>
            </>
          )}
        </Stack>
      </Modal>

      {/* A sibling of the modal above, not a child: React events bubble
          through portals along the component tree, so nested inside it a key
          press here would reach the outer dialog too. */}
      <Modal
        opened={opened && confirmRestore}
        onClose={closeConfirm}
        title="Restore this component?"
        size="md"
        centered
        // Raised from inside the history modal, so one layer above it.
        zIndex={Z_LAYERS.nestedOverlay}
        className={brandScope?.className}
        data-mantine-color-scheme={brandScope?.['data-mantine-color-scheme']}
        closeOnClickOutside={!restoring}
        data-testid="component-version-restore-modal"
      >
        <Stack gap="sm">
          <Text size="sm">
            This replaces the component with how it was in{' '}
            <strong>{selectedTitle}</strong>.
          </Text>
          <Alert color="blue" variant="light" icon={<Icon icon="mdi:information" width={16} />}>
            Only this component changes; everything else on the dashboard stays as
            it is. The current state is saved as a version first, so this can be
            undone.
          </Alert>
          <Switch
            size="xs"
            checked={restoreLayout}
            onChange={(e) => setRestoreLayout(e.currentTarget.checked)}
            disabled={restoring}
            label="Also restore its position and size"
            description="Off, it stays where it is now, in the same section."
          />
          {restoreError && (
            <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" width={16} />}>
              {restoreError}
            </Alert>
          )}
          <Group justify="flex-end" gap="xs" mt="sm">
            <Button variant="subtle" onClick={closeConfirm} disabled={restoring}>
              Cancel
            </Button>
            <Button
              leftSection={<Icon icon="mdi:restore" width={14} aria-hidden />}
              loading={restoring}
              onClick={handleRestore}
              data-testid="component-version-restore-confirm"
            >
              Restore
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default ComponentVersionModal;
