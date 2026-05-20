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
  /** Full ordered list of ranks/columns the user can wire as steps. The
   *  in-viz Depth slider picks the prefix slice. When unset, the renderer
   *  falls back to ``step_cols`` (i.e. depth control becomes a no-op). */
  available_step_cols?: string[] | null;
  value_col?: string | null;
  /** Human label for the value column shown in hover tooltips. Defaults to
   *  the column name. Use for example "rel. abundance" when value_col is
   *  "abundance" but the units are fractions of 1. */
  value_label?: string | null;
  /** "fraction" → display value × 100% in hover. "count" → integer flow.
   *  "raw" (default) → just the number as-is. */
  value_format?: 'raw' | 'fraction' | 'count' | null;
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

  // Master list of step columns the user can choose from. Falls back to the
  // configured step_cols when the dashboard didn't supply an extended list,
  // so the depth slider degrades gracefully into a fixed-length step view.
  const allSteps = useMemo<string[]>(
    () =>
      Array.isArray(config.available_step_cols) && config.available_step_cols.length >= 2
        ? config.available_step_cols
        : config.step_cols || [],
    [config.available_step_cols, config.step_cols],
  );
  // Initial depth: prefer the configured step_cols length so dashboards can
  // override; otherwise fall back to 3 (a balanced default that picks the
  // first three ranks, e.g. Kingdom → Phylum → Class for taxonomy DCs).
  const [depth, setDepth] = useState<number>(
    Math.max(2, Math.min(allSteps.length, (config.step_cols || []).length || 3)),
  );
  const effectiveStepCols = useMemo<string[]>(() => allSteps.slice(0, depth), [allSteps, depth]);
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
    if (!metadata.wf_id || !metadata.dc_id || !effectiveStepCols.length) return;
    let cancelled = false;
    fetchAdvancedVizData(
      metadata.wf_id,
      metadata.dc_id,
      // Fetch the WHOLE possible-step universe, not just the depth-sliced
      // active prefix — so the step-filter MultiSelects keep working when the
      // user expands depth without a refetch.
      allSteps,
      filters,
      5000,
    )
      .then((res) => {
        if (cancelled) return;
        const opts: Record<string, string[]> = {};
        for (const col of allSteps) {
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
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(allSteps), JSON.stringify(filters), refreshTick]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Sankey: missing data binding');
      setLoading(false);
      return;
    }
    if (!effectiveStepCols || effectiveStepCols.length < 2) {
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
      step_cols: effectiveStepCols,
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
    JSON.stringify(effectiveStepCols),
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

    // Per-link total flow used as the denominator for the percentage shown
    // in the hover. Plotly's Sankey doesn't expose the trace total via
    // customdata, so we bake the share into the customdata array per link.
    const totalFlow = link.value.reduce((acc, v) => acc + (Number.isFinite(v) ? v : 0), 0) || 1;

    // Resolve the human-readable value-axis labels for the hover tooltip.
    // - When value_label is set in config we use it as-is.
    // - Otherwise fall back to value_col (when present) or the generic "flow".
    const valueAxisLabel = (config.value_label || config.value_col || 'flow') as string;
    const valueFormat = (config.value_format || 'raw') as 'raw' | 'fraction' | 'count';

    // Resolve the source / target step names from the server-supplied
    // step_cols. This makes the hover line read e.g.
    // "Phylum: Proteobacteria → Class: Gammaproteobacteria" instead of just
    // "Proteobacteria → Gammaproteobacteria" — much clearer when several
    // ranks have overlapping taxon names (Unclassified appears at every rank).
    const stepCols = result.step_cols;
    const sourceStepNames = link.source.map((s) => stepCols[nodes[s]?.step_index ?? 0] || '');
    const targetStepNames = link.target.map((t) => stepCols[nodes[t]?.step_index ?? 0] || '');

    // Pre-format values per the configured display mode so Plotly's
    // hovertemplate can read them directly. customdata layout:
    //   [0] source rank name
    //   [1] target rank name
    //   [2] formatted value string (e.g. "0.234" or "23.4%")
    //   [3] % of total flow (always pre-formatted to one decimal)
    const formatValue = (v: number): string => {
      if (!Number.isFinite(v)) return '—';
      if (valueFormat === 'count') return v.toLocaleString();
      if (valueFormat === 'fraction') return `${(v * 100).toFixed(2)}%`;
      // 'raw': adapt precision to magnitude so we don't print 0.0000 for
      // small abundance values or 12345.678 for absolute counts.
      return Math.abs(v) < 1 ? v.toFixed(4) : v.toFixed(2);
    };
    const linkCustomdata = link.value.map((v, i) => [
      sourceStepNames[i],
      targetStepNames[i],
      formatValue(v),
      ((v / totalFlow) * 100).toFixed(1),
    ]);

    const nodeLabels = showNodeLabels ? nodes.map((n) => n.label) : nodes.map(() => '');
    fig.data[0] = {
      ...trace,
      node: {
        ...(trace.node as object),
        label: nodeLabels,
        color: nodeColors,
        line: { color: isDark ? theme.colors.dark[5] : theme.colors.gray[0], width: 0.5 },
        // Per-node hover shows the rank → taxon and the total flow through
        // the node. Plotly substitutes `%{value}` with the summed in/out flow
        // it computed when laying out the trace.
        customdata: nodes.map((n) => [stepCols[n.step_index] || '']),
        hovertemplate:
          '<b>%{customdata[0]}: %{label}</b><br>' +
          `Total ${valueAxisLabel}: %{value}<extra></extra>`,
      },
      link: {
        ...link,
        color: linkColors,
        customdata: linkCustomdata,
        hovertemplate:
          '<b>%{customdata[0]}: %{source.label}</b> → ' +
          '<b>%{customdata[1]}: %{target.label}</b><br>' +
          `${valueAxisLabel}: %{customdata[2]}<br>` +
          'share of total flow: %{customdata[3]}%<extra></extra>',
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
  }, [
    result,
    palette,
    colorMode,
    linkOpacity,
    showNodeLabels,
    isDark,
    theme.colors,
    config.value_col,
    config.value_label,
    config.value_format,
  ]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        {/* Depth picker — SegmentedControl chosen over Slider because (a) the
            value set is tiny (2..available_step_cols.length, typically 2–6)
            and (b) Slider marks visually bleed into the SegmentedControl
            below it, making the popover layout confusing. Hidden entirely
            when the dashboard didn't supply an available_step_cols list
            longer than the configured step_cols. */}
        {allSteps.length > 2 ? (
          <Stack gap={4}>
            {/* Match Mantine's default input-label style (fw=500, size=xs)
                so this label visually aligns with the NumberInput / Switch /
                MultiSelect labels below in the same popover. */}
            <Text size="xs" fw={500}>
              Depth — {effectiveStepCols.join(' → ')}
            </Text>
            <SegmentedControl
              size="xs"
              fullWidth
              value={String(depth)}
              onChange={(v) => setDepth(Number(v))}
              data={Array.from({ length: allSteps.length - 1 }, (_, i) => {
                const n = i + 2;
                return { value: String(n), label: String(n) };
              })}
            />
          </Stack>
        ) : null}
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Sort nodes
          </Text>
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
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Colour links by
          </Text>
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
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
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
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Labels
          </Text>
          <Switch
            size="xs"
            checked={showNodeLabels}
            onChange={(e) => setShowNodeLabels(e.currentTarget.checked)}
            label="Show node labels"
          />
        </Stack>
        {effectiveStepCols.map((col) => (
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
      allSteps,
      depth,
      effectiveStepCols,
      sortMode,
      colorMode,
      linkOpacity,
      minLinkValue,
      showNodeLabels,
      stepFilters,
      stepOptions,
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
      dataColumns={effectiveStepCols}
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
