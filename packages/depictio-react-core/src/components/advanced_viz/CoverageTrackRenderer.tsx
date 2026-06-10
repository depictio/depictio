import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  MultiSelect,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  CoverageTrackResult,
  InteractiveFilter,
  StoredMetadata,
  dispatchCoverageTrack,
  pollCoverageTrack,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme } from './plotlyTheme';
import { GenomeAnnotation, resolveAnnotation } from './genome_annotations';

interface CoverageTrackConfig {
  chromosome_col: string;
  position_col: string;
  value_col: string;
  end_col?: string | null;
  sample_col?: string | null;
  category_col?: string | null;
  y_scale?: 'linear' | 'log';
  smoothing_window?: number;
  color_by?: 'single' | 'category' | 'sample';
  show_annotation_lane?: boolean;
  /** Persisted initial view mode. When set, skips sample-count auto-detection
   *  so the component renders consistently across catalog add and dashboard. */
  view_mode?: 'aggregate' | 'facet' | 'overlay';
  /** Optional bundled-annotation override. Falls back to chromosome-name
   *  auto-detection when null. See ``genome_annotations/index.ts``. */
  annotation_id?: string | null;
  chromosomes_filter?: string[] | null;
  samples_filter?: string[] | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: CoverageTrackConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const SMOOTHING_CHOICES = [
  { value: '0', label: 'None' },
  { value: '5', label: '5-bin' },
  { value: '10', label: '10-bin' },
  { value: '20', label: '20-bin' },
  { value: '50', label: '50-bin' },
];

/** Soft cap on per-sample subplots used for the *auto-default* picker only.
 *  The user can still explicitly pick "Per-sample" beyond this — they'll get a
 *  crowded but functional grid, and a hint nudging them toward Aggregate.
 *  Plotly handles N stacked rows fine; the bottleneck is human readability. */
const MAX_FACETED_SAMPLES_AUTO = 8;

/** Above this sample count, default to aggregate view. Individual stacked tracks
 *  become illegible past ~10 samples regardless of layout, so we collapse to a
 *  cohort median + IQR ribbon with optional dimmed individual traces. */
const AGGREGATE_DEFAULT_THRESHOLD = 10;

type ViewMode = 'aggregate' | 'facet' | 'overlay';

const CoverageTrackRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const config = (metadata.config || {}) as CoverageTrackConfig;
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const [yScale, setYScale] = useState<'linear' | 'log'>(config.y_scale ?? 'linear');
  // Bump from 0 → 5 so the default plot is de-noised. 200-bp bins × 5 ≈ 1 kb
  // rolling window — preserves dropout structure, kills high-frequency wiggle.
  const [smoothingWindow, setSmoothingWindow] = useState<number>(config.smoothing_window ?? 5);
  const [colorBy, setColorBy] = useState<NonNullable<CoverageTrackConfig['color_by']>>(
    config.color_by ?? (config.category_col ? 'category' : 'sample'),
  );
  // When a view_mode is persisted in config (e.g. set at catalog-add time),
  // use it directly — no auto-detection needed. Otherwise hold null until data
  // arrives so the sample count can drive the sensible default.
  const [viewMode, setViewMode] = useState<ViewMode | null>(config.view_mode ?? null);
  const [showAnnotationStrip, setShowAnnotationStrip] = useState<boolean>(true);
  const [showIndividuals, setShowIndividuals] = useState<boolean>(true);
  const [selectedChromosomes, setSelectedChromosomes] = useState<string[]>(
    config.chromosomes_filter ?? [],
  );
  const [selectedSamples, setSelectedSamples] = useState<string[]>(config.samples_filter ?? []);

  const [data, setData] = useState<CoverageTrackResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [computeStatus, setComputeStatus] = useState<string | null>(null);
  const [computeMs, setComputeMs] = useState<number | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Coverage track: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setComputeStatus('Aggregating coverage…');
    setComputeMs(null);

    const payload = {
      wf_id: metadata.wf_id,
      dc_id: metadata.dc_id,
      chromosome_col: config.chromosome_col,
      position_col: config.position_col,
      value_col: config.value_col,
      end_col: config.end_col ?? null,
      sample_col: config.sample_col ?? null,
      category_col: config.category_col ?? null,
      chromosomes_filter: selectedChromosomes.length ? selectedChromosomes : null,
      samples_filter: selectedSamples.length ? selectedSamples : null,
      smoothing_window: smoothingWindow,
      filter_metadata: filters,
    };

    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    const accept = (result: CoverageTrackResult) => {
      if (cancelled) return;
      setData(result);
      setComputeMs(result.compute_ms ?? null);
      setComputeStatus(null);
      setLoading(false);
    };

    dispatchCoverageTrack(payload)
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
            const status = await pollCoverageTrack(job.job_id);
            if (cancelled) return;
            if (status.status === 'done' && status.result) accept(status.result);
            else if (status.status === 'failed') {
              setError(status.error || 'Compute task failed');
              setLoading(false);
            } else pollTimer = setTimeout(tick, 1200);
          } catch (err) {
            if (!cancelled) {
              setError(err instanceof Error ? err.message : String(err));
              setLoading(false);
            }
          }
        };
        pollTimer = setTimeout(tick, 600);
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
    smoothingWindow,
    JSON.stringify(selectedChromosomes),
    JSON.stringify(selectedSamples),
    config.chromosome_col,
    config.position_col,
    config.value_col,
    config.end_col,
    config.sample_col,
    config.category_col,
  ]);

  // Once data lands, pick a sensible default viewMode: aggregate when there
  // are many samples (median+ribbon scales), overlay when 1 sample. User can
  // override; we don't second-guess subsequent loads.
  useEffect(() => {
    if (viewMode !== null || !data) return;
    const n = data.summary.samples.length;
    if (n === 0 || n === 1) setViewMode('overlay');
    else if (n <= MAX_FACETED_SAMPLES_AUTO) setViewMode('facet');
    else setViewMode('aggregate');
  }, [data, viewMode]);

  /** Mantine theme palette for categorical traces. */
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

  /** Resolve a genome annotation — explicit ``annotation_id`` in the config
   *  wins, otherwise fall back to chromosome-name auto-detection against the
   *  bound DC's first (or user-selected) chromosome. Returns null when neither
   *  resolves; the annotation strip is hidden in that case. */
  const annotation: GenomeAnnotation | null = useMemo(() => {
    if (!data) return null;
    const chroms = data.summary.chromosomes;
    const target = selectedChromosomes[0] || chroms[0];
    return resolveAnnotation(config.annotation_id ?? null, target);
  }, [data, selectedChromosomes, config.annotation_id]);

  /** Aggregate the long-format rows by position across samples. For each unique
   *  position we compute min/q1/median/q3/max so the renderer can draw a Tukey-
   *  style band. Cheap (~150 positions × N samples for SARS-CoV-2 mosdepth). */
  type Aggregate = {
    positions: number[];
    min: number[];
    q1: number[];
    median: number[];
    q3: number[];
    max: number[];
  };
  const aggregate: Aggregate | null = useMemo(() => {
    if (!data || viewMode !== 'aggregate') return null;
    const cols = data.columns;
    const positions = (data.rows[cols.position] as number[]) || [];
    const values = (data.rows[cols.value] as number[]) || [];
    if (!positions.length) return null;
    const byPos = new Map<number, number[]>();
    for (let i = 0; i < positions.length; i++) {
      const p = positions[i];
      const v = values[i];
      if (!Number.isFinite(v)) continue;
      const arr = byPos.get(p);
      if (arr) arr.push(v);
      else byPos.set(p, [v]);
    }
    const sortedPos = Array.from(byPos.keys()).sort((a, b) => a - b);
    const q = (xs: number[], frac: number) => {
      if (xs.length === 1) return xs[0];
      const pos = frac * (xs.length - 1);
      const lo = Math.floor(pos);
      const hi = Math.ceil(pos);
      return lo === hi ? xs[lo] : xs[lo] + (xs[hi] - xs[lo]) * (pos - lo);
    };
    const out: Aggregate = {
      positions: sortedPos,
      min: [],
      q1: [],
      median: [],
      q3: [],
      max: [],
    };
    for (const p of sortedPos) {
      const arr = byPos.get(p)!.slice().sort((a, b) => a - b);
      out.min.push(arr[0]);
      out.q1.push(q(arr, 0.25));
      out.median.push(q(arr, 0.5));
      out.q3.push(q(arr, 0.75));
      out.max.push(arr[arr.length - 1]);
    }
    return out;
  }, [data, viewMode]);

  const figureSpec = useMemo<{ data: unknown[]; layout: Record<string, unknown> } | null>(() => {
    if (!data || !viewMode) return null;
    const cols = data.columns;
    const positions = (data.rows[cols.position] as number[]) || [];
    const values = (data.rows[cols.value] as number[]) || [];
    const samplesArr = cols.sample ? ((data.rows[cols.sample] as string[]) || []) : null;
    const categoriesArr = cols.category
      ? ((data.rows[cols.category] as string[]) || [])
      : null;

    const samples = data.summary.samples.length ? data.summary.samples : ['(all)'];
    const sampleColor: Record<string, string> = {};
    samples.forEach((s, i) => {
      sampleColor[s] = palette[i % palette.length];
    });

    const categories = categoriesArr ? Array.from(new Set(categoriesArr)).sort() : [];
    const categoryColor: Record<string, string> = {};
    categories.forEach((c, i) => {
      categoryColor[c] = palette[i % palette.length];
    });

    // Group row indices by sample so we can emit per-sample slices.
    const sampleRowIdx: Record<string, number[]> = {};
    if (samplesArr) {
      for (let i = 0; i < samplesArr.length; i++) {
        const s = samplesArr[i];
        (sampleRowIdx[s] = sampleRowIdx[s] || []).push(i);
      }
    } else {
      sampleRowIdx['(all)'] = positions.map((_, i) => i);
    }

    // Honour the user's view-mode pick regardless of sample count — the
    // ``MAX_FACETED_SAMPLES_AUTO`` cap only governs the *auto-default* branch
    // above. Past that cap the user gets a crowded but functional grid; a hint
    // in the controls nudges them toward aggregate.
    const useFacets = viewMode === 'facet' && samples.length > 1;
    const useAggregate = viewMode === 'aggregate' && aggregate !== null;

    const traces: unknown[] = [];

    if (useAggregate && aggregate) {
      const aggColor = palette[0]; // blue
      const ribbonFill = isDark ? `${aggColor}55` : `${aggColor}33`;

      // Ghost individual traces (light grey, low opacity). User can hide.
      if (showIndividuals) {
        samples.forEach((sample) => {
          const idxs = sampleRowIdx[sample] || [];
          const xs = idxs.map((i) => positions[i]);
          const ys = idxs.map((i) => values[i]);
          traces.push({
            type: 'scattergl',
            mode: 'lines',
            name: sample,
            x: xs,
            y: ys,
            line: { color: isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.18)', width: 0.6 },
            hoverinfo: 'skip',
            showlegend: false,
            xaxis: 'x',
            yaxis: 'y',
          });
        });
      }

      // IQR ribbon: q3 (upper) drawn first, then q1 with fill='tonexty' so the
      // band is filled between the two. Plotly's tonexty fills toward the
      // previous trace in the data array, so order matters.
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: 'Q3 (75%)',
        x: aggregate.positions,
        y: aggregate.q3,
        line: { color: aggColor, width: 0 },
        hoverinfo: 'skip',
        showlegend: false,
        xaxis: 'x',
        yaxis: 'y',
      });
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: 'IQR (Q1–Q3)',
        x: aggregate.positions,
        y: aggregate.q1,
        line: { color: aggColor, width: 0 },
        fill: 'tonexty',
        fillcolor: ribbonFill,
        hoverinfo: 'skip',
        showlegend: true,
        xaxis: 'x',
        yaxis: 'y',
      });

      // Median (bold line, primary colour).
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: `Cohort median (n=${samples.length})`,
        x: aggregate.positions,
        y: aggregate.median,
        line: { color: aggColor, width: 2.2 },
        hovertemplate: `pos %{x:,}<br>median %{y:,.1f}<extra></extra>`,
        showlegend: true,
        xaxis: 'x',
        yaxis: 'y',
      });
    } else {
      // Overlay or facet: emit one trace per sample.
      samples.forEach((sample, sampleIdx) => {
        const idxs = sampleRowIdx[sample] || [];
        const xs = idxs.map((i) => positions[i]);
        const ys = idxs.map((i) => values[i]);
        const text = idxs.map((i) =>
          categoriesArr ? `${sample} · ${categoriesArr[i]}` : sample,
        );
        const traceColor =
          colorBy === 'sample' ? sampleColor[sample] ?? palette[0] : palette[0];
        const markerColor =
          colorBy === 'category' && categoriesArr
            ? idxs.map((i) => categoryColor[categoriesArr[i]] || palette[0])
            : undefined;
        const yaxis = useFacets && sampleIdx > 0 ? `y${sampleIdx + 1}` : 'y';
        traces.push({
          type: 'scattergl',
          mode: markerColor ? 'lines+markers' : 'lines',
          name: sample,
          x: xs,
          y: ys,
          text,
          hovertemplate: `%{text}<br>pos %{x:,}<br>cov %{y:,.2f}<extra></extra>`,
          line: { color: traceColor, width: 1.4 },
          ...(markerColor
            ? { marker: { color: markerColor, size: 4, line: { width: 0 } } }
            : {}),
          fill: useFacets ? 'tozeroy' : 'none',
          fillcolor: useFacets ? `${traceColor}33` : undefined,
          xaxis: 'x',
          yaxis,
          showlegend: !useFacets,
        });
      });
    }

    // ---- Annotation strip (genome-aware) ----------------------------------
    // Replaces the old category-heatmap annotation lane. When we recognise the
    // assembly, render labelled gene rectangles aligned to genomic positions.
    // The strip sits in a thin band [0, ~0.06] at the bottom of the figure.
    const showStrip = showAnnotationStrip && annotation !== null;
    const stripHeight = 0.06;
    const trackBase = showStrip ? stripHeight + 0.03 : 0;
    const trackArea = 1 - trackBase;

    const facetRows = useFacets ? samples.length : 1;
    const rowSize = trackArea / facetRows;

    const layout: Record<string, unknown> = {
      template: isDark ? 'plotly_dark' : 'plotly_white',
      margin: { l: 80, r: 12, t: 8, b: 32 },
      showlegend: !useFacets,
      legend: {
        orientation: 'h',
        x: 0,
        y: 1.04,
        font: { size: 10 },
      },
      autosize: true,
      hovermode: 'x unified',
      plot_bgcolor: 'rgba(0,0,0,0)',
      paper_bgcolor: 'rgba(0,0,0,0)',
    };

    const visibleSamples = useFacets ? samples : samples.slice(0, 1);
    visibleSamples.forEach((sample, sampleIdx) => {
      const key = sampleIdx === 0 ? 'yaxis' : `yaxis${sampleIdx + 1}`;
      const lo = trackBase + sampleIdx * rowSize;
      const hi = useFacets ? lo + rowSize - 0.005 : trackBase + trackArea;
      layout[key] = {
        title:
          useFacets
            ? {
                text: sample,
                font: { size: 10, color: isDark ? '#dee2e6' : '#495057' },
                standoff: 6,
              }
            : {
                text: useAggregate ? `${config.value_col} (cohort)` : config.value_col,
                font: { size: 10 },
                standoff: 4,
              },
        type: yScale === 'log' ? 'log' : 'linear',
        domain: [lo, hi],
        zeroline: false,
        showgrid: true,
        gridcolor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
        tickfont: { size: 9 },
      };
    });

    layout.xaxis = {
      title: { text: annotation ? `${annotation.displayName} (bp)` : config.position_col, font: { size: 11 } },
      zeroline: false,
      showgrid: true,
      gridcolor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
      anchor: useFacets ? 'free' : 'y',
      ...(annotation ? { range: [0, annotation.length] } : {}),
    };

    const shapes: Record<string, unknown>[] = [];
    const annotations: Record<string, unknown>[] = [];

    // Sample names render as y-axis titles (in the left margin) — see the
    // facet branch of layout[`yaxis${N}`].title above. Keeps labels clear of
    // the coverage data they describe.

    if (showStrip && annotation) {
      // Render each gene as a coloured rectangle on a dedicated bottom axis
      // (yaxis2 when overlay/aggregate, yaxis{N+1} when faceted) so the strip
      // shares the same x-axis as the coverage panels.
      const stripAxisKey = useFacets ? `yaxis${samples.length + 1}` : 'yaxis2';
      const stripAxisRef = useFacets ? `y${samples.length + 1}` : 'y2';

      layout[stripAxisKey] = {
        domain: [0, stripHeight],
        showticklabels: false,
        showgrid: false,
        zeroline: false,
        range: [0, 1],
        fixedrange: true,
      };

      annotation.features.forEach((feature, i) => {
        const color = palette[i % palette.length];
        shapes.push({
          type: 'rect',
          xref: 'x',
          yref: stripAxisRef,
          x0: feature.start,
          x1: feature.end,
          y0: 0.1,
          y1: 0.9,
          fillcolor: color,
          line: { color, width: 0 },
          opacity: 0.55,
          layer: 'below',
        });

        const featureLen = feature.end - feature.start;
        // Only label features wide enough to fit their name without overlap.
        // Below ~400bp we drop the label (E, ORF6, ORF7a/b, ORF10 are short).
        if (featureLen >= 400) {
          annotations.push({
            xref: 'x',
            yref: stripAxisRef,
            x: (feature.start + feature.end) / 2,
            y: 0.5,
            text: feature.name,
            showarrow: false,
            font: { size: 10, color: isDark ? '#fff' : '#212529', family: 'Inter, sans-serif' },
          });
        }
      });

      // Subtle alternating background banding across the coverage panels for
      // each ORF — gives a free spatial reference even without reading the
      // strip labels. Skipped in aggregate+individuals mode to avoid clutter.
      if (!useAggregate || !showIndividuals) {
        annotation.features.forEach((feature, i) => {
          if (i % 2 !== 0) return; // every other gene
          shapes.push({
            type: 'rect',
            xref: 'x',
            yref: 'paper',
            x0: feature.start,
            x1: feature.end,
            y0: trackBase,
            y1: 1,
            fillcolor: isDark ? 'rgba(255,255,255,0.025)' : 'rgba(0,0,0,0.025)',
            line: { width: 0 },
            layer: 'below',
          });
        });
      }
    }

    layout.shapes = shapes;
    layout.annotations = annotations;

    return { data: traces, layout };
  }, [
    data,
    config,
    palette,
    isDark,
    yScale,
    colorBy,
    viewMode,
    showAnnotationStrip,
    showIndividuals,
    annotation,
    aggregate,
  ]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            View
          </Text>
          <SegmentedControl
          size="xs"
          fullWidth
          value={viewMode ?? 'overlay'}
          onChange={(v) => setViewMode(v as ViewMode)}
          data={[
            { value: 'aggregate', label: 'Aggregate' },
            { value: 'facet', label: 'Per-sample' },
            { value: 'overlay', label: 'Overlay' },
          ]}
        />
        </Stack>
        {viewMode === 'facet' &&
        data &&
        data.summary.samples.length > MAX_FACETED_SAMPLES_AUTO ? (
          <Text size="xs" c="dimmed">
            {data.summary.samples.length} samples stacked — Aggregate is usually
            more legible past ~{MAX_FACETED_SAMPLES_AUTO}.
          </Text>
        ) : null}
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Y-axis scale
          </Text>
          <SegmentedControl
          size="xs"
          fullWidth
          value={yScale}
          onChange={(v) => setYScale(v as 'linear' | 'log')}
          data={[
            { value: 'linear', label: 'Linear' },
            { value: 'log', label: 'Log' },
          ]}
        />
        </Stack>
        <Select
          size="xs"
          label="Smoothing"
          value={String(smoothingWindow)}
          onChange={(v) => setSmoothingWindow(Number(v ?? '0'))}
          data={SMOOTHING_CHOICES}
        />
        {viewMode !== 'aggregate' ? (
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Colour by
            </Text>
            <SegmentedControl
            size="xs"
            fullWidth
            value={colorBy}
            onChange={(v) => setColorBy(v as typeof colorBy)}
            data={[
              { value: 'single', label: 'Single' },
              { value: 'sample', label: 'Sample' },
              ...(config.category_col ? [{ value: 'category', label: 'Region' }] : []),
            ]}
          />
          </Stack>
        ) : (
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Per-sample traces
            </Text>
            <Switch
            size="xs"
            checked={showIndividuals}
            onChange={(e) => setShowIndividuals(e.currentTarget.checked)}
            label="Show individual traces"
          />
          </Stack>
        )}
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Gene strip
          </Text>
          <Switch
          size="xs"
          checked={showAnnotationStrip}
          onChange={(e) => setShowAnnotationStrip(e.currentTarget.checked)}
          disabled={!annotation}
          label={annotation ? `Gene strip (${annotation.displayName})` : 'Gene strip (no map)'}
        />
        </Stack>
        <MultiSelect
          size="xs"
          label="Chromosomes"
          value={selectedChromosomes}
          onChange={setSelectedChromosomes}
          data={(data?.summary.chromosomes ?? []).map((c) => ({ value: c, label: c }))}
          placeholder={data ? 'All chromosomes' : 'Loading…'}
          searchable
          clearable
        />
        <MultiSelect
          size="xs"
          label="Samples"
          value={selectedSamples}
          onChange={setSelectedSamples}
          data={(data?.summary.samples ?? []).map((s) => ({ value: s, label: s }))}
          placeholder={data ? 'All samples' : 'Loading…'}
          searchable
          clearable
          disabled={!config.sample_col}
        />
        {computeStatus ? (
          <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
            {computeStatus}
          </Badge>
        ) : null}
        {computeMs != null && !computeStatus ? (
          <Text size="xs" c="dimmed">
            Built in {computeMs} ms ({data?.row_count?.toLocaleString() ?? '?'} bins,
            {' '}{data?.summary.samples.length ?? 0} samples)
          </Text>
        ) : null}
        {viewMode === 'aggregate' && data && data.summary.samples.length > AGGREGATE_DEFAULT_THRESHOLD ? (
          <Text size="xs" c="dimmed">
            Showing cohort median + IQR ribbon — switch to Per-sample to drill in.
          </Text>
        ) : null}
      </Stack>
    ),
    [
      viewMode,
      yScale,
      smoothingWindow,
      colorBy,
      showAnnotationStrip,
      showIndividuals,
      annotation,
      selectedChromosomes,
      selectedSamples,
      config.category_col,
      config.sample_col,
      data,
      computeStatus,
      computeMs,
    ],
  );

  const dataColumns = useMemo(() => {
    if (!data) return [] as string[];
    const cols = data.columns;
    return [cols.chromosome, cols.position, cols.value, cols.end, cols.sample, cols.category]
      .filter((c): c is string => Boolean(c));
  }, [data]);

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Coverage track'}
      subtitle={(metadata as { description?: string; subtitle?: string }).description}
      controls={controls}
      loading={loading}
      error={error}
      dataRows={data?.rows ?? undefined}
      dataColumns={dataColumns}
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

export default CoverageTrackRenderer;
