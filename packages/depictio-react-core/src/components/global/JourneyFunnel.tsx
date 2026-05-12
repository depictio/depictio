/**
 * JourneyFunnel — filter-rail footer widget for the cross-tab Journey feature.
 *
 * Two modes, picked based on whether a journey is currently active:
 *
 *  - **Live mode** (no active journey) — shows cumulative row counts for the
 *    current global-filter chain (`N → N₁ → N₂`), plus a "Save current as
 *    new journey…" CTA. This is the original FunnelWidget behavior.
 *
 *  - **Active-journey mode** — renders the active journey's stops as a
 *    vertical list (●─ Stop 1 · count │ ●─ Stop 2 · count …). Each row is
 *    clickable to apply that stop's snapshot. The active stop is highlighted
 *    and shows its live row count (the only stop with a count fetched —
 *    saves N-1 round-trips per render). Bottom: "+ Save current as next
 *    stop" CTA, and an "Exit journey" link in the header.
 */

import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Group,
  Modal,
  Paper,
  Skeleton,
  Stack,
  Tabs,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

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

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

// ---------------------------------------------------------------------------
// Shared row-count computation hook
// ---------------------------------------------------------------------------

function useFunnelData(
  parentDashboardId: string,
  steps: FunnelStep[],
  targetDcs: FunnelTargetDC[],
  refreshTick: number | undefined,
): { data: FunnelResponse | null; loading: boolean } {
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
          console.warn('JourneyFunnel: computeFunnel failed:', err);
          setData(null);
        })
        .finally(() => setLoading(false));
    }, FETCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // stringify to debounce identity churn without re-running on shape-equal arrays
  }, [
    parentDashboardId,
    JSON.stringify(steps),
    JSON.stringify(targetDcs),
    refreshTick,
  ]);

  return { data, loading };
}

// ---------------------------------------------------------------------------
// Live mode — current filter chain, no journey active
// ---------------------------------------------------------------------------

interface LiveFunnelViewProps {
  parentDashboardId: string;
  definitions: GlobalFilterDef[];
  steps: FunnelStep[];
  targetDcs: FunnelTargetDC[];
  refreshTick?: number;
}

const LiveFunnelView: React.FC<LiveFunnelViewProps> = ({
  parentDashboardId,
  definitions,
  steps,
  targetDcs,
  refreshTick,
}) => {
  const { data, loading } = useFunnelData(parentDashboardId, steps, targetDcs, refreshTick);
  if (targetDcs.length === 0) return null;

  const renderSeries = (counts: number[] | null) => {
    if (counts === null) return <Text size="xs" c="dimmed">unavailable</Text>;
    return (
      <Group gap={6} wrap="nowrap">
        {counts.map((n, idx) => {
          const label =
            idx === 0
              ? 'Starting rows'
              : `After: ${
                  definitions.find((d) => d.id === steps[idx - 1]?.filter_id)?.label ??
                  'filter'
                }`;
          return (
            <React.Fragment key={idx}>
              {idx > 0 && (
                <Icon icon="tabler:chevron-right" width={12} color="var(--mantine-color-dimmed)" />
              )}
              <Tooltip label={label} withArrow>
                <Text
                  size="xs"
                  fw={idx === counts.length - 1 ? 700 : 500}
                  c={idx === counts.length - 1 ? 'blue' : 'dimmed'}
                  style={{ fontVariantNumeric: 'tabular-nums' }}
                >
                  {formatCount(n)}
                </Text>
              </Tooltip>
            </React.Fragment>
          );
        })}
      </Group>
    );
  };

  if (loading && !data) return <Skeleton height={20} radius="sm" />;
  if (!data) return null;

  const entries: Array<[string, number[] | null]> = Object.entries(data.counts) as Array<
    [string, number[] | null]
  >;
  if (entries.length === 0) return null;

  if (entries.length === 1) {
    const [, counts] = entries[0];
    return renderSeries(counts);
  }
  return (
    <Tabs defaultValue={entries[0]?.[0]} variant="pills" radius="sm">
      <Tabs.List>
        {entries.map(([dcId]) => (
          <Tabs.Tab key={dcId} value={dcId}>
            <Text size="xs">{dcId.slice(-6)}</Text>
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {entries.map(([dcId, counts]) => (
        <Tabs.Panel key={dcId} value={dcId} pt={6}>
          {renderSeries(counts)}
        </Tabs.Panel>
      ))}
    </Tabs>
  );
};

// ---------------------------------------------------------------------------
// JourneyFunnel — the top-level widget
// ---------------------------------------------------------------------------

export interface JourneyFunnelProps {
  parentDashboardId: string;
  definitions: GlobalFilterDef[];
  /** Live funnel steps — used when no journey is active. */
  liveSteps: FunnelStep[];
  /** Target DCs for both live and active-stop count computation. */
  targetDcs: FunnelTargetDC[];
  /** Active journey (null = live mode). */
  journey: Journey | null;
  activeStopId: string | null;
  /** Apply a stop's snapshot. Caller handles navigation + per-tab filter reset. */
  onApplyStop: (stop: JourneyStop) => void;
  /** Exit the active journey (clears active state, keeps current filters). */
  onExitJourney: () => void;
  /** Save the current dashboard state. If `journeyId` is null, opens a "name
   *  the new journey" flow; otherwise appends as next stop. */
  onSaveAsStop: (args: { journeyId: string | null; journeyName?: string; stopName: string }) => void;
  refreshTick?: number;
}

const JourneyFunnel: React.FC<JourneyFunnelProps> = ({
  parentDashboardId,
  definitions,
  liveSteps,
  targetDcs,
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
    setNewStopName('All samples');
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
          <Text size="xs" c="dimmed" mb={6}>
            Stop {activeIndex + 1} of {journey.stops.length}
          </Text>
        )}
        <Stack gap={4}>
          {journey.stops.map((stop, idx) => {
            const isActive = stop.id === activeStopId;
            return (
              <UnstyledButton
                key={stop.id}
                onClick={() => !isActive && onApplyStop(stop)}
                disabled={isActive}
                style={{
                  padding: '4px 6px',
                  borderRadius: 4,
                  backgroundColor: isActive
                    ? 'var(--mantine-color-blue-1)'
                    : 'transparent',
                  cursor: isActive ? 'default' : 'pointer',
                }}
              >
                <Group gap={6} wrap="nowrap" align="center">
                  <Icon
                    icon={isActive ? 'tabler:point-filled' : 'tabler:point'}
                    width={14}
                    color={
                      isActive
                        ? 'var(--mantine-color-blue-filled)'
                        : 'var(--mantine-color-dimmed)'
                    }
                  />
                  <Text size="xs" fw={isActive ? 700 : 500} truncate>
                    {idx + 1}. {stop.name}
                  </Text>
                  {isActive && targetDcs.length > 0 && (
                    <Box style={{ marginLeft: 'auto' }}>
                      <LiveFunnelView
                        parentDashboardId={parentDashboardId}
                        definitions={definitions}
                        steps={liveSteps}
                        targetDcs={targetDcs}
                        refreshTick={refreshTick}
                      />
                    </Box>
                  )}
                </Group>
              </UnstyledButton>
            );
          })}
          <UnstyledButton
            onClick={openSaveAsStop}
            style={{
              padding: '4px 6px',
              borderRadius: 4,
              borderTop: '1px dashed var(--mantine-color-blue-3)',
              marginTop: 4,
            }}
          >
            <Group gap={6} wrap="nowrap">
              <Icon icon="tabler:plus" width={14} color="var(--mantine-color-blue-7)" />
              <Text size="xs" c="blue.7" fw={600}>
                Save current as next stop
              </Text>
            </Group>
          </UnstyledButton>
        </Stack>

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
            placeholder="e.g. All samples"
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
