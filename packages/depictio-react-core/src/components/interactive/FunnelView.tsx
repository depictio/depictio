/**
 * Funnel overview modal (issue #939).
 *
 * Shows the cascading restriction of the applied filters as a real Plotly
 * funnel: one trace per delta-backed data collection, one y-band per stage,
 * starting from the unfiltered row count and narrowing as each active filter
 * is applied in turn. Multiple DCs render side by side in the same funnel, so
 * a filter that guts one collection while leaving another untouched is visible
 * at a glance.
 *
 * The stage order is editable. Row counts are the whole point of the view and
 * they depend on the order the filters are applied in, so the reorder list
 * lets you ask "what if I had filtered by run first?" without touching the
 * dashboard's actual filter state. The final stage is order-independent (an
 * intersection does not care about sequence); every stage above it is not.
 *
 * Data comes from `POST /dashboards/funnel_values/{id}` with
 * `include_stages: true`, which applies `filters` in the order it receives
 * them. Reordering is therefore just a client-side permutation of the request
 * body, refetched when it changes. Colors are Mantine theme tokens.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Center,
  Group,
  Loader,
  Modal,
  MultiSelect,
  SegmentedControl,
  Stack,
  Text,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import Plot from 'react-plotly.js';

import {
  fetchFunnelValues,
  FunnelStage,
  FunnelValuesResponse,
  InteractiveFilter,
} from '../../api';
import { applyLayoutTheme, plotlyThemeColors } from '../advanced_viz/plotlyTheme';
import { isFilterActive } from '../../activeFilters';

const formatValue = (value: unknown): string => {
  if (Array.isArray(value)) return value.map(String).join(', ');
  if (value === null || value === undefined) return '';
  return String(value);
};

/** Label for one stage's y-band. Kept short on purpose: the y axis gets a
 *  fixed slice of the modal, and a wrapped 60-char label eats the plot. */
const stageLabel = (stage: FunnelStage, position: number): string => {
  const name = stage.label || stage.column_name || `Filter ${position}`;
  const value = formatValue(stage.value);
  const short = value.length > 24 ? `${value.slice(0, 23)}…` : value;
  return short ? `${position}. ${name} = ${short}` : `${position}. ${name}`;
};

/** Left gutter reserved for the stage labels, in px. Sized for the longest
 *  label `stageLabel` can emit (a position, a column name and a 24-char value)
 *  so the chart never has to measure its own ticks. */
const STAGE_LABEL_GUTTER = 240;

type LabelMode = 'value' | 'percent initial' | 'percent previous';

export interface FunnelViewProps {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  /** The shell's (debounced) filter list, the same one the components use. */
  filters: InteractiveFilter[];
  /** Stage order as component indexes, when the shell owns it (so it can be
   *  exported with the analysis state). Uncontrolled when omitted. */
  order?: string[];
  onOrderChange?: (order: string[]) => void;
}

const FunnelView: React.FC<FunnelViewProps> = ({
  opened,
  onClose,
  dashboardId,
  filters,
  order: controlledOrder,
  onOrderChange,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const [data, setData] = useState<FunnelValuesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [labelMode, setLabelMode] = useState<LabelMode>('value');
  /** DC ids to chart. `null` means "all of them", which is also what we fall
   *  back to when the user clears the selection. */
  const [visibleDcs, setVisibleDcs] = useState<string[] | null>(null);
  /** User-chosen stage order, as component indexes. Empty = dashboard order.
   *  Controlled by the shell when it passes `order`, local otherwise. */
  const [localOrder, setLocalOrder] = useState<string[]>([]);
  const order = controlledOrder ?? localOrder;
  const setOrder = useCallback(
    (next: string[]) => {
      setLocalOrder(next);
      onOrderChange?.(next);
    },
    [onOrderChange],
  );

  // Must stay the shared rule: the server zips its `stages` array positionally
  // against this list, so a divergence mislabels every row past it.
  const activeFilters = useMemo(() => filters.filter(isFilterActive), [filters]);

  // Reconcile the stored order against the live filter list: keep the ranks the
  // user set for filters that are still active, drop the ones they cleared, and
  // append newly applied filters at the end (they were applied last, so that is
  // where they belong until the user says otherwise).
  const orderedFilters = useMemo(() => {
    const byIndex = new Map(activeFilters.map((f) => [String(f.index), f]));
    const ranked: InteractiveFilter[] = [];
    for (const idx of order) {
      const f = byIndex.get(idx);
      if (f) {
        ranked.push(f);
        byIndex.delete(idx);
      }
    }
    // Whatever the stored order did not cover keeps its natural position.
    for (const f of activeFilters) {
      if (byIndex.delete(String(f.index))) ranked.push(f);
    }
    return ranked;
  }, [activeFilters, order]);

  const reordered = useMemo(
    () => orderedFilters.some((f, i) => String(f.index) !== String(activeFilters[i]?.index)),
    [orderedFilters, activeFilters],
  );

  const requestKey = useMemo(
    () => JSON.stringify(orderedFilters.map((f) => [f.index, f.value])),
    [orderedFilters],
  );

  useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchFunnelValues(dashboardId, orderedFilters, [], true, controller.signal)
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
    // requestKey stands in for the orderedFilters array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, dashboardId, requestKey]);

  const initialRows = useMemo(() => data?.initial_rows_by_dc ?? {}, [data]);
  const stages = useMemo(() => data?.stages ?? [], [data]);
  const dcLabels = useMemo(() => data?.dc_labels ?? {}, [data]);
  const allDcIds = useMemo(() => Object.keys(initialRows), [initialRows]);

  // Drop a stale DC selection when the dashboard's DC set changes under us.
  useEffect(() => {
    setVisibleDcs((cur) => {
      if (cur === null) return null;
      const next = cur.filter((dc) => allDcIds.includes(dc));
      return next.length === cur.length ? cur : next;
    });
  }, [allDcIds]);

  const chartedDcs = useMemo(() => {
    if (visibleDcs === null || visibleDcs.length === 0) return allDcIds;
    return allDcIds.filter((dc) => visibleDcs.includes(dc));
  }, [allDcIds, visibleDcs]);

  const moveStage = useCallback(
    (from: number, to: number) => {
      if (to < 0 || to >= orderedFilters.length) return;
      const next = orderedFilters.map((f) => String(f.index));
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      setOrder(next);
    },
    [orderedFilters],
  );

  // One Plotly funnel trace per DC. `y` is shared across traces so the stages
  // line up in bands; `funnelmode: 'group'` then draws the DCs side by side
  // inside each band instead of stacking them into one misleading bar.
  const plotData = useMemo(() => {
    if (chartedDcs.length === 0) return [];
    const yLabels = ['0. Unfiltered', ...stages.map((s, i) => stageLabel(s, i + 1))];
    const palette = [
      theme.colors.teal[6],
      theme.colors.blue[6],
      theme.colors.violet[6],
      theme.colors.orange[6],
      theme.colors.pink[6],
      theme.colors.cyan[6],
      theme.colors.grape[6],
      theme.colors.lime[7],
    ];
    const connectorColor = plotlyThemeColors(isDark, theme).gridColor;
    return chartedDcs.map((dc, i) => ({
      type: 'funnel' as const,
      name: dcLabels[dc] || dc.slice(0, 8),
      orientation: 'h' as const,
      y: yLabels,
      // A stage whose count failed to load comes back null; Plotly leaves a
      // gap for it rather than drawing a misleading zero.
      x: [initialRows[dc] ?? null, ...stages.map((s) => s.rows_by_dc[dc] ?? null)],
      textinfo: labelMode === 'value' ? 'value' : `value+${labelMode}`,
      textposition: 'inside' as const,
      hovertemplate: '%{y}<br>%{x} rows<extra>%{fullData.name}</extra>',
      marker: { color: palette[i % palette.length] },
      connector: { line: { color: connectorColor, width: 1 } },
    }));
  }, [chartedDcs, stages, initialRows, dcLabels, labelMode, theme, isDark]);

  const layout = useMemo(
    () =>
      applyLayoutTheme(
        {
          // Fixed left margin, NOT `yaxis.automargin`. Automargin resizes the
          // plot to fit the tick labels, the container is width:100%, and a
          // resize feeds back into another automargin pass: inside a modal
          // that is still animating open, the two chase each other and the
          // renderer spins. Stage labels are length-capped by `stageLabel`, so
          // a fixed gutter holds them without measuring.
          margin: { l: STAGE_LABEL_GUTTER, r: 24, t: 8, b: 24 },
          // Funnel bands read top-down; Plotly's category axis defaults to
          // bottom-up, which would put "Unfiltered" at the bottom.
          yaxis: { autorange: 'reversed' },
          showlegend: chartedDcs.length > 1,
          legend: { orientation: 'h', y: -0.12 },
          funnelmode: 'group',
          plot_bgcolor: 'rgba(0,0,0,0)',
          paper_bgcolor: 'rgba(0,0,0,0)',
        },
        isDark,
        theme,
      ),
    [chartedDcs.length, isDark, theme],
  );

  // Each band needs a fixed slice of vertical space or the funnel collapses
  // into unreadable slivers once a dashboard applies more than three filters.
  const chartHeight = Math.max(260, 90 + (stages.length + 1) * 46);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={
        <Group gap="xs">
          <Icon icon="mdi:filter-check-outline" width={18} height={18} />
          <Text fw={600}>Filter funnel</Text>
          {loading && data && <Loader size="xs" />}
        </Group>
      }
    >
      {error && (
        <Alert color="orange" title="Funnel unavailable">
          {error}
        </Alert>
      )}
      {!error && !data && loading && (
        <Center py="xl">
          <Loader size="sm" />
        </Center>
      )}
      {!error && data && (
        <Stack gap="md">
          {stages.length === 0 ? (
            <Text size="sm" c="dimmed">
              No active filters. Apply a filter to see how it narrows the data.
            </Text>
          ) : (
            <>
              <Group justify="space-between" align="flex-end" wrap="wrap" gap="sm">
                <MultiSelect
                  size="xs"
                  label="Data collections"
                  placeholder="All"
                  style={{ flex: 1, minWidth: 220 }}
                  data={allDcIds.map((dc) => ({
                    value: dc,
                    label: dcLabels[dc] || dc.slice(0, 8),
                  }))}
                  value={visibleDcs ?? []}
                  onChange={(v) => setVisibleDcs(v.length === 0 ? null : v)}
                  clearable
                  searchable
                />
                <Stack gap={4}>
                  <Text size="xs" fw={500}>
                    Bar labels
                  </Text>
                  <SegmentedControl
                    size="xs"
                    value={labelMode}
                    onChange={(v) => setLabelMode(v as LabelMode)}
                    data={[
                      { value: 'value', label: 'Rows' },
                      { value: 'percent initial', label: '% of start' },
                      { value: 'percent previous', label: '% of previous' },
                    ]}
                  />
                </Stack>
              </Group>

              <Box style={{ width: '100%' }}>
                {/* `responsive: true` alone. Pairing it with react-plotly's
                    `useResizeHandler` gives the figure two independent resize
                    paths onto one width:100% container, which is the other
                    half of the relayout loop the fixed margin above avoids. */}
                <Plot
                  data={plotData as never}
                  layout={layout as never}
                  config={{ displayModeBar: false, responsive: true }}
                  style={{ width: '100%', height: chartHeight }}
                />
              </Box>

              <Stack gap={6}>
                <Group gap="xs" wrap="nowrap">
                  <Text size="sm" fw={600}>
                    Filter order
                  </Text>
                  <Text size="xs" c="dimmed" style={{ flex: 1, minWidth: 0 }}>
                    Reorder to see how the data narrows along a different path.
                    The last stage lands on the same rows either way.
                  </Text>
                  {reordered && (
                    <Tooltip label="Back to the order the filters were applied in" withArrow>
                      <ActionIcon
                        variant="subtle"
                        color="gray"
                        size="sm"
                        aria-label="Reset filter order"
                        onClick={() => setOrder([])}
                        data-testid="funnel-order-reset"
                      >
                        <Icon icon="bx:reset" width={14} height={14} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                </Group>
                <Stack gap={4}>
                  {orderedFilters.map((f, i) => {
                    const stage = stages[i];
                    const name =
                      stage?.label || stage?.column_name || f.column_name || String(f.index);
                    return (
                      <Group
                        key={String(f.index)}
                        gap="xs"
                        wrap="nowrap"
                        data-testid="funnel-order-row"
                      >
                        <Badge size="sm" variant="light" color="teal" circle>
                          {i + 1}
                        </Badge>
                        <Text size="sm" fw={500} truncate style={{ maxWidth: 200 }}>
                          {name}
                        </Text>
                        <Text size="xs" c="dimmed" truncate style={{ flex: 1, minWidth: 0 }}>
                          {formatValue(f.value)}
                        </Text>
                        <ActionIcon.Group>
                          <ActionIcon
                            variant="default"
                            size="sm"
                            aria-label={`Move ${name} earlier`}
                            disabled={i === 0}
                            onClick={() => moveStage(i, i - 1)}
                          >
                            <Icon icon="mdi:chevron-up" width={14} height={14} />
                          </ActionIcon>
                          <ActionIcon
                            variant="default"
                            size="sm"
                            aria-label={`Move ${name} later`}
                            disabled={i === orderedFilters.length - 1}
                            onClick={() => moveStage(i, i + 1)}
                          >
                            <Icon icon="mdi:chevron-down" width={14} height={14} />
                          </ActionIcon>
                        </ActionIcon.Group>
                      </Group>
                    );
                  })}
                </Stack>
              </Stack>

              <Text size="xs" c="dimmed">
                Row counts cover delta-backed data collections; cross-DC filters
                are translated through the project&apos;s links. MultiQC
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
