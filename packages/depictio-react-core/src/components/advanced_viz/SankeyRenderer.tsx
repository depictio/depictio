import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  MultiSelect,
  NumberInput,
  SegmentedControl,
  Slider,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  InteractiveFilter,
  SankeyResult,
  StoredMetadata,
  dispatchSankey,
  fetchAdvancedVizData,
  pollSankey,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme } from './plotlyTheme';

interface SankeyConfig {
  step_cols: string[];
  value_col?: string | null;
  sort_mode?: 'alphabetical' | 'total_flow' | 'input';
  color_mode?: 'source' | 'target' | 'step';
  link_opacity?: number;
  min_link_value?: number;
  show_node_labels?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SankeyConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

function hexWithAlpha(hex: string, alpha: number): string {
  // Mantine palette entries are 7-char hex literals (#rrggbb). Append the alpha
  // byte as two hex chars so Plotly's link colour accepts opacity per-link.
  const a = Math.max(0, Math.min(255, Math.round(alpha * 255)))
    .toString(16)
    .padStart(2, '0');
  return `${hex}${a}`;
}

const SankeyRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const config = (metadata.config || {}) as SankeyConfig;
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const [sortMode, setSortMode] = useState<NonNullable<SankeyConfig['sort_mode']>>(
    config.sort_mode ?? 'total_flow',
  );
  const [colorMode, setColorMode] = useState<NonNullable<SankeyConfig['color_mode']>>(
    config.color_mode ?? 'source',
  );
  const [linkOpacity, setLinkOpacity] = useState<number>(config.link_opacity ?? 0.5);
  const [minLinkValue, setMinLinkValue] = useState<number>(config.min_link_value ?? 0);
  const [showNodeLabels, setShowNodeLabels] = useState<boolean>(config.show_node_labels ?? true);
  const [stepFilters, setStepFilters] = useState<Record<string, string[]>>({});

  const [result, setResult] = useState<SankeyResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [computeStatus, setComputeStatus] = useState<string | null>(null);
  const [computeMs, setComputeMs] = useState<number | null>(null);
  const [dataRows, setDataRows] = useState<Record<string, unknown[]> | null>(null);

  // Step-filter options come from the underlying DC (server-side aggregation
  // would otherwise drop unselected values before we could list them). One
  // /data fetch is enough to populate every step's MultiSelect.
  const [stepOptions, setStepOptions] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !config.step_cols?.length) return;
    let cancelled = false;
    fetchAdvancedVizData(
      metadata.wf_id,
      metadata.dc_id,
      config.step_cols,
      filters,
      5000,
    )
      .then((res) => {
        if (cancelled) return;
        const opts: Record<string, string[]> = {};
        for (const col of config.step_cols) {
          const vals = (res.rows[col] as unknown[]) || [];
          opts[col] = Array.from(new Set(vals.map((v) => String(v ?? '')))).sort();
        }
        setStepOptions(opts);
        setDataRows(res.rows);
      })
      .catch(() => {
        /* options are best-effort; popover MultiSelects stay empty */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(config.step_cols), JSON.stringify(filters), refreshTick]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Sankey: missing data binding');
      setLoading(false);
      return;
    }
    if (!config.step_cols || config.step_cols.length < 2) {
      setError('Sankey: ≥2 step columns required');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setComputeStatus('Aggregating flow…');
    setComputeMs(null);

    const payload = {
      wf_id: metadata.wf_id,
      dc_id: metadata.dc_id,
      step_cols: config.step_cols,
      value_col: config.value_col ?? null,
      sort_mode: sortMode,
      min_link_value: minLinkValue,
      step_filters: Object.fromEntries(
        Object.entries(stepFilters).filter(([, v]) => v.length > 0),
      ),
      filter_metadata: filters,
    };

    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    const accept = (r: SankeyResult) => {
      if (cancelled) return;
      setResult(r);
      setComputeMs(r.compute_ms ?? null);
      setComputeStatus(null);
      setLoading(false);
    };

    dispatchSankey(payload)
      .then((job) => {
        if (cancelled) return;
        if (job.status === 'done' && job.result) {
          accept(job.result);
          return;
        }
        if (job.status === 'failed') {
          setError(job.error || 'Compute task failed');
          setLoading(false);
          return;
        }
        const tick = async () => {
          if (cancelled) return;
          try {
            const status = await pollSankey(job.job_id);
            if (cancelled) return;
            if (status.status === 'done' && status.result) accept(status.result);
            else if (status.status === 'failed') {
              setError(status.error || 'Compute task failed');
              setLoading(false);
            } else pollTimer = setTimeout(tick, 1000);
          } catch (err) {
            if (!cancelled) {
              setError(err instanceof Error ? err.message : String(err));
              setLoading(false);
            }
          }
        };
        pollTimer = setTimeout(tick, 400);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(filters),
    refreshTick,
    JSON.stringify(config.step_cols),
    config.value_col,
    sortMode,
    minLinkValue,
    JSON.stringify(stepFilters),
  ]);

  /** Categorical palette pulled from Mantine theme — same swatches used by the
   *  Coverage track renderer so the two viz feel consistent in either scheme. */
  const palette = useMemo<string[]>(
    () => [
      theme.colors.blue[5],
      theme.colors.orange[5],
      theme.colors.green[5],
      theme.colors.grape[5],
      theme.colors.teal[5],
      theme.colors.red[5],
      theme.colors.violet[5],
      theme.colors.yellow[7],
      theme.colors.cyan[5],
      theme.colors.pink[5],
      theme.colors.lime[6],
      theme.colors.indigo[5],
    ],
    [theme.colors],
  );

  // Client-side recolour + opacity tweak on the server-built sankey figure.
  // Re-running the celery task for a colour pick would be wasted work — we
  // already have the full node + link metadata.
  const figureSpec = useMemo<{ data: unknown[]; layout: Record<string, unknown> } | null>(() => {
    if (!result) return null;
    const nodes = result.nodes;
    const fig = JSON.parse(JSON.stringify(result.figure)) as {
      data: Array<Record<string, unknown>>;
      layout: Record<string, unknown>;
    };
    const trace = fig.data[0] ?? {};
    const link = (trace.link as { source: number[]; target: number[]; value: number[] } | undefined) ?? {
      source: [],
      target: [],
      value: [],
    };

    // Step-colour map keyed by node step_index so each level gets a distinct
    // tint when colorMode='step'. Nodes within a step share a hue.
    const stepHues = result.step_cols.map((_, i) => palette[i % palette.length]);
    const nodeColors = nodes.map((n, i) => {
      if (colorMode === 'step') return stepHues[n.step_index] ?? palette[0];
      // 'source' and 'target' both fall back to a per-node hash when colouring
      // nodes themselves — Plotly only uses link.color for actual flows. We
      // keep node colours stable across modes for visual continuity.
      return palette[i % palette.length];
    });

    function baseColorFor(src: number, tgt: number): string {
      if (colorMode === 'step') return stepHues[nodes[src]?.step_index ?? 0] ?? palette[0];
      const idx = colorMode === 'target' ? tgt : src;
      return palette[idx % palette.length];
    }

    const linkColors = link.source.map((src, i) =>
      hexWithAlpha(baseColorFor(src, link.target[i]), linkOpacity),
    );

    const nodeLabels = showNodeLabels ? nodes.map((n) => n.label) : nodes.map(() => '');
    fig.data[0] = {
      ...trace,
      node: {
        ...(trace.node as object),
        label: nodeLabels,
        color: nodeColors,
        line: { color: isDark ? theme.colors.dark[5] : theme.colors.gray[0], width: 0.5 },
      },
      link: {
        ...link,
        color: linkColors,
        hovertemplate: '%{source.label} → %{target.label}<br>flow %{value}<extra></extra>',
      },
    };

    return {
      data: fig.data,
      layout: {
        ...fig.layout,
        template: isDark ? 'plotly_dark' : 'plotly_white',
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
        autosize: true,
        font: {
          size: 12,
          color: isDark ? theme.colors.gray[2] : theme.colors.gray[8],
        },
      },
    };
  }, [result, palette, colorMode, linkOpacity, showNodeLabels, isDark, theme.colors]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <SegmentedControl
          size="xs"
          fullWidth
          value={sortMode}
          onChange={(v) => setSortMode(v as typeof sortMode)}
          data={[
            { value: 'total_flow', label: 'By flow' },
            { value: 'alphabetical', label: 'A–Z' },
            { value: 'input', label: 'Input' },
          ]}
        />
        <SegmentedControl
          size="xs"
          fullWidth
          value={colorMode}
          onChange={(v) => setColorMode(v as typeof colorMode)}
          data={[
            { value: 'source', label: 'Source' },
            { value: 'target', label: 'Target' },
            { value: 'step', label: 'Step' },
          ]}
        />
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            Link opacity
          </Text>
          <Slider
            size="xs"
            value={linkOpacity}
            onChange={setLinkOpacity}
            min={0.1}
            max={1}
            step={0.05}
            label={(v) => v.toFixed(2)}
          />
        </Stack>
        <NumberInput
          size="xs"
          label="Min link value"
          value={minLinkValue}
          onChange={(v) => setMinLinkValue(Math.max(0, Number(v) || 0))}
          min={0}
          step={1}
        />
        <Switch
          size="xs"
          checked={showNodeLabels}
          onChange={(e) => setShowNodeLabels(e.currentTarget.checked)}
          label="Show node labels"
        />
        {(config.step_cols || []).map((col) => (
          <MultiSelect
            key={col}
            size="xs"
            label={col}
            value={stepFilters[col] ?? []}
            onChange={(v) => setStepFilters((prev) => ({ ...prev, [col]: v }))}
            data={(stepOptions[col] ?? []).map((s) => ({ value: s, label: s }))}
            placeholder={stepOptions[col]?.length ? 'All values' : 'Loading…'}
            searchable
            clearable
          />
        ))}
        {computeStatus ? (
          <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
            {computeStatus}
          </Badge>
        ) : null}
        {computeMs != null && !computeStatus && result ? (
          <Text size="xs" c="dimmed">
            Built in {computeMs} ms ({result.node_count} nodes / {result.link_count} links)
          </Text>
        ) : null}
      </Stack>
    ),
    [
      sortMode,
      colorMode,
      linkOpacity,
      minLinkValue,
      showNodeLabels,
      stepFilters,
      stepOptions,
      config.step_cols,
      computeStatus,
      computeMs,
      result,
    ],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Categorical flow'}
      subtitle={(metadata as { description?: string; subtitle?: string }).description}
      controls={controls}
      loading={loading}
      error={error}
      dataRows={dataRows ?? undefined}
      dataColumns={config.step_cols}
    >
      {figureSpec ? (
        <Plot
          data={applyDataTheme(figureSpec.data, isDark, theme) as any}
          layout={
            applyLayoutTheme(
              { ...(figureSpec.layout as any), width: undefined, height: undefined, autosize: true },
              isDark,
              theme,
            ) as any
          }
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default SankeyRenderer;
