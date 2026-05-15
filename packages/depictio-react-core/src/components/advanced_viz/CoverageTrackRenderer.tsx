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
  { value: '5', label: '5-bin mean' },
  { value: '10', label: '10-bin mean' },
  { value: '20', label: '20-bin mean' },
  { value: '50', label: '50-bin mean' },
];

/** Cap on per-sample subplots — Plotly grid layouts past ~8 rows squeeze too
 *  thin to be useful and add measurable jank. When the user picks more samples
 *  than this, we drop into single-axis multi-trace mode (one line per sample). */
const MAX_FACETED_SAMPLES = 8;

const CoverageTrackRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const config = (metadata.config || {}) as CoverageTrackConfig;
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const [yScale, setYScale] = useState<'linear' | 'log'>(config.y_scale ?? 'linear');
  const [smoothingWindow, setSmoothingWindow] = useState<number>(config.smoothing_window ?? 0);
  const [colorBy, setColorBy] = useState<NonNullable<CoverageTrackConfig['color_by']>>(
    config.color_by ?? (config.category_col ? 'category' : 'sample'),
  );
  const [showAnnotationLane, setShowAnnotationLane] = useState<boolean>(
    config.show_annotation_lane ?? true,
  );
  const [selectedChromosomes, setSelectedChromosomes] = useState<string[]>(
    config.chromosomes_filter ?? [],
  );
  const [selectedSamples, setSelectedSamples] = useState<string[]>(config.samples_filter ?? []);
  const [facet, setFacet] = useState<boolean>(true);

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

  /** Mantine theme palette for categorical traces — primary swatches across hues
   *  so per-sample / per-category colouring stays distinct in both light + dark
   *  scheme (Mantine's shade-5 lands in the visible band of every named hue). */
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

  const figureSpec = useMemo<{ data: unknown[]; layout: Record<string, unknown> } | null>(() => {
    if (!data) return null;
    const cols = data.columns;
    const positions = (data.rows[cols.position] as number[]) || [];
    const values = (data.rows[cols.value] as number[]) || [];
    const samplesArr = cols.sample ? ((data.rows[cols.sample] as string[]) || []) : null;
    const categoriesArr = cols.category
      ? ((data.rows[cols.category] as string[]) || [])
      : null;

    // Per-sample slice ranges so we can emit one trace per sample.
    const samples = data.summary.samples.length
      ? data.summary.samples
      : ['(all)'];
    const sampleColor: Record<string, string> = {};
    samples.forEach((s, i) => {
      sampleColor[s] = palette[i % palette.length];
    });

    const categories = categoriesArr
      ? Array.from(new Set(categoriesArr)).sort()
      : [];
    const categoryColor: Record<string, string> = {};
    categories.forEach((c, i) => {
      categoryColor[c] = palette[i % palette.length];
    });

    const useFacets = facet && samples.length > 1 && samples.length <= MAX_FACETED_SAMPLES;
    const traces: unknown[] = [];

    // Group row indices by sample for trace emission.
    const sampleRowIdx: Record<string, number[]> = {};
    if (samplesArr) {
      for (let i = 0; i < samplesArr.length; i++) {
        const s = samplesArr[i];
        (sampleRowIdx[s] = sampleRowIdx[s] || []).push(i);
      }
    } else {
      sampleRowIdx['(all)'] = positions.map((_, i) => i);
    }

    function traceColorFor(sample: string): string {
      if (colorBy === 'sample') return sampleColor[sample] ?? palette[0];
      // 'single' and 'category' both fall back to the primary swatch — the
      // category mode then overrides per-point via marker.color below.
      return palette[0];
    }

    samples.forEach((sample, sampleIdx) => {
      const idxs = sampleRowIdx[sample] || [];
      const xs = idxs.map((i) => positions[i]);
      const ys = idxs.map((i) => values[i]);
      const text = idxs.map((i) =>
        categoriesArr ? `${sample} · ${categoriesArr[i]}` : sample,
      );
      const traceColor = traceColorFor(sample);
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

    // Optional annotation lane: a thin bottom subplot encoding category at each
    // x position as a coloured bar. Skipped when category_col isn't bound.
    const annotationLane = Boolean(showAnnotationLane && categoriesArr && categories.length > 0);

    const facetRows = useFacets ? samples.length : 1;
    const totalRows = facetRows + (annotationLane ? 1 : 0);
    const layout: Record<string, unknown> = {
      template: isDark ? 'plotly_dark' : 'plotly_white',
      margin: { l: 60, r: 12, t: 8, b: 36 },
      showlegend: !useFacets,
      legend: { orientation: 'h', x: 0, y: 1.04, font: { size: 10 } },
      autosize: true,
      hovermode: 'closest',
      plot_bgcolor: 'rgba(0,0,0,0)',
      paper_bgcolor: 'rgba(0,0,0,0)',
    };

    // Vertical domain layout: split [0,1] across faceted rows + optional ann lane.
    const annHeight = 0.08;
    const trackBase = annotationLane ? annHeight + 0.02 : 0;
    const trackArea = 1 - trackBase;
    const rowSize = trackArea / facetRows;
    const visibleSamples = useFacets ? samples : samples.slice(0, 1);
    visibleSamples.forEach((sample, sampleIdx) => {
      const key = sampleIdx === 0 ? 'yaxis' : `yaxis${sampleIdx + 1}`;
      const lo = trackBase + sampleIdx * rowSize;
      const hi = useFacets ? lo + rowSize : 1;
      layout[key] = {
        title: {
          text: useFacets ? sample : config.value_col,
          font: { size: 10 },
          standoff: 4,
        },
        type: yScale === 'log' ? 'log' : 'linear',
        domain: [lo, hi],
        zeroline: false,
        showgrid: true,
        gridcolor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
      };
    });
    layout.xaxis = {
      title: { text: config.position_col, font: { size: 11 } },
      zeroline: false,
      showgrid: true,
      gridcolor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
      anchor: useFacets ? 'free' : 'y',
    };

    if (annotationLane && categoriesArr) {
      // Build a heatmap row keyed by category index — one cell per row in the
      // raw frame. Plotly renders this as a coloured strip; the colorbar is
      // hidden because the legend below already lists categories.
      const catIndex: Record<string, number> = {};
      categories.forEach((c, i) => {
        catIndex[c] = i;
      });
      const zs = categoriesArr.map((c) => (c in catIndex ? catIndex[c] : -1));
      // Plotly requires ≥2 colorscale stops; duplicate the single colour at both
      // ends when only one category survives the filter so the lane still
      // renders instead of falling back to the default Viridis gradient.
      const colorscale =
        categories.length === 1
          ? [
              [0, categoryColor[categories[0]]],
              [1, categoryColor[categories[0]]],
            ]
          : categories.map((c, i) => [i / (categories.length - 1), categoryColor[c]]);
      traces.push({
        type: 'heatmap',
        x: positions,
        z: [zs],
        colorscale,
        showscale: false,
        hovertemplate: `pos %{x:,}<br>region: %{text}<extra></extra>`,
        text: [categoriesArr],
        xaxis: 'x',
        yaxis: useFacets ? `y${samples.length + 1}` : 'y2',
      });
      const annKey = useFacets ? `yaxis${samples.length + 1}` : 'yaxis2';
      layout[annKey] = {
        domain: [0, annHeight],
        showticklabels: false,
        showgrid: false,
        zeroline: false,
        title: { text: config.category_col || 'category', font: { size: 10 } },
      };
    }

    layout.grid = { rows: totalRows, columns: 1, pattern: 'independent' };

    return { data: traces, layout };
  }, [data, config, palette, isDark, yScale, colorBy, facet, showAnnotationLane]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
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
        <Select
          size="xs"
          label="Smoothing"
          value={String(smoothingWindow)}
          onChange={(v) => setSmoothingWindow(Number(v ?? '0'))}
          data={SMOOTHING_CHOICES}
        />
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
        <Switch
          size="xs"
          checked={facet}
          onChange={(e) => setFacet(e.currentTarget.checked)}
          label={`Facet by sample (≤ ${MAX_FACETED_SAMPLES})`}
        />
        <Switch
          size="xs"
          checked={showAnnotationLane}
          onChange={(e) => setShowAnnotationLane(e.currentTarget.checked)}
          disabled={!config.category_col}
          label="Annotation lane"
        />
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
            Built in {computeMs} ms ({data?.row_count?.toLocaleString() ?? '?'} bins)
          </Text>
        ) : null}
      </Stack>
    ),
    [
      yScale,
      smoothingWindow,
      colorBy,
      facet,
      showAnnotationLane,
      selectedChromosomes,
      selectedSamples,
      config.category_col,
      config.sample_col,
      data,
      computeStatus,
      computeMs,
    ],
  );

  // Wire the AdvancedVizFrame's "Show data" popover to the aggregated rows
  // we already fetched for plotting. Column order follows the role binding so
  // the popover preview reads chrom → start/end → position → value → sample → category.
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
          // react-plotly.js's Layout type forbids `width: undefined`, but the
          // underlying Plotly.js library uses it to disable the fixed-size
          // shortcut. applyLayoutTheme retints every axis + legend + title +
          // colorbar so dark/light flips reliably without relying on Plotly's
          // template-vs-layout precedence rules.
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
