/**
 * JourneyFunnel — filter-rail footer widget for the cross-tab Journey feature.
 *
 * Renders a real Plotly funnel chart visualizing the row-count narrowing
 * across either:
 *
 *  - **Live mode** (no active journey) — the current global filter chain
 *    (`baseline → after filter A → after filter A+B → …`) + a "Save as
 *    new journey…" CTA.
 *
 *  - **Active-journey mode** — the active journey's stops, one bar per
 *    stop, labelled by name. Bars are clickable to jump to that stop. The
 *    active stop is highlighted. Below: "+ Save current as next stop"
 *    + "Exit journey".
 *
 * For multi-DC dashboards, the inline funnel shows the first target DC
 * (labelled by its data_collection_tag) and a "View per data collection"
 * link opens a modal with one funnel per DC.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Divider,
  Group,
  Modal,
  Paper,
  Skeleton,
  Stack,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import Plot from 'react-plotly.js';

import {
  computeFunnel,
  type FunnelResponse,
  type FunnelStep,
  type FunnelTargetDC,
  type GlobalFilterDef,
  type Journey,
  type JourneyStop,
} from '../../api';

const FETCH_DEBOUNCE_MS = 300;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dcLabel(dcId: string, dcTagsById?: Record<string, string>): string {
  return dcTagsById?.[dcId] || dcId.slice(-6);
}

/** A single point on a funnel chart — label + per-DC count map. */
interface FunnelPoint {
  label: string;
  /** Stable id for click handling (stop id in journey mode, step index in
   *  live mode). Optional because live-mode points aren't clickable. */
  clickId?: string;
  /** Per-DC row counts after applying everything up to and including this
   *  point. `null` = data load failed for that DC. */
  countsByDc: Record<string, number | null>;
}

/**
 * Render a Plotly funnel for one DC. Active label (when set) gets a deeper
 * shade; everything else uses the same blue. `onClickPoint` is called with
 * the clicked point's `clickId` so the host can apply the matching stop.
 */
interface FunnelChartProps {
  dcId: string;
  dcTag: string;
  points: FunnelPoint[];
  activeClickId?: string | null;
  onClickPoint?: (clickId: string) => void;
  height?: number;
}

const FunnelChart: React.FC<FunnelChartProps> = ({
  dcId,
  dcTag,
  points,
  activeClickId,
  onClickPoint,
  height = 200,
}) => {
  const labels = points.map((p) => p.label);
  // Plotly orientation: vertical funnel (default) wants y=labels (top→bottom),
  // x=values. We reverse so the widest slice is at the top, matching the
  // canonical funnel shape.
  const values = points.map((p) => p.countsByDc[dcId] ?? 0);
  const colors = points.map((p) =>
    p.clickId && p.clickId === activeClickId
      ? 'rgba(34, 110, 215, 1)'
      : 'rgba(34, 110, 215, 0.55)',
  );

  return (
    <Plot
      data={[
        {
          type: 'funnel',
          y: labels,
          x: values,
          textinfo: 'value+percent initial',
          textposition: 'inside',
          marker: { color: colors },
          connector: { line: { color: 'rgba(34, 110, 215, 0.3)', width: 1 } },
          hovertemplate: '<b>%{y}</b><br>%{x} rows<br>%{percentInitial:.0%} of start<extra></extra>',
        } as Plotly.Data,
      ]}
      layout={{
        height,
        margin: { l: 110, r: 16, t: 8, b: 8 },
        font: { size: 11 },
        showlegend: false,
        title: { text: dcTag, x: 0, font: { size: 11, color: '#868e96' } },
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
      onClick={(evt) => {
        if (!onClickPoint) return;
        const pointIdx = evt.points?.[0]?.pointIndex;
        if (typeof pointIdx !== 'number') return;
        const clickId = points[pointIdx]?.clickId;
        if (clickId) onClickPoint(clickId);
      }}
    />
  );
};

// ---------------------------------------------------------------------------
// Live mode — current filter chain, no journey active
// ---------------------------------------------------------------------------

interface LiveFunnelViewProps {
  parentDashboardId: string;
  definitions: GlobalFilterDef[];
  steps: FunnelStep[];
  targetDcs: FunnelTargetDC[];
  dcTagsById?: Record<string, string>;
  refreshTick?: number;
}

const LiveFunnelView: React.FC<LiveFunnelViewProps> = ({
  parentDashboardId,
  definitions,
  steps,
  targetDcs,
  dcTagsById,
  refreshTick,
}) => {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [data, setData] = useState<FunnelResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (targetDcs.length === 0) {
      setData(null);
      return;
    }
    const handle = setTimeout(() => {
      setLoading(true);
      computeFunnel(parentDashboardId, steps, targetDcs)
        .then((res) => setData(res))
        .catch((err) => {
          console.warn('LiveFunnelView: computeFunnel failed:', err);
          setData(null);
        })
        .finally(() => setLoading(false));
    }, FETCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [
    parentDashboardId,
    JSON.stringify(steps),
    JSON.stringify(targetDcs),
    refreshTick,
  ]);

  // Build the point list. Index 0 = baseline (no filters); index k = after
  // step k-1 applied. Labels use the filter's def label for clarity.
  const points: FunnelPoint[] = useMemo(() => {
    if (!data) return [];
    const result: FunnelPoint[] = [];
    const stepCount = steps.length;
    for (let i = 0; i <= stepCount; i++) {
      const label =
        i === 0
          ? 'All rows'
          : `After ${
              definitions.find((d) => d.id === steps[i - 1]?.filter_id)?.label ?? 'filter'
            }`;
      const countsByDc: Record<string, number | null> = {};
      for (const [dcId, counts] of Object.entries(data.counts)) {
        countsByDc[dcId] = counts ? counts[i] ?? null : null;
      }
      result.push({ label, countsByDc });
    }
    return result;
  }, [data, steps, definitions]);

  if (targetDcs.length === 0) return null;
  if (loading && !data) return <Skeleton height={140} radius="sm" />;
  if (!data || points.length === 0) return null;

  const dcEntries = Object.entries(data.counts);
  const primaryDcId = dcEntries[0][0];
  const primaryTag = dcLabel(primaryDcId, dcTagsById);

  return (
    <>
      <FunnelChart dcId={primaryDcId} dcTag={primaryTag} points={points} />
      {dcEntries.length > 1 && (
        <UnstyledButton
          onClick={() => setDetailsOpen(true)}
          style={{ width: 'fit-content' }}
        >
          <Group gap={4} wrap="nowrap" align="center">
            <Icon icon="tabler:layout-list" width={12} color="var(--mantine-color-blue-6)" />
            <Text size="xs" c="blue.6" fw={500}>
              View {dcEntries.length} data collections
            </Text>
          </Group>
        </UnstyledButton>
      )}
      <Modal
        opened={detailsOpen}
        onClose={() => setDetailsOpen(false)}
        title="Funnel per data collection"
        size="lg"
      >
        <Stack gap="lg">
          {dcEntries.map(([dcId], idx) => (
            <React.Fragment key={dcId}>
              {idx > 0 && <Divider />}
              <FunnelChart
                dcId={dcId}
                dcTag={dcLabel(dcId, dcTagsById)}
                points={points}
                height={240}
              />
            </React.Fragment>
          ))}
        </Stack>
      </Modal>
    </>
  );
};

// ---------------------------------------------------------------------------
// Journey mode — bars = stops, click a bar to apply
// ---------------------------------------------------------------------------

interface JourneyFunnelViewProps {
  parentDashboardId: string;
  journey: Journey;
  activeStopId: string | null;
  targetDcs: FunnelTargetDC[];
  dcTagsById?: Record<string, string>;
  onClickStop: (stopId: string) => void;
  refreshTick?: number;
}

const JourneyFunnelView: React.FC<JourneyFunnelViewProps> = ({
  parentDashboardId,
  journey,
  activeStopId,
  targetDcs,
  dcTagsById,
  onClickStop,
  refreshTick,
}) => {
  const [detailsOpen, setDetailsOpen] = useState(false);
  // perStopCounts[i] = result of /funnel for stops[i].global_filter_state.
  // Stored as Record<dcId, number|null> per stop. null = fetch failed.
  const [perStopCounts, setPerStopCounts] = useState<Record<string, number | null>[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (targetDcs.length === 0 || journey.stops.length === 0) {
      setPerStopCounts([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    // One /funnel call per stop in parallel. Each stop's filter_state is
    // converted to a single-step funnel — we want counts[1] (the after-
    // filter value), or counts[0] (baseline) when the stop has no filters.
    Promise.all(
      journey.stops.map(async (stop) => {
        const stepEntries = Object.entries(stop.global_filter_state || {});
        const stepsForStop: FunnelStep[] = stepEntries.map(([filter_id, value]) => ({
          filter_id,
          value,
        }));
        try {
          const res = await computeFunnel(parentDashboardId, stepsForStop, targetDcs);
          const out: Record<string, number | null> = {};
          for (const [dcId, counts] of Object.entries(res.counts)) {
            if (!counts) {
              out[dcId] = null;
              continue;
            }
            // Empty step → take baseline (counts[0]); else take post-filter.
            out[dcId] = counts[stepsForStop.length] ?? counts[0] ?? null;
          }
          return out;
        } catch (err) {
          console.warn(`JourneyFunnel: stop "${stop.name}" count failed:`, err);
          return Object.fromEntries(targetDcs.map((d) => [d.dc_id, null]));
        }
      }),
    ).then((all) => {
      if (!cancelled) {
        setPerStopCounts(all);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [
    parentDashboardId,
    JSON.stringify(targetDcs),
    JSON.stringify(journey.stops.map((s) => ({ id: s.id, gfs: s.global_filter_state }))),
    refreshTick,
  ]);

  const points: FunnelPoint[] = useMemo(
    () =>
      journey.stops.map((stop, i) => ({
        label: `${i + 1}. ${stop.name}`,
        clickId: stop.id,
        countsByDc: perStopCounts[i] || {},
      })),
    [journey.stops, perStopCounts],
  );

  if (loading && perStopCounts.length === 0) return <Skeleton height={180} radius="sm" />;
  if (points.length === 0) return null;

  const dcIds = targetDcs.map((d) => d.dc_id);
  if (dcIds.length === 0) return null;
  const primaryDcId = dcIds[0];
  const primaryTag = dcLabel(primaryDcId, dcTagsById);

  return (
    <>
      <FunnelChart
        dcId={primaryDcId}
        dcTag={primaryTag}
        points={points}
        activeClickId={activeStopId}
        onClickPoint={onClickStop}
        height={Math.max(140, journey.stops.length * 50)}
      />
      {dcIds.length > 1 && (
        <UnstyledButton onClick={() => setDetailsOpen(true)} style={{ width: 'fit-content' }}>
          <Group gap={4} wrap="nowrap" align="center">
            <Icon icon="tabler:layout-list" width={12} color="var(--mantine-color-blue-6)" />
            <Text size="xs" c="blue.6" fw={500}>
              View {dcIds.length} data collections
            </Text>
          </Group>
        </UnstyledButton>
      )}
      <Modal
        opened={detailsOpen}
        onClose={() => setDetailsOpen(false)}
        title="Journey funnel per data collection"
        size="lg"
      >
        <Stack gap="lg">
          {dcIds.map((dcId, idx) => (
            <React.Fragment key={dcId}>
              {idx > 0 && <Divider />}
              <FunnelChart
                dcId={dcId}
                dcTag={dcLabel(dcId, dcTagsById)}
                points={points}
                activeClickId={activeStopId}
                onClickPoint={onClickStop}
                height={240}
              />
            </React.Fragment>
          ))}
        </Stack>
      </Modal>
    </>
  );
};

// ---------------------------------------------------------------------------
// JourneyFunnel — top-level widget
// ---------------------------------------------------------------------------

export interface JourneyFunnelProps {
  parentDashboardId: string;
  definitions: GlobalFilterDef[];
  liveSteps: FunnelStep[];
  targetDcs: FunnelTargetDC[];
  dcTagsById?: Record<string, string>;
  journey: Journey | null;
  activeStopId: string | null;
  onApplyStop: (stop: JourneyStop) => void;
  onExitJourney: () => void;
  onSaveAsStop: (args: { journeyId: string | null; journeyName?: string; stopName: string }) => void;
  refreshTick?: number;
}

const JourneyFunnel: React.FC<JourneyFunnelProps> = ({
  parentDashboardId,
  definitions,
  liveSteps,
  targetDcs,
  dcTagsById,
  journey,
  activeStopId,
  onApplyStop,
  onExitJourney,
  onSaveAsStop,
  refreshTick,
}) => {
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [savingAsNewJourney, setSavingAsNewJourney] = useState(false);
  const [newJourneyName, setNewJourneyName] = useState('');
  const [newStopName, setNewStopName] = useState('');

  const openSaveAsStop = () => {
    setSavingAsNewJourney(false);
    setNewStopName('');
    setSaveModalOpen(true);
  };
  const openSaveAsNewJourney = () => {
    setSavingAsNewJourney(true);
    setNewJourneyName('');
    setNewStopName('All rows');
    setSaveModalOpen(true);
  };
  const handleSave = () => {
    if (!newStopName.trim()) return;
    if (savingAsNewJourney) {
      if (!newJourneyName.trim()) return;
      onSaveAsStop({
        journeyId: null,
        journeyName: newJourneyName.trim(),
        stopName: newStopName.trim(),
      });
    } else {
      onSaveAsStop({ journeyId: journey?.id ?? null, stopName: newStopName.trim() });
    }
    setSaveModalOpen(false);
  };

  if (targetDcs.length === 0 && !journey) return null;

  // ─────────────── Active-journey mode ───────────────
  if (journey) {
    const activeIndex = journey.stops.findIndex((s) => s.id === activeStopId);
    return (
      <Paper
        withBorder
        radius="md"
        p="sm"
        style={{
          backgroundColor: 'var(--mantine-color-blue-0)',
          borderColor: 'var(--mantine-color-blue-3)',
        }}
      >
        <Group justify="space-between" wrap="nowrap" mb="xs">
          <Group gap={6} wrap="nowrap" align="center" style={{ minWidth: 0 }}>
            <Icon
              icon={journey.icon ?? 'tabler:route'}
              width={14}
              color={journey.color ?? 'var(--mantine-color-blue-filled)'}
            />
            <Text size="xs" fw={700} c="blue.7" tt="uppercase" style={{ letterSpacing: 0.4 }} truncate>
              Journey · {journey.name}
            </Text>
          </Group>
          <Tooltip label="Exit journey (keep current filters)">
            <ActionIcon size="sm" variant="subtle" color="gray" onClick={onExitJourney}>
              <Icon icon="tabler:x" width={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
        {activeIndex >= 0 && (
          <Text size="xs" c="dimmed" mb={4}>
            Stop {activeIndex + 1} of {journey.stops.length} · click a bar to jump
          </Text>
        )}
        <JourneyFunnelView
          parentDashboardId={parentDashboardId}
          journey={journey}
          activeStopId={activeStopId}
          targetDcs={targetDcs}
          dcTagsById={dcTagsById}
          onClickStop={(stopId) => {
            const stop = journey.stops.find((s) => s.id === stopId);
            if (stop) onApplyStop(stop);
          }}
          refreshTick={refreshTick}
        />
        <UnstyledButton
          onClick={openSaveAsStop}
          mt={6}
          style={{
            padding: '4px 6px',
            borderRadius: 4,
            borderTop: '1px dashed var(--mantine-color-blue-3)',
          }}
        >
          <Group gap={6} wrap="nowrap">
            <Icon icon="tabler:plus" width={14} color="var(--mantine-color-blue-7)" />
            <Text size="xs" c="blue.7" fw={600}>
              Save current as next stop
            </Text>
          </Group>
        </UnstyledButton>

        <Modal opened={saveModalOpen} onClose={() => setSaveModalOpen(false)} title="Save stop" size="sm">
          <Stack gap="sm">
            <TextInput
              label="Stop name"
              placeholder="e.g. Riverwater + 2 samples"
              value={newStopName}
              onChange={(e) => setNewStopName(e.currentTarget.value)}
              autoFocus
            />
            <Group justify="flex-end">
              <Button variant="subtle" onClick={() => setSaveModalOpen(false)}>
                Cancel
              </Button>
              <Button onClick={handleSave} disabled={!newStopName.trim()}>
                Save
              </Button>
            </Group>
          </Stack>
        </Modal>
      </Paper>
    );
  }

  // ─────────────── Live mode (no active journey) ───────────────
  return (
    <Paper withBorder radius="md" p="sm">
      <Group gap={6} wrap="nowrap" align="center" mb="xs">
        <Icon icon="tabler:filter-cog" width={14} color="var(--mantine-color-dimmed)" />
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ letterSpacing: 0.4 }}>
          Funnel
        </Text>
      </Group>
      <LiveFunnelView
        parentDashboardId={parentDashboardId}
        definitions={definitions}
        steps={liveSteps}
        targetDcs={targetDcs}
        dcTagsById={dcTagsById}
        refreshTick={refreshTick}
      />
      <UnstyledButton onClick={openSaveAsNewJourney} mt={8} style={{ width: '100%' }}>
        <Group gap={6} wrap="nowrap">
          <Icon icon="tabler:bookmark-plus" width={14} color="var(--mantine-color-blue-7)" />
          <Text size="xs" c="blue.7" fw={600}>
            Save current filters as new journey…
          </Text>
        </Group>
      </UnstyledButton>

      <Modal
        opened={saveModalOpen}
        onClose={() => setSaveModalOpen(false)}
        title="Save as new journey"
        size="sm"
      >
        <Stack gap="sm">
          <TextInput
            label="Journey name"
            placeholder="e.g. Riverwater funnel"
            value={newJourneyName}
            onChange={(e) => setNewJourneyName(e.currentTarget.value)}
            autoFocus
          />
          <TextInput
            label="First stop name"
            placeholder="e.g. All rows"
            value={newStopName}
            onChange={(e) => setNewStopName(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setSaveModalOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={!newJourneyName.trim() || !newStopName.trim()}
            >
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
};

export default JourneyFunnel;
