/**
 * JourneyFunnel — scenario-aware filter funnel UI.
 *
 * Inline strip (always visible in the filter rail) + a modal that opens on
 * click. The strip is one line; the modal carries the full Plotly funnel
 * chart and any journey-mode navigation.
 *
 * Three scenarios determine what we show, derived from the active global
 * filters' link map:
 *
 *  - **Single DC** — one data collection referenced. The funnel is a
 *    straightforward chain. Strip: `<tag>: N → N₁ → N₂`. Modal: one
 *    Plotly funnel.
 *
 *  - **Linked DCs** (multiple DCs that share join columns via global
 *    filters' multi-link payload). One primary entity, cascading effects
 *    on related tables. Strip shows the primary's chain. Modal shows the
 *    primary funnel + a small "cascading effect" table for the linked DCs.
 *
 *  - **Unlinked DCs** — multiple DCs with no join path between them.
 *    Filters can't propagate. Strip shows a warning; modal shows an
 *    explainer with a pointer to the project YAML link configuration.
 *
 * The component also handles journey state: when a journey is active, the
 * strip prepends the journey name + step counter, and the modal exposes
 * the step list, Save-as-next-step, and Exit affordances.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Divider,
  Group,
  Modal,
  Skeleton,
  Stack,
  Table,
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

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function dcLabel(dcId: string, dcTagsById?: Record<string, string>): string {
  return dcTagsById?.[dcId] || dcId.slice(-6);
}

// ─────────────────────────────────────────────────────────────────────────────
// Scenario detection
// ─────────────────────────────────────────────────────────────────────────────

type Scenario =
  | { type: 'empty' }
  | { type: 'single'; dcId: string }
  | { type: 'linked'; primaryDcId: string; dcIds: string[] }
  | { type: 'unlinked'; components: string[][] };

/**
 * Two DCs are considered linked iff at least one active global filter
 * declares both of them in its `links[]` payload (the filter's
 * column-mapping array). We build that graph and BFS from any DC; if the
 * whole DC set is one connected component → linked. Otherwise the disjoint
 * components are returned so the explainer can be specific.
 *
 * The primary DC (for the linked case) is the first one in `targetDcs` —
 * the upstream order ranks DCs by the order they appear in the first
 * active global filter's `links`, which puts the filter's source DC first.
 */
function detectScenario(
  definitions: GlobalFilterDef[],
  targetDcs: FunnelTargetDC[],
): Scenario {
  const dcs = new Set(targetDcs.map((d) => d.dc_id));
  if (dcs.size === 0) return { type: 'empty' };
  if (dcs.size === 1) return { type: 'single', dcId: [...dcs][0] };

  // Build co-occurrence adjacency from each filter's link list.
  const adj = new Map<string, Set<string>>();
  for (const dc of dcs) adj.set(dc, new Set());
  for (const def of definitions) {
    const defDcs = def.links.map((l) => l.dc_id).filter((dc) => dcs.has(dc));
    for (let i = 0; i < defDcs.length; i++) {
      for (let j = i + 1; j < defDcs.length; j++) {
        adj.get(defDcs[i])!.add(defDcs[j]);
        adj.get(defDcs[j])!.add(defDcs[i]);
      }
    }
  }

  // Compute connected components.
  const components: string[][] = [];
  const seen = new Set<string>();
  for (const dc of dcs) {
    if (seen.has(dc)) continue;
    const comp: string[] = [];
    const queue = [dc];
    seen.add(dc);
    while (queue.length) {
      const n = queue.shift()!;
      comp.push(n);
      for (const m of adj.get(n) ?? []) {
        if (!seen.has(m)) {
          seen.add(m);
          queue.push(m);
        }
      }
    }
    components.push(comp);
  }

  if (components.length === 1) {
    return {
      type: 'linked',
      primaryDcId: targetDcs[0].dc_id,
      dcIds: [...dcs],
    };
  }
  return { type: 'unlinked', components };
}

// ─────────────────────────────────────────────────────────────────────────────
// Data fetching: live filter chain + per-stop journey counts
// ─────────────────────────────────────────────────────────────────────────────

function useLiveFunnel(
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
          console.warn('FunnelInsight: live funnel failed:', err);
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

  return { data, loading };
}

function useJourneyStopCounts(
  parentDashboardId: string,
  journey: Journey | null,
  targetDcs: FunnelTargetDC[],
  refreshTick: number | undefined,
): { perStop: Record<string, number | null>[]; loading: boolean } {
  const [perStop, setPerStop] = useState<Record<string, number | null>[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!journey || targetDcs.length === 0) {
      setPerStop([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
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
            out[dcId] = counts ? counts[stepsForStop.length] ?? counts[0] ?? null : null;
          }
          return out;
        } catch (err) {
          console.warn(`FunnelInsight: stop "${stop.name}" failed:`, err);
          return Object.fromEntries(targetDcs.map((d) => [d.dc_id, null]));
        }
      }),
    ).then((all) => {
      if (!cancelled) {
        setPerStop(all);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [
    parentDashboardId,
    JSON.stringify(targetDcs),
    JSON.stringify(
      journey ? journey.stops.map((s) => ({ id: s.id, gfs: s.global_filter_state })) : null,
    ),
    refreshTick,
  ]);

  return { perStop, loading };
}

// ─────────────────────────────────────────────────────────────────────────────
// Inline strip — always visible, one line
// ─────────────────────────────────────────────────────────────────────────────

interface InlineStripProps {
  scenario: Scenario;
  data: FunnelResponse | null;
  loading: boolean;
  dcTagsById?: Record<string, string>;
  journey: Journey | null;
  activeStopIndex: number;
  onOpen: () => void;
}

const InlineStrip: React.FC<InlineStripProps> = ({
  scenario,
  data,
  loading,
  dcTagsById,
  journey,
  activeStopIndex,
  onOpen,
}) => {
  if (scenario.type === 'empty') return null;

  // Scenario 2: unlinked DCs — warning, no chain.
  if (scenario.type === 'unlinked') {
    return (
      <UnstyledButton onClick={onOpen} style={{ width: '100%' }}>
        <Group gap={6} wrap="nowrap" align="center">
          <Icon icon="tabler:alert-triangle" width={14} color="var(--mantine-color-orange-7)" />
          <Text size="xs" fw={600} c="orange.7" style={{ flex: 1 }} truncate>
            Data collections must be linked
          </Text>
          <Icon icon="tabler:info-circle" width={12} color="var(--mantine-color-orange-6)" />
        </Group>
      </UnstyledButton>
    );
  }

  // Scenarios 1 & 3: pick the primary DC and render its chain.
  const primaryDcId = scenario.type === 'single' ? scenario.dcId : scenario.primaryDcId;
  const primaryTag = dcLabel(primaryDcId, dcTagsById);
  const counts = data?.counts[primaryDcId] ?? null;

  if (loading && !counts) {
    return <Skeleton height={16} radius="sm" />;
  }
  if (!counts || counts.length === 0) return null;

  const linkedCount = scenario.type === 'linked' ? scenario.dcIds.length - 1 : 0;

  return (
    <UnstyledButton onClick={onOpen} style={{ width: '100%' }}>
      <Group gap={6} wrap="nowrap" align="center">
        {journey && (
          <Tooltip
            label={`Journey: ${journey.name} · Step ${activeStopIndex + 1} of ${journey.stops.length}`}
            withArrow
          >
            <Icon icon="tabler:route" width={12} color="var(--mantine-color-blue-7)" />
          </Tooltip>
        )}
        <Text size="xs" fw={600} c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {primaryTag}:
        </Text>
        <Group gap={4} wrap="nowrap" align="center" style={{ flex: 1, minWidth: 0 }}>
          {counts.map((n, idx) => (
            <React.Fragment key={idx}>
              {idx > 0 && (
                <Icon
                  icon="tabler:chevron-right"
                  width={10}
                  color="var(--mantine-color-dimmed)"
                />
              )}
              <Text
                size="xs"
                fw={idx === counts.length - 1 ? 700 : 500}
                c={idx === counts.length - 1 ? 'blue.7' : 'dimmed'}
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {formatCount(n)}
              </Text>
            </React.Fragment>
          ))}
        </Group>
        {linkedCount > 0 && (
          <Tooltip label={`+${linkedCount} linked data collection${linkedCount > 1 ? 's' : ''}`} withArrow>
            <Text size="xs" c="dimmed" fw={500}>
              +{linkedCount}
            </Text>
          </Tooltip>
        )}
        <Icon icon="tabler:chart-bar" width={12} color="var(--mantine-color-blue-6)" />
      </Group>
    </UnstyledButton>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Plotly funnel chart for one DC + a series of points (one bar per point)
// ─────────────────────────────────────────────────────────────────────────────

interface FunnelChartProps {
  labels: string[];
  values: number[];
  activeIndex?: number;
  onClickBar?: (index: number) => void;
  height?: number;
}

const FunnelChart: React.FC<FunnelChartProps> = ({
  labels,
  values,
  activeIndex,
  onClickBar,
  height = 240,
}) => {
  const colors = labels.map((_, i) =>
    typeof activeIndex === 'number' && i === activeIndex
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
        margin: { l: 160, r: 24, t: 8, b: 8 },
        font: { size: 12 },
        showlegend: false,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
      onClick={(evt) => {
        if (!onClickBar) return;
        const idx = evt.points?.[0]?.pointIndex;
        if (typeof idx === 'number') onClickBar(idx);
      }}
    />
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Modal body — varies by scenario × journey-mode
// ─────────────────────────────────────────────────────────────────────────────

interface ModalBodyProps {
  scenario: Scenario;
  dcTagsById?: Record<string, string>;
  // Live mode inputs
  liveData: FunnelResponse | null;
  liveSteps: FunnelStep[];
  definitions: GlobalFilterDef[];
  // Journey mode inputs
  journey: Journey | null;
  activeStopId: string | null;
  perStop: Record<string, number | null>[];
  onClickStop: (stopId: string) => void;
}

const ModalBody: React.FC<ModalBodyProps> = ({
  scenario,
  dcTagsById,
  liveData,
  liveSteps,
  definitions,
  journey,
  activeStopId,
  perStop,
  onClickStop,
}) => {
  // Scenario 2: explainer instead of a chart.
  if (scenario.type === 'unlinked') {
    return (
      <Stack gap="md">
        <Group gap={8} align="flex-start">
          <Icon icon="tabler:alert-triangle" width={20} color="var(--mantine-color-orange-7)" />
          <Stack gap={4} style={{ flex: 1 }}>
            <Text fw={600}>Data collections must be linked.</Text>
            <Text size="sm" c="dimmed">
              Your active global filters span multiple data collections that don't share a
              join column. The funnel can only narrow data when collections are linked —
              typically via a shared identifier (e.g. <Text component="span" fw={600}>sample</Text>,{' '}
              <Text component="span" fw={600}>gene_id</Text>). Without a link, filtering one
              collection has no effect on the other.
            </Text>
          </Stack>
        </Group>
        <Divider />
        <Stack gap={4}>
          <Text size="sm" fw={600}>Disconnected groups</Text>
          {scenario.components.map((comp, idx) => (
            <Text size="xs" c="dimmed" key={idx}>
              <Text component="span" fw={600} c="orange.8">
                Group {idx + 1}:
              </Text>{' '}
              {comp.map((dc) => dcLabel(dc, dcTagsById)).join(', ')}
            </Text>
          ))}
        </Stack>
        <Divider />
        <Text size="xs" c="dimmed">
          Configure project links (in the project YAML) so the funnel can propagate filters
          across data collections.
        </Text>
      </Stack>
    );
  }

  if (scenario.type === 'empty') return null;

  // Journey mode: bars = stops; click to jump.
  if (journey && journey.stops.length > 0) {
    const primaryDcId =
      scenario.type === 'single' ? scenario.dcId : scenario.primaryDcId;
    const primaryTag = dcLabel(primaryDcId, dcTagsById);
    const labels = journey.stops.map((s, i) => `${i + 1}. ${s.name}`);
    const values = journey.stops.map((_, i) => perStop[i]?.[primaryDcId] ?? 0);
    const activeIndex = journey.stops.findIndex((s) => s.id === activeStopId);

    return (
      <Stack gap="md">
        <Text size="xs" c="dimmed">
          Click any bar to jump to that step. Bar values are{' '}
          <Text component="span" fw={600}>
            {primaryTag}
          </Text>{' '}
          row counts at each step.
        </Text>
        <FunnelChart
          labels={labels}
          values={values}
          activeIndex={activeIndex >= 0 ? activeIndex : undefined}
          onClickBar={(idx) => {
            const stop = journey.stops[idx];
            if (stop) onClickStop(stop.id);
          }}
          height={Math.max(260, journey.stops.length * 60)}
        />
        {scenario.type === 'linked' && scenario.dcIds.length > 1 && (
          <CascadeTable
            scenario={scenario}
            labels={labels}
            dcTagsById={dcTagsById}
            perStep={perStop}
          />
        )}
      </Stack>
    );
  }

  // Live mode (no journey active): bars = filter chain steps.
  if (!liveData) return <Skeleton height={240} radius="sm" />;
  const primaryDcId =
    scenario.type === 'single' ? scenario.dcId : scenario.primaryDcId;
  const primaryTag = dcLabel(primaryDcId, dcTagsById);
  const primaryCounts = liveData.counts[primaryDcId] ?? [];
  const labels = primaryCounts.map((_, i) =>
    i === 0
      ? 'All rows'
      : `After ${
          definitions.find((d) => d.id === liveSteps[i - 1]?.filter_id)?.label ?? 'filter'
        }`,
  );

  return (
    <Stack gap="md">
      <Text size="xs" c="dimmed">
        Row counts in{' '}
        <Text component="span" fw={600}>
          {primaryTag}
        </Text>{' '}
        after each filter is applied.
      </Text>
      <FunnelChart labels={labels} values={primaryCounts} />
      {scenario.type === 'linked' && scenario.dcIds.length > 1 && (
        <CascadeTable
          scenario={scenario}
          labels={labels}
          dcTagsById={dcTagsById}
          perStep={primaryCounts.map((_, i) => {
            const row: Record<string, number | null> = {};
            for (const [dcId, counts] of Object.entries(liveData.counts)) {
              row[dcId] = counts ? counts[i] ?? null : null;
            }
            return row;
          })}
        />
      )}
    </Stack>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Cascade table — shown for linked-DC scenarios; one row per linked DC,
// one cell per step, value = that DC's row count at that step.
// ─────────────────────────────────────────────────────────────────────────────

interface CascadeTableProps {
  scenario: Scenario & { type: 'linked' };
  labels: string[];
  dcTagsById?: Record<string, string>;
  perStep: Record<string, number | null>[];
}

const CascadeTable: React.FC<CascadeTableProps> = ({
  scenario,
  labels,
  dcTagsById,
  perStep,
}) => {
  const otherDcs = scenario.dcIds.filter((d) => d !== scenario.primaryDcId);
  if (otherDcs.length === 0) return null;
  return (
    <Box>
      <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb={4} style={{ letterSpacing: 0.4 }}>
        Cascading effect on linked data collections
      </Text>
      <Table withTableBorder withColumnBorders striped highlightOnHover fz="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Data collection</Table.Th>
            {labels.map((l, i) => (
              <Table.Th key={i} style={{ textAlign: 'right' }}>
                {l}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {otherDcs.map((dcId) => (
            <Table.Tr key={dcId}>
              <Table.Td fw={600}>{dcLabel(dcId, dcTagsById)}</Table.Td>
              {perStep.map((row, i) => (
                <Table.Td key={i} style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {row[dcId] == null ? '—' : formatCount(row[dcId] as number)}
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Box>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Top-level component
// ─────────────────────────────────────────────────────────────────────────────

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
  const [modalOpen, setModalOpen] = useState(false);
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [newStopName, setNewStopName] = useState('');

  const scenario = useMemo(
    () => detectScenario(definitions, targetDcs),
    [definitions, targetDcs],
  );

  const { data: liveData, loading: liveLoading } = useLiveFunnel(
    parentDashboardId,
    liveSteps,
    targetDcs,
    refreshTick,
  );
  const { perStop } = useJourneyStopCounts(
    parentDashboardId,
    journey,
    targetDcs,
    refreshTick,
  );

  const activeStopIndex = journey
    ? journey.stops.findIndex((s) => s.id === activeStopId)
    : -1;

  if (scenario.type === 'empty') return null;

  const openSaveNextStop = () => {
    setNewStopName('');
    setSaveModalOpen(true);
  };
  const handleSave = () => {
    if (!newStopName.trim()) return;
    onSaveAsStop({ journeyId: journey?.id ?? null, stopName: newStopName.trim() });
    setSaveModalOpen(false);
  };

  return (
    <>
      <InlineStrip
        scenario={scenario}
        data={liveData}
        loading={liveLoading}
        dcTagsById={dcTagsById}
        journey={journey}
        activeStopIndex={activeStopIndex}
        onOpen={() => setModalOpen(true)}
      />

      <Modal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        size="xl"
        title={
          journey ? (
            <Group gap={8} wrap="nowrap" align="center">
              <Icon
                icon={journey.icon ?? 'tabler:route'}
                width={18}
                color={journey.color ?? 'var(--mantine-color-blue-filled)'}
              />
              <Text fw={600}>Journey · {journey.name}</Text>
              {activeStopIndex >= 0 && (
                <Text size="sm" c="dimmed">
                  Step {activeStopIndex + 1} of {journey.stops.length}
                </Text>
              )}
            </Group>
          ) : (
            <Group gap={8} wrap="nowrap" align="center">
              <Icon icon="tabler:filter-cog" width={18} />
              <Text fw={600}>Filter funnel</Text>
            </Group>
          )
        }
      >
        <Stack gap="md">
          <ModalBody
            scenario={scenario}
            dcTagsById={dcTagsById}
            liveData={liveData}
            liveSteps={liveSteps}
            definitions={definitions}
            journey={journey}
            activeStopId={activeStopId}
            perStop={perStop}
            onClickStop={(stopId) => {
              const stop = journey?.stops.find((s) => s.id === stopId);
              if (stop) onApplyStop(stop);
            }}
          />
          {/* Journey CTAs (Save next step, Exit) live in the modal footer
           *  rather than the rail strip — they're heavy actions, opening the
           *  modal is the appropriate gesture. */}
          {journey && scenario.type !== 'unlinked' && (
            <>
              <Divider />
              <Group justify="space-between">
                <Button
                  variant="subtle"
                  color="gray"
                  leftSection={<Icon icon="tabler:x" width={14} />}
                  onClick={() => {
                    onExitJourney();
                    setModalOpen(false);
                  }}
                >
                  Exit journey
                </Button>
                <Button
                  leftSection={<Icon icon="tabler:plus" width={14} />}
                  onClick={openSaveNextStop}
                >
                  Save current as next step
                </Button>
              </Group>
            </>
          )}
        </Stack>
      </Modal>

      <Modal
        opened={saveModalOpen}
        onClose={() => setSaveModalOpen(false)}
        title="Save step"
        size="sm"
      >
        <Stack gap="sm">
          <TextInput
            label="Step name"
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
    </>
  );
};

export default JourneyFunnel;
