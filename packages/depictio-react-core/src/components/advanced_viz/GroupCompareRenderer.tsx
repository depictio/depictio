import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Group,
  ScrollArea,
  Stack,
  Table,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  dispatchGroupCompare,
  fetchUniqueValues,
  GroupCompareResult,
  InteractiveFilter,
  pollGroupCompare,
  StoredMetadata,
} from '../../api';
import type { GroupRenderState } from '../../selectionGroups';
import { adaptGlTrace, SVG_MAX_POINTS, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame, { TIER_COLORS } from './AdvancedVizFrame';
import { VizControlGroup, VizNumberInput, VizSelect, VizSwitch } from './controls/VizControls';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';
import { createAutoRunGate } from './group_compare/autoRun';
import {
  configuredGroupPair,
  groupCompareOptions,
  LABEL_VALUE_SOURCE,
  SAVED_GROUP_SOURCE,
  selectorFor,
} from './group_compare/groupOptions';
import { negLog10, tierCounts, topLabelIndices, volcanoPoints } from './group_compare/volcanoSpec';

interface GroupCompareConfig {
  index_col?: string;
  group_col?: string | null;
  test?: 'wilcoxon' | 't_test';
  log_transform?: boolean;
  max_features?: number;
  min_observations?: number;
  fdr_threshold?: number;
  log2fc_threshold?: number;
  top_n_labels?: number;
  default_group_a?: string | null;
  default_group_b?: string | null;
  auto_run?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: GroupCompareConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** The dashboard's saved selection groups. Not a colouring override here:
   *  for this kind the groups ARE the input, so they become the first source
   *  the two pickers offer. They reach the renderer whenever the dashboard's
   *  "Color by" is on the groups; the label column is what the comparison
   *  falls back to otherwise. */
  groupRender?: GroupRenderState;
}

/** Rows of the marker table under the volcano. Enough to read the top of the
 *  ranking at a glance; the whole result is in the Show-data popover. */
const TABLE_ROWS = 20;

/** Poll cadence, matching the other Celery-backed renderers: a short first
 *  wait, because a comparison of a showcase-sized matrix is usually done by
 *  then, and a longer one after. */
const FIRST_POLL_MS = 800;
const POLL_MS = 1500;

/** The whole result, column-oriented, for the frame's Show-data popover. */
const DATA_COLUMNS = ['feature', 'mean_a', 'mean_b', 'log2fc', 'p_value', 'fdr'];

type RunState =
  | { phase: 'idle' }
  | { phase: 'queued' }
  | { phase: 'running' }
  | { phase: 'done'; key: string; fromCache: boolean }
  | { phase: 'failed'; message: string };

const GroupCompareRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, groupRender }) => {
  const config = (metadata.config || {}) as GroupCompareConfig;
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';

  const indexCol = config.index_col || 'index';
  const groupCol = config.group_col || null;
  const maxFeatures = config.max_features ?? 2000;
  const minObservations = config.min_observations ?? 3;

  // Statistic tunables. `test` and the transform change what the server
  // computes, so they invalidate the result; the two thresholds and the label
  // budget only change how the finished rows are read, and are applied
  // client-side without a fresh job.
  const [test, setTest] = usePersistedVizControl<'wilcoxon' | 't_test'>(metadata, 'test', 'wilcoxon');
  const [logTransform, setLogTransform] = usePersistedVizControl(metadata, 'log_transform', true);
  const [fdrThreshold, setFdrThreshold] = usePersistedVizControl(metadata, 'fdr_threshold', 0.05);
  const [log2fcThreshold, setLog2fc] = usePersistedVizControl(metadata, 'log2fc_threshold', 1.0);
  const [topN, setTopN] = usePersistedVizControl(metadata, 'top_n_labels', 20);

  // Distinct values of the label column, so the pickers can offer them. Read
  // unfiltered on purpose: a reader who narrowed the dashboard to one cluster
  // should still see which two clusters the comparison could be between, and
  // the dashboard's filters are applied to the rows the job loads either way.
  const [labelValues, setLabelValues] = useState<string[]>([]);
  useEffect(() => {
    if (!metadata.dc_id || !groupCol) {
      setLabelValues([]);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, groupCol)
      .then((values) => {
        if (!cancelled) setLabelValues(values);
      })
      .catch(() => {
        // Best effort: with no label values the saved groups are still offered.
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, groupCol]);

  const options = useMemo(
    () => groupCompareOptions(groupRender?.groups, groupCol, labelValues),
    [groupRender?.groups, groupCol, labelValues],
  );

  const [pickA, setPickA] = useState<string | null>(null);
  const [pickB, setPickB] = useState<string | null>(null);
  // Seeded from the options rather than persisted: which two groups to
  // compare is a question about this reader's session, and a lasso one person
  // saved does not exist in another viewer's dashboard. The config's
  // `default_group_a` / `default_group_b` name the pair a dashboard author
  // wants the tile to open on; a reader's own pick survives new options.
  const defaultA = config.default_group_a ?? null;
  const defaultB = config.default_group_b ?? null;
  useEffect(() => {
    const known = new Set(options.map((o) => o.value));
    const [a, b] = configuredGroupPair(options, defaultA, defaultB);
    setPickA((prev) => (prev && known.has(prev) ? prev : a));
    setPickB((prev) => (prev && known.has(prev) ? prev : b));
  }, [options, defaultA, defaultB]);

  const selectorA = useMemo(() => selectorFor(options, pickA), [options, pickA]);
  const selectorB = useMemo(() => selectorFor(options, pickB), [options, pickB]);

  // Everything the server hashes into its cache key. A result computed for a
  // different key is stale: still shown, but with the Compare button asking
  // for it again rather than silently passing off the previous answer.
  const filterSig = JSON.stringify(filters);
  const requestKey = useMemo(
    () =>
      JSON.stringify({
        dc: metadata.dc_id,
        a: selectorA,
        b: selectorB,
        test,
        logTransform,
        indexCol,
        maxFeatures,
        minObservations,
        filterSig,
        refreshTick,
      }),
    [
      metadata.dc_id,
      selectorA,
      selectorB,
      test,
      logTransform,
      indexCol,
      maxFeatures,
      minObservations,
      filterSig,
      refreshTick,
    ],
  );

  const [result, setResult] = useState<GroupCompareResult | null>(null);
  const [run, setRun] = useState<RunState>({ phase: 'idle' });
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Bumped on every dispatch and on unmount, so a poll that comes back after
  // the reader changed their mind lands on a stale token and is dropped.
  const runToken = useRef(0);
  // `auto_run`: at most one dispatch per request key per mount (see autoRun.ts).
  const autoRun = config.auto_run ?? false;
  const autoGate = useRef(createAutoRunGate());

  useEffect(
    () => () => {
      runToken.current += 1;
      autoGate.current.reset();
      if (pollTimer.current) clearTimeout(pollTimer.current);
    },
    [],
  );

  const sameSelection = pickA !== null && pickA === pickB;
  const canRun =
    Boolean(metadata.wf_id && metadata.dc_id && selectorA && selectorB) && !sameSelection;
  const stale = run.phase === 'done' && run.key !== requestKey;

  const compare = useCallback(() => {
    if (!canRun || !selectorA || !selectorB || !metadata.wf_id || !metadata.dc_id) return;
    const token = (runToken.current += 1);
    const key = requestKey;
    if (pollTimer.current) clearTimeout(pollTimer.current);
    setRun({ phase: 'queued' });

    const accept = (payload: GroupCompareResult, fromCache: boolean) => {
      if (runToken.current !== token) return;
      setResult(payload);
      setRun({ phase: 'done', key, fromCache });
    };
    const fail = (message: string) => {
      if (runToken.current !== token) return;
      setRun({ phase: 'failed', message });
    };

    dispatchGroupCompare({
      wf_id: metadata.wf_id,
      dc_id: metadata.dc_id,
      index_col: indexCol,
      group_a: selectorA,
      group_b: selectorB,
      test,
      log_transform: logTransform,
      max_features: maxFeatures,
      min_observations: minObservations,
      fdr_threshold: fdrThreshold,
      log2fc_threshold: log2fcThreshold,
      top_n_labels: topN,
      filter_metadata: filters,
    })
      .then((job) => {
        if (runToken.current !== token) return;
        if (job.status === 'done' && job.result) {
          accept(job.result, Boolean(job.from_cache));
          return;
        }
        if (job.status === 'failed') {
          fail(job.error || 'The comparison failed');
          return;
        }
        setRun({ phase: 'running' });
        const tick = async () => {
          if (runToken.current !== token) return;
          try {
            const status = await pollGroupCompare(job.job_id);
            if (runToken.current !== token) return;
            if (status.status === 'done' && status.result) accept(status.result, false);
            else if (status.status === 'failed') fail(status.error || 'The comparison failed');
            else pollTimer.current = setTimeout(tick, POLL_MS);
          } catch (err) {
            fail(err instanceof Error ? err.message : String(err));
          }
        };
        pollTimer.current = setTimeout(tick, FIRST_POLL_MS);
      })
      .catch((err: unknown) => fail(err instanceof Error ? err.message : String(err)));
  }, [
    canRun,
    selectorA,
    selectorB,
    metadata.wf_id,
    metadata.dc_id,
    indexCol,
    test,
    logTransform,
    maxFeatures,
    minObservations,
    fdrThreshold,
    log2fcThreshold,
    topN,
    filters,
    requestKey,
  ]);

  // Read through a ref so the effect below fires on the request key alone: a
  // threshold or label-budget change re-renders `compare` but must not queue
  // a job, since the server's answer would be the same rows.
  const compareRef = useRef(compare);
  compareRef.current = compare;
  useEffect(() => {
    if (autoGate.current.claim(requestKey, autoRun, canRun)) compareRef.current();
  }, [autoRun, canRun, requestKey]);

  const points = useMemo(
    () => (result ? volcanoPoints(result.rows, fdrThreshold, log2fcThreshold) : []),
    [result, fdrThreshold, log2fcThreshold],
  );
  const counts = useMemo(() => (result ? tierCounts(points) : undefined), [result, points]);
  const glGranted = useWebglSlot(points.length > SVG_MAX_POINTS);

  const figure = useMemo(() => {
    if (!result || points.length === 0) return null;
    const labelled = topLabelIndices(points, topN);
    const axis = plotlyAxisOverrides(isDark, theme);
    const rule = { dash: 'dot' as const, color: axis.zerolinecolor, width: 1 };
    const sigLine = negLog10(fdrThreshold);

    return {
      data: [
        adaptGlTrace(
          {
            type: 'scattergl' as const,
            mode: 'markers' as const,
            x: points.map((p) => p.x),
            y: points.map((p) => p.y),
            text: points.map((p) => p.feature),
            customdata: points.map((p) => [p.tier, p.pValue, p.fdr, p.meanA, p.meanB]),
            hovertemplate:
              '<b>%{text}</b> [%{customdata[0]}]' +
              '<br>log2FC: %{x:.3f}' +
              '<br>p: %{customdata[1]:.2e}   FDR: %{customdata[2]:.2e}' +
              `<br>mean ${result.group_a.label}: %{customdata[3]:.3f}` +
              `<br>mean ${result.group_b.label}: %{customdata[4]:.3f}` +
              '<extra></extra>',
            marker: {
              color: points.map((p) => theme.colors[TIER_COLORS[p.tier] || 'gray'][6]),
              size: points.map((p) => (p.tier === 'NS' ? 5 : 8)),
              opacity: 0.85,
            },
          },
          glGranted,
        ),
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 54, r: 16, t: 12, b: 44 },
        xaxis: {
          ...axis,
          title: { text: `log2 fold change (${result.group_a.label} / ${result.group_b.label})` },
          zeroline: true,
        },
        yaxis: { ...axis, title: { text: '-log10(FDR)' } },
        shapes: [
          ...(log2fcThreshold > 0
            ? [-log2fcThreshold, log2fcThreshold].map((x) => ({
                type: 'line' as const,
                x0: x,
                x1: x,
                yref: 'paper' as const,
                y0: 0,
                y1: 1,
                line: rule,
              }))
            : []),
          {
            type: 'line' as const,
            xref: 'paper' as const,
            x0: 0,
            x1: 1,
            y0: sigLine,
            y1: sigLine,
            line: rule,
          },
        ],
        annotations: points
          .map((p, i) =>
            labelled.has(i)
              ? {
                  x: p.x,
                  y: p.y,
                  text: p.feature,
                  showarrow: true,
                  arrowhead: 0,
                  arrowwidth: 0.6,
                  arrowcolor: axis.zerolinecolor,
                  ax: 0,
                  ay: -16,
                  font: { size: 10 },
                }
              : null,
          )
          .filter(Boolean),
        showlegend: false,
        autosize: true,
      },
    };
  }, [result, points, topN, fdrThreshold, log2fcThreshold, isDark, theme, glGranted]);

  const tableRows = useMemo(() => points.slice(0, TABLE_ROWS), [points]);

  const dataRows = useMemo(() => {
    if (!result) return undefined;
    return {
      feature: result.rows.map((r) => r.feature),
      mean_a: result.rows.map((r) => r.mean_a),
      mean_b: result.rows.map((r) => r.mean_b),
      log2fc: result.rows.map((r) => r.log2fc),
      p_value: result.rows.map((r) => r.p_value),
      fdr: result.rows.map((r) => r.fdr),
    } as Record<string, unknown[]>;
  }, [result]);
  const tierAnnotation = useMemo(
    () =>
      result
        ? { values: points.map((p) => p.tier), selectedOrder: ['UP', 'DN'], columnLabel: 'tier' }
        : undefined,
    [result, points],
  );

  const selectData = useMemo(
    () =>
      [SAVED_GROUP_SOURCE, LABEL_VALUE_SOURCE]
        .map((source) => ({
          group: source,
          items: options
            .filter((o) => o.source === source)
            .map((o) => ({ value: o.value, label: o.label })),
        }))
        .filter((g) => g.items.length > 0),
    [options],
  );

  // Encoding tier: the two groups and the test are what the result IS, so
  // they sit in the header when the tile asks for `controls_placement:
  // header`. The transform and the two thresholds refine it and live in the
  // settings tier with the label budget.
  const primaryControls = useMemo(
    () => (
      <>
        <VizControlGroup title="Comparison">
          <VizSelect
            label="Group A"
            placeholder="Pick a group"
            value={pickA}
            onChange={setPickA}
            data={selectData}
            searchable
            data-testid="group-compare-pick-a"
          />
          <VizSelect
            label="Group B"
            placeholder="Pick a group"
            value={pickB}
            onChange={setPickB}
            data={selectData}
            searchable
            data-testid="group-compare-pick-b"
          />
          <VizSelect
            label="Test"
            value={test}
            onChange={(v) => v && setTest(v as 'wilcoxon' | 't_test')}
            data={[
              { value: 'wilcoxon', label: 'Wilcoxon rank-sum' },
              { value: 't_test', label: 'Welch t-test' },
            ]}
          />
        </VizControlGroup>
      </>
    ),
    [pickA, pickB, selectData, test],
  );

  const controls = useMemo(
    () => (
      <>
        <VizControlGroup title="Thresholds">
          <VizSwitch
            checked={logTransform}
            onChange={(e) => setLogTransform(e.currentTarget.checked)}
            label="log1p before testing"
          />
          <VizNumberInput
            label="FDR threshold"
            value={fdrThreshold}
            onChange={(v) => setFdrThreshold(Math.min(0.999, Math.max(0.0001, Number(v) || 0.05)))}
            step={0.01}
            min={0.0001}
            max={0.999}
            decimalScale={4}
          />
          <VizNumberInput
            label="|log2FC| threshold"
            value={log2fcThreshold}
            onChange={(v) => setLog2fc(Math.max(0, Number(v) || 0))}
            step={0.25}
            min={0}
            decimalScale={2}
          />
        </VizControlGroup>
        <VizControlGroup title="Labels">
          <VizNumberInput
            label="Top-N labels"
            value={topN}
            onChange={(v) => setTopN(Math.max(0, Math.min(200, Number(v) || 0)))}
            min={0}
            max={200}
          />
        </VizControlGroup>
      </>
    ),
    [logTransform, fdrThreshold, log2fcThreshold, topN],
  );

  // The one line under the title: which two groups are being compared, and how
  // many observations each side actually contributed.
  const pickedLabelA = useMemo(() => selectorA?.label ?? null, [selectorA]);
  const pickedLabelB = useMemo(() => selectorB?.label ?? null, [selectorB]);
  const echo = useMemo(() => {
    if (result) {
      const overlap = result.overlap_dropped
        ? `, ${result.overlap_dropped} in both dropped`
        : '';
      return (
        `A: ${result.group_a.label} (n=${result.group_a.n}) vs ` +
        `B: ${result.group_b.label} (n=${result.group_b.n})${overlap}`
      );
    }
    return pickedLabelA && pickedLabelB ? `A: ${pickedLabelA} vs B: ${pickedLabelB}` : undefined;
  }, [result, pickedLabelA, pickedLabelB]);

  const status = useMemo(() => {
    if (run.phase === 'queued') return { color: 'grape', text: 'Queued' };
    if (run.phase === 'running') return { color: 'grape', text: 'Running' };
    if (run.phase === 'failed') return { color: 'red', text: run.message };
    if (stale) return { color: 'orange', text: 'Settings changed, compare again' };
    if (run.phase === 'done' && result) {
      const where = run.fromCache ? 'cached' : `${result.compute_ms ?? 0} ms`;
      return {
        color: 'gray',
        text:
          `${result.group_a.n} vs ${result.group_b.n} observations, ` +
          `${result.tested_features} of ${result.feature_count} features, ${where}`,
      };
    }
    if (!canRun) {
      return {
        color: 'gray',
        text: sameSelection
          ? 'Pick two different groups'
          : 'Save two selection groups, or bind a label column',
      };
    }
    return { color: 'gray', text: 'Ready' };
  }, [run, stale, result, canRun, sameSelection]);

  const busy = run.phase === 'queued' || run.phase === 'running';

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Group comparison'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      echo={echo}
      loading={false}
      error={null}
      dataRows={dataRows}
      dataColumns={DATA_COLUMNS}
      counts={counts}
      tierAnnotation={tierAnnotation}
    >
      <Stack gap="xs" style={{ height: '100%' }}>
        <Group gap="xs" wrap="nowrap">
          <Badge size="sm" color={status.color} variant="light" radius="sm">
            {status.text}
          </Badge>
          {!autoRun || run.phase === 'failed' || stale ? (
            <Button size="xs" variant="light" onClick={compare} disabled={!canRun} loading={busy}>
              Compare
            </Button>
          ) : null}
        </Group>

        <div style={{ flex: '1 1 auto', minHeight: 140, position: 'relative' }}>
          {figure ? (
            <Plot
              data={applyDataTheme(figure.data, isDark, theme) as any}
              layout={applyLayoutTheme(figure.layout as any, isDark, theme) as any}
              useResizeHandler
              style={{ width: '100%', height: '100%' }}
              config={{ displaylogo: false, responsive: true } as any}
            />
          ) : busy ? (
            <Text size="sm" c="dimmed">
              Comparing {pickedLabelA} with {pickedLabelB} on the server. The first run of a
              comparison takes a few seconds; the result is cached, so reopening this tab or
              picking the same two groups again is instant.
            </Text>
          ) : (
            <Stack gap={6} maw={560} data-testid="group-compare-empty">
              <Text size="sm" fw={500}>
                What this tile compares
              </Text>
              <Text size="sm" c="dimmed">
                Group A and group B are two sets of rows (cells, samples) of this table. Every
                numeric column is tested between them, one test per feature, and drawn as effect
                size against significance: a positive log2 fold change means higher in A. Pick
                the two groups in the Group A and Group B menus (tile header, or the settings
                popover)
                {autoRun ? '; the comparison then runs by itself.' : ', then press Compare.'}
              </Text>
              <Text size="sm" c="dimmed">
                A group is either a value of the {groupCol ? `"${groupCol}" ` : ''}label column
                (a cluster, a condition), or a selection saved from another tile: lasso or
                box-select points on a scatter or embedding, then save the selection as a group
                from the Analysis panel. Saved groups are listed first in both menus.
              </Text>
            </Stack>
          )}
        </div>

        {tableRows.length > 0 && result ? (
          <ScrollArea style={{ flex: '0 0 auto', maxHeight: 200 }} type="auto">
            <Table striped highlightOnHover fz="xs" stickyHeader>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Feature</Table.Th>
                  <Table.Th ta="right">mean {result.group_a.label}</Table.Th>
                  <Table.Th ta="right">mean {result.group_b.label}</Table.Th>
                  <Table.Th ta="right">log2FC</Table.Th>
                  <Table.Th ta="right">p</Table.Th>
                  <Table.Th ta="right">FDR</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {tableRows.map((p) => (
                  <Table.Tr key={p.feature}>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <Badge
                          size="xs"
                          radius="sm"
                          variant="light"
                          color={TIER_COLORS[p.tier] || 'gray'}
                        >
                          {p.tier}
                        </Badge>
                        {p.feature}
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right">{fixed(p.meanA)}</Table.Td>
                    <Table.Td ta="right">{fixed(p.meanB)}</Table.Td>
                    <Table.Td ta="right">{fixed(p.x)}</Table.Td>
                    <Table.Td ta="right">{scientific(p.pValue)}</Table.Td>
                    <Table.Td ta="right">{scientific(p.fdr)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        ) : null}
      </Stack>
    </AdvancedVizFrame>
  );
};

function fixed(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? '-' : value.toFixed(3);
}

function scientific(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  return value >= 0.001 ? value.toFixed(4) : value.toExponential(2);
}

export default GroupCompareRenderer;
