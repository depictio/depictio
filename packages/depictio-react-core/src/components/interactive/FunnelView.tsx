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
 * A second mode charts the values of one column instead of rows: pick a data
 * collection and a column, and each band shows how many distinct values of
 * that column survive the stage, and a values by stages matrix under the chart
 * shows which stage removed each value. Same request, plus `stage_column`.
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
 * body, refetched when it changes.
 *
 * Colors: DC traces take the categorical palette (the brand's colorway when
 * there is one), indexed by the DC's position in the full list so hiding one
 * does not recolor the rest. Stage badges and the column trace use the
 * grouping color; a stage projected from a saved group wears that group's own.
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
  Select,
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
  fetchPolarsSchema,
  FunnelStage,
  FunnelStageColumn,
  FunnelValuesResponse,
  InteractiveFilter,
} from '../../api';
import { applyLayoutTheme, plotlyThemeColors } from '../advanced_viz/plotlyTheme';
import { isFilterActive } from '../../activeFilters';
import { resolveCategoricalPalette, TAB10_PALETTE } from '../../colors';
import { useGroupingColor, type SelectionGroup } from '../../selectionGroups';
import {
  groupStageColor,
  resolveStageColumn,
  resolveStageDc,
  valuesHoverText,
} from './funnelStages';
import FunnelValuesMatrix, { type MatrixStage } from './FunnelValuesMatrix';

const formatValue = (value: unknown): string => {
  if (Array.isArray(value)) return value.map(String).join(', ');
  if (value === null || value === undefined) return '';
  return String(value);
};

/** A stage's short name: its component title, else its column. */
const stageName = (stage: FunnelStage, position: number): string =>
  stage.label || stage.column_name || `Filter ${position}`;

/** Label for one stage's y-band. Kept short on purpose: the y axis gets a
 *  fixed slice of the modal, and a wrapped 60-char label eats the plot. */
const stageLabel = (stage: FunnelStage, position: number): string => {
  const name = stageName(stage, position);
  const value = formatValue(stage.value);
  const short = value.length > 24 ? `${value.slice(0, 23)}…` : value;
  return short ? `${position}. ${name} = ${short}` : `${position}. ${name}`;
};

/** Left gutter reserved for the stage labels, in px. Sized for the longest
 *  label `stageLabel` can emit (a position, a column name and a 24-char value)
 *  so the chart never has to measure its own ticks. */
const STAGE_LABEL_GUTTER = 240;

type LabelMode = 'value' | 'percent initial' | 'percent previous';
type ChartMode = 'rows' | 'column';

const NO_GROUPS: SelectionGroup[] = [];

export interface FunnelViewProps {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  /** The shell's (debounced) filter list, the same one the components use. */
  filters: InteractiveFilter[];
  /** The dashboard's saved selection groups, so a stage projected from a
   *  group filter can be badged in that group's color. */
  groups?: SelectionGroup[];
}

const FunnelView: React.FC<FunnelViewProps> = ({
  opened,
  onClose,
  dashboardId,
  filters,
  groups = NO_GROUPS,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const groupingColor = useGroupingColor();

  const [data, setData] = useState<FunnelValuesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [labelMode, setLabelMode] = useState<LabelMode>('value');
  /** DC ids to chart. `null` means "all of them", which is also what we fall
   *  back to when the user clears the selection. */
  const [visibleDcs, setVisibleDcs] = useState<string[] | null>(null);
  /** User-chosen stage order, as component indexes. Empty = dashboard order. */
  const [order, setOrder] = useState<string[]>([]);
  const [mode, setMode] = useState<ChartMode>('rows');
  /** Column mode picks. `null` follows the defaults in `funnelStages`. */
  const [columnDc, setColumnDc] = useState<string | null>(null);
  const [columnName, setColumnName] = useState<string | null>(null);
  /** Schema of the DC column mode last looked at; `error` set when it failed. */
  const [schema, setSchema] = useState<{
    dcId: string;
    columns: string[];
    error: string | null;
  } | null>(null);

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

  // Column mode narrows `initial_rows_by_dc` to the one DC it charts, so the
  // full candidate list comes from `stage_dcs` whenever the server sends it.
  const allDcIds = useMemo(
    () => data?.stage_dcs ?? Object.keys(data?.initial_rows_by_dc ?? {}),
    [data],
  );

  const columnMode = mode === 'column';
  // Defaults follow the dashboard's own first filter, not the reordered one,
  // so reordering stages never swaps the column out from under the reader.
  const stageDc = useMemo(
    () => (columnMode ? resolveStageDc(columnDc, activeFilters[0], allDcIds) : null),
    [columnMode, columnDc, activeFilters, allDcIds],
  );

  // Refetched per DC switch and per reopen; the schema read is metadata only.
  useEffect(() => {
    if (!opened || !stageDc) return;
    let cancelled = false;
    fetchPolarsSchema(stageDc)
      .then((s) => {
        if (!cancelled) setSchema({ dcId: stageDc, columns: Object.keys(s), error: null });
      })
      .catch((err) => {
        if (!cancelled) {
          setSchema({
            dcId: stageDc,
            columns: [],
            error: err instanceof Error ? err.message : String(err),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [opened, stageDc]);

  const currentSchema = schema && schema.dcId === stageDc ? schema : null;
  const columns = currentSchema ? currentSchema.columns : null;

  const stageColumn = useMemo<FunnelStageColumn | null>(() => {
    if (!stageDc) return null;
    const name = resolveStageColumn(columnName, activeFilters[0], stageDc, columns);
    return name ? { dc_id: stageDc, column_name: name } : null;
  }, [stageDc, columnName, activeFilters, columns]);

  const requestKey = useMemo(
    () => JSON.stringify([orderedFilters.map((f) => [f.index, f.value]), stageColumn]),
    [orderedFilters, stageColumn],
  );

  // Column mode with no column resolvable before the schema lands: wait for
  // it instead of fetching a rows overview nobody is looking at.
  const awaitingColumn = columnMode && !!stageDc && !stageColumn && columns === null;

  useEffect(() => {
    if (!opened || awaitingColumn) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchFunnelValues(dashboardId, orderedFilters, [], true, controller.signal, stageColumn)
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
    // requestKey stands in for the orderedFilters and stageColumn identities.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, dashboardId, requestKey, awaitingColumn]);

  // A response answers one mode. Until the refetch after a mode switch lands,
  // the other mode's response must not be drawn as this one's.
  const columnData = data?.stage_column_status === 'ok' ? data : null;
  const rowsData = data && data.stage_column_status !== 'ok' ? data : null;

  const initialRows = useMemo(() => data?.initial_rows_by_dc ?? {}, [data]);
  const stages = useMemo(() => data?.stages ?? [], [data]);
  const dcLabels = useMemo(() => data?.dc_labels ?? {}, [data]);
  const dcLabel = useCallback((dc: string) => dcLabels[dc] || dc.slice(0, 8), [dcLabels]);

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

  const yLabels = useMemo(
    () => ['0. Unfiltered', ...stages.map((s, i) => stageLabel(s, i + 1))],
    [stages],
  );
  const textinfo = labelMode === 'value' ? 'value' : `value+${labelMode}`;
  const connectorColor = plotlyThemeColors(isDark, theme).gridColor;

  // One Plotly funnel trace per DC. `y` is shared across traces so the stages
  // line up in bands; `funnelmode: 'group'` then draws the DCs side by side
  // inside each band instead of stacking them into one misleading bar.
  const rowsPlot = useMemo(() => {
    if (!rowsData || chartedDcs.length === 0) return [];
    const palette = resolveCategoricalPalette(theme, TAB10_PALETTE);
    return chartedDcs.map((dc) => ({
      type: 'funnel' as const,
      name: dcLabel(dc),
      orientation: 'h' as const,
      y: yLabels,
      // A stage whose count failed to load comes back null; Plotly leaves a
      // gap for it rather than drawing a misleading zero.
      x: [initialRows[dc] ?? null, ...stages.map((s) => s.rows_by_dc[dc] ?? null)],
      textinfo,
      textposition: 'inside' as const,
      hovertemplate: '%{y}<br>%{x} rows<extra>%{fullData.name}</extra>',
      marker: { color: palette[allDcIds.indexOf(dc) % palette.length] },
      connector: { line: { color: connectorColor, width: 1 } },
    }));
  }, [rowsData, chartedDcs, allDcIds, yLabels, stages, initialRows, dcLabel, textinfo, theme, connectorColor]);

  // One trace: the distinct values of the chosen column at each stage. The
  // hover text is built per point because Plotly cannot list an array field.
  const columnPlot = useMemo(() => {
    if (!columnData) return [];
    const points = [columnData.initial_values ?? null, ...stages.map((s) => s.values ?? null)];
    // Plotly needs a paintable color, not a palette name: shade 6 reads on
    // white, shade 4 on the dark background.
    const shades = theme.colors[groupingColor] ?? theme.colors[theme.primaryColor];
    return [
      {
        type: 'funnel' as const,
        name: columnData.stage_column?.column_name ?? '',
        orientation: 'h' as const,
        y: yLabels,
        x: points.map((p) => p?.count ?? null),
        customdata: points.map((p) => valuesHoverText(p)),
        textinfo,
        textposition: 'inside' as const,
        hovertemplate: '%{y}<br>%{customdata}<extra></extra>',
        marker: { color: shades[isDark ? 4 : 6] },
        connector: { line: { color: connectorColor, width: 1 } },
      },
    ];
  }, [columnData, stages, yLabels, textinfo, groupingColor, theme, isDark, connectorColor]);

  // The matrix under the column chart. A stage's header color is looked up by
  // the stage's own filter index rather than its position, so a response still
  // in flight after a reorder keeps each header in its own group's color.
  const stageValues = useMemo(() => stages.map((s) => s.values ?? null), [stages]);
  const matrixStages = useMemo<MatrixStage[]>(() => {
    const byIndex = new Map(activeFilters.map((f) => [String(f.index), f]));
    return stages.map((s, i) => {
      const f = byIndex.get(String(s.index ?? '')) ?? orderedFilters[i];
      return {
        name: stageName(s, i + 1),
        label: yLabels[i + 1],
        color: (f ? groupStageColor(f, groups) : null) ?? groupingColor,
      };
    });
  }, [stages, activeFilters, orderedFilters, groups, groupingColor, yLabels]);

  const showLegend = !columnMode && chartedDcs.length > 1;
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
          showlegend: showLegend,
          legend: { orientation: 'h', y: -0.12 },
          funnelmode: 'group',
          plot_bgcolor: 'rgba(0,0,0,0)',
          paper_bgcolor: 'rgba(0,0,0,0)',
        },
        isDark,
        theme,
      ),
    [showLegend, isDark, theme],
  );

  // Each band needs a fixed slice of vertical space or the funnel collapses
  // into unreadable slivers once a dashboard applies more than three filters.
  const chartHeight = Math.max(260, 90 + (stages.length + 1) * 46);

  // What stands in for the column chart when it cannot be drawn.
  let columnNotice: React.ReactNode = null;
  if (columnMode) {
    if (currentSchema?.error) {
      columnNotice = (
        <Alert color="orange" title="Columns unavailable">
          {currentSchema.error}
        </Alert>
      );
    } else if (columns?.length === 0) {
      columnNotice = (
        <Text size="sm" c="dimmed">
          This data collection has no columns to chart.
        </Text>
      );
    } else if (!loading && data?.stage_column_status === 'unsupported') {
      columnNotice = (
        <Alert color="orange" title="Column not charted" data-testid="funnel-column-unsupported">
          This column cannot be charted for this data collection. Pick another one.
        </Alert>
      );
    }
  }
  const viewData = columnMode ? columnData : rowsData;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={
        <Group gap="xs">
          <Icon icon="mdi:filter-check-outline" width={18} height={18} />
          <Text fw={600}>Filter funnel</Text>
          {(loading || awaitingColumn) && data && <Loader size="xs" />}
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
              <SegmentedControl
                size="xs"
                value={mode}
                onChange={(v) => setMode(v as ChartMode)}
                data={[
                  { value: 'rows', label: 'Rows by data collection' },
                  { value: 'column', label: 'Values of a column' },
                ]}
                style={{ alignSelf: 'flex-start' }}
                data-testid="funnel-mode"
              />
              <Group justify="space-between" align="flex-end" wrap="wrap" gap="sm">
                {columnMode ? (
                  <Group gap="sm" align="flex-end" wrap="wrap" style={{ flex: 1, minWidth: 220 }}>
                    <Select
                      size="xs"
                      label="Data collection"
                      style={{ flex: 1, minWidth: 160 }}
                      data={allDcIds.map((dc) => ({ value: dc, label: dcLabel(dc) }))}
                      value={stageDc}
                      onChange={(v) => {
                        setColumnDc(v);
                        setColumnName(null);
                      }}
                      allowDeselect={false}
                      searchable
                      data-testid="funnel-column-dc"
                    />
                    <Select
                      size="xs"
                      label="Column"
                      style={{ flex: 1, minWidth: 160 }}
                      data={columns ?? []}
                      value={stageColumn?.column_name ?? null}
                      onChange={setColumnName}
                      placeholder={columns === null ? 'Loading columns…' : 'Pick a column'}
                      nothingFoundMessage="No matching column"
                      disabled={columns === null}
                      allowDeselect={false}
                      searchable
                      data-testid="funnel-column-name"
                    />
                  </Group>
                ) : (
                  <MultiSelect
                    size="xs"
                    label="Data collections"
                    placeholder="All"
                    style={{ flex: 1, minWidth: 220 }}
                    data={allDcIds.map((dc) => ({ value: dc, label: dcLabel(dc) }))}
                    value={visibleDcs ?? []}
                    onChange={(v) => setVisibleDcs(v.length === 0 ? null : v)}
                    clearable
                    searchable
                  />
                )}
                <Stack gap={4}>
                  <Text size="xs" fw={500}>
                    Bar labels
                  </Text>
                  <SegmentedControl
                    size="xs"
                    value={labelMode}
                    onChange={(v) => setLabelMode(v as LabelMode)}
                    data={[
                      { value: 'value', label: columnMode ? 'Values' : 'Rows' },
                      { value: 'percent initial', label: '% of start' },
                      { value: 'percent previous', label: '% of previous' },
                    ]}
                  />
                </Stack>
              </Group>

              {columnNotice ??
                (viewData ? (
                  <Box style={{ width: '100%' }}>
                    {/* `responsive: true` alone. Pairing it with react-plotly's
                        `useResizeHandler` gives the figure two independent resize
                        paths onto one width:100% container, which is the other
                        half of the relayout loop the fixed margin above avoids. */}
                    <Plot
                      data={(columnMode ? columnPlot : rowsPlot) as never}
                      layout={layout as never}
                      config={{ displayModeBar: false, responsive: true }}
                      style={{ width: '100%', height: chartHeight }}
                    />
                  </Box>
                ) : (
                  <Center style={{ height: chartHeight }}>
                    <Loader size="sm" />
                  </Center>
                ))}

              {!columnNotice && columnData && (
                <FunnelValuesMatrix
                  // A new column starts with an empty search.
                  key={`${columnData.stage_column?.dc_id}:${columnData.stage_column?.column_name}`}
                  columnName={columnData.stage_column?.column_name ?? ''}
                  initial={columnData.initial_values}
                  stageValues={stageValues}
                  stages={matrixStages}
                  accent={groupingColor}
                />
              )}

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
                        <Badge
                          size="sm"
                          variant="light"
                          color={groupStageColor(f, groups) ?? groupingColor}
                          circle
                        >
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
                {columnMode
                  ? 'Counts are the distinct non-null values of the column in one delta-backed data collection; cross-DC filters are translated through the project’s links.'
                  : 'Row counts cover delta-backed data collections; cross-DC filters are translated through the project’s links. MultiQC collections have no row table and are not charted here.'}
              </Text>
            </>
          )}
        </Stack>
      )}
    </Modal>
  );
};

export default FunnelView;
