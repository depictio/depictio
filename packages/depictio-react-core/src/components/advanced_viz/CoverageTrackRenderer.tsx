import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Box,
  Group,
  SegmentedControl,
  Stack,
  Text,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import AdvancedVizPlot from './AdvancedVizPlot';

import {
  CoverageTrackResult,
  InteractiveFilter,
  StoredMetadata,
  dispatchCoverageTrack,
  pollCoverageTrack,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { usePlotAnnotationLayer } from '../annotations/usePlotAnnotationLayer';
import { supportsAdvancedVizAnnotation } from '../../annotations/plotDecorate';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { useReportGroupColouring } from '../../groupReach';
import { applyDataTheme, applyLayoutTheme } from './plotlyTheme';
import { GenomeAnnotation, resolveAnnotation } from './genome_annotations';
import { regionXRange, useFollowedRegion } from './genomicAxis';
import { usePersistedVizControl, useVizConfigWriter } from './usePersistedVizControl';
import GenomeViewRenderer from './GenomeViewRenderer';
import {
  VizControlCell,
  VizControlGroup,
  VizFullRow,
  VizMultiSelect,
  VizSegmented,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';
import type { GenomeViewConfig } from './genomespy/genomeSpySpec';
import { useDefaultRegionGate } from './genomespy/defaultRegionGate';

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
  /** Trace geometry for the overlay/facet path. Optional, defaults ('line')
   *  keep today's rendering. Ignored in aggregate view, whose median+IQR
   *  ribbon has no single-mark equivalent. */
  mark?: 'line' | 'rect' | 'point';
  /** Force per-sample facets regardless of the sample-count auto-default.
   *  Optional, false keeps today's rendering. The user's own Segmented
   *  Control pick (`view_mode`, persisted separately) still wins once made. */
  facet_by_sample?: boolean;
  /** Which rendering of the same rows the tile shows. `track` is the smoothed
   *  Plotly line this file has always drawn; `locus` hands the rows to the
   *  GenomeSpy track the `genome_view` kind renders. */
  view?: CoverageView;
  /** Views offered in the tile's switch; null offers every view the bindings
   *  and the browser allow. */
  views?: CoverageView[] | null;
  /** Locus view only: bundled gene lane drawn under the track. */
  locus_annotation?: 'none' | 'hg38' | 'mm10';
  /** Locus view only: assembly whose contig lengths lay out the genome axis.
   *  Null derives the axis from the rows themselves. */
  locus_assembly?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: CoverageTrackConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts. Only the locus view uses it, for the region
   *  brush GenomeSpy publishes; the Plotly track emits no filters. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Dashboard-wide analysis grouping, applied to the finished figure. */
  groupRender?: GroupRenderState;
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

/** Bins per sample track the server reduces a wide region to. A track is a few
 *  hundred to a couple of thousand pixels wide, so more rows than this only
 *  cost transfer and Plotly layout time without adding a visible detail. */
const MAX_BINS_PER_TRACK = 4000;

type ViewMode = 'aggregate' | 'facet' | 'overlay';

/** The two renderings of one coverage binding. `track` is this file's own
 *  smoothed Plotly line; `locus` is the GenomeSpy track `genome_view` draws,
 *  mounted here so a template that wanted both no longer needs two tiles over
 *  the same collection. */
const ALL_VIEWS = ['track', 'locus'] as const;
type CoverageView = (typeof ALL_VIEWS)[number];

/**
 * Whether the locus view is worth offering in this browser at all.
 *
 * GenomeSpy draws through a canvas, preferring WebGL and falling back to the
 * 2D context when no GL slot is free (see `webglBudget.ts`). Where neither
 * context can be created the track would mount and paint nothing, which is a
 * worse answer than not offering the view, so the switch hides it. Probed once
 * per page: the answer cannot change under us, and creating throwaway contexts
 * per tile would itself eat the GL budget.
 */
let canvasProbe: boolean | null = null;
function locusViewSupported(): boolean {
  if (canvasProbe !== null) return canvasProbe;
  if (typeof document === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    canvasProbe = Boolean(
      canvas.getContext('webgl2') || canvas.getContext('webgl') || canvas.getContext('2d'),
    );
  } catch {
    canvasProbe = false;
  }
  return canvasProbe;
}

const CoverageTrackRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
  groupRender,
}) => {
  const config = (metadata.config || {}) as CoverageTrackConfig;
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  // Which rendering of the binding the tile shows. The two views fetch through
  // different code paths, this file's Celery coverage job, GenomeSpy's own row
  // load, which is why the "one fetch per tile" rule still holds: each view
  // owns exactly one fetch, only the visible view fetches at all, and switching
  // view is a deliberate click rather than something a re-render can trigger.
  const [view, setView] = usePersistedVizControl<CoverageView>(metadata, 'view', 'track');
  const offeredViews = useMemo<CoverageView[]>(() => {
    const allowed = config.views ?? [...ALL_VIEWS];
    return ALL_VIEWS.filter(
      (v) => allowed.includes(v) && (v !== 'locus' || locusViewSupported()),
    );
  }, [config.views]);
  // A persisted view the bindings or the browser no longer offer falls back to
  // the first offered one here, rather than being corrected through the setter:
  // an author's pick is not overwritten just because one reader lacks a canvas.
  const activeView: CoverageView =
    offeredViews.includes(view) ? view : (offeredViews[0] ?? 'track');

  const [yScale, setYScale] = usePersistedVizControl<'linear' | 'log'>(
    metadata,
    'y_scale',
    'linear',
  );
  // Bump from 0 → 5 so the default plot is de-noised. 200-bp bins × 5 ≈ 1 kb
  // rolling window — preserves dropout structure, kills high-frequency wiggle.
  const [smoothingWindow, setSmoothingWindow] = usePersistedVizControl<number>(
    metadata,
    'smoothing_window',
    5,
  );
  const [colorBy, setColorBy] = usePersistedVizControl<
    NonNullable<CoverageTrackConfig['color_by']>
  >(metadata, 'color_by', config.category_col ? 'category' : 'sample');
  // When a view_mode is persisted in config (e.g. set at catalog-add time),
  // use it directly — no auto-detection needed. Otherwise hold null until data
  // arrives so the sample count can drive the sensible default.
  //
  // Plain state rather than usePersistedVizControl, because the effect below
  // sets it too: an auto-detected default is not a choice anyone made, and
  // writing it to the config would freeze one run's sample count into the
  // component. Only the author's own pick is persisted, on the control itself.
  const [viewMode, setViewMode] = useState<ViewMode | null>(
    config.view_mode ?? (config.facet_by_sample ? 'facet' : null),
  );
  const writeConfig = useVizConfigWriter(metadata);
  const [mark, setMark] = usePersistedVizControl<NonNullable<CoverageTrackConfig['mark']>>(
    metadata,
    'mark',
    config.mark ?? 'line',
  );
  const [showAnnotationStrip, setShowAnnotationStrip] = usePersistedVizControl(metadata, 'show_annotation_lane', true);
  const [showIndividuals, setShowIndividuals] = usePersistedVizControl(metadata, 'show_individuals', true);
  const [selectedChromosomes, setSelectedChromosomes] = useState<string[]>(
    config.chromosomes_filter ?? [],
  );
  const [selectedSamples, setSelectedSamples] = useState<string[]>(config.samples_filter ?? []);

  // ---- Following a region someone else brushed ----------------------------
  // A `genome_selection` filter naming *this* collection's chromosome and
  // position columns (a genome_view brush above, a chromosome select in the
  // left panel, or a chrom/pos pair rewritten onto this DC by a `region` link)
  // already narrows the rows the server returns, because the payload below
  // forwards the dashboard filters untouched. What the tile adds here is the
  // other half: it moves its own chromosome control onto the brushed contig
  // and clamps the x axis to the window, so the track reads as the same locus
  // as the track above it rather than as the whole contig.
  const followedRegion = useFollowedRegion(metadata, config, filters);
  useEffect(() => {
    if (!followedRegion) return;
    setSelectedChromosomes((current) =>
      current.length === 1 && current[0] === followedRegion.chrom
        ? current
        : [followedRegion.chrom],
    );
  }, [followedRegion]);

  // A navigator above that still has its `default_region` to emit holds the
  // first fetch (at most `DEFAULT_REGION_GATE_MS`), so the track reads the
  // region rather than the whole genome it would replace a moment later.
  const regionGateOpen = useDefaultRegionGate(filters, metadata.index);

  const [data, setData] = useState<CoverageTrackResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [computeStatus, setComputeStatus] = useState<string | null>(null);
  const [computeMs, setComputeMs] = useState<number | null>(null);

  useEffect(() => {
    // The locus view reads its rows through GenomeSpy's own loader, so queuing
    // the coverage aggregation job here would burn a worker on a figure nobody
    // is looking at.
    if (activeView === 'locus') {
      setLoading(false);
      setComputeStatus(null);
      return;
    }
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Coverage track: missing data binding');
      setLoading(false);
      return;
    }
    if (!regionGateOpen) {
      setLoading(true);
      setComputeStatus('Waiting for the section region…');
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
      max_bins_per_track: MAX_BINS_PER_TRACK,
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
    activeView,
    regionGateOpen,
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

  /** The followed region as an x-axis window, once the rows on screen are
   *  actually the ones that region names. A region on a contig this tile does
   *  not hold would clamp the axis onto an empty span. */
  const regionRange = useMemo<[number, number] | null>(() => {
    if (!followedRegion) return null;
    const shown = selectedChromosomes.length
      ? selectedChromosomes
      : (data?.summary.chromosomes ?? []);
    if (shown.length && !shown.includes(followedRegion.chrom)) return null;
    return regionXRange(followedRegion);
  }, [followedRegion, selectedChromosomes, data]);

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
            // Slot 0 is the sample, so an analysis group can pick its own tracks
            // out of the ghost cohort. Hover stays skipped, as before.
            customdata: idxs.map(() => [sample]),
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
        // `mark` only shapes this overlay/facet trace; the aggregate view's
        // median+IQR ribbon above has no single-mark equivalent and ignores it.
        // 'line' (the default) reproduces the pre-`mark` trace byte for byte.
        const shared = {
          name: sample,
          x: xs,
          y: ys,
          text,
          // Slot 0 is the sample this track belongs to — the value a saved group
          // of samples is matched against. One trace is one sample, so a track
          // is assigned to a group whole. The hover reads `text`, not
          // `customdata`, so it renders exactly as it did before.
          customdata: idxs.map(() => [sample]),
          hovertemplate: `%{text}<br>pos %{x:,}<br>cov %{y:,.2f}<extra></extra>`,
          xaxis: 'x',
          yaxis,
          showlegend: !useFacets,
        };
        if (mark === 'point') {
          traces.push({
            ...shared,
            type: 'scattergl',
            mode: 'markers',
            marker: { color: markerColor ?? traceColor, size: 4, line: { width: 0 } },
          });
        } else if (mark === 'rect') {
          // A bar needs a finite height: a null value (or a non-positive one
          // on a log axis) becomes a `d="M…,NaNVNaN"` path Plotly still
          // writes into the DOM. Dropping the row draws the same picture.
          const keep = ys.map((y) => Number.isFinite(y) && (yScale !== 'log' || y > 0));
          const pick = <T,>(arr: T[]): T[] => arr.filter((_, i) => keep[i]);
          traces.push({
            ...shared,
            x: pick(xs),
            y: pick(ys),
            text: pick(text),
            customdata: pick(shared.customdata),
            type: 'bar',
            marker: { color: markerColor ?? traceColor },
            // `text` is for the hover only. Left to its default `auto`, Plotly
            // lays an SVG label on every bar, which on a whole-genome fetch
            // (150k rects before the region lands) held the main thread for
            // minutes: 68.8 s against 1.1 s for 153,891 bars, measured.
            textposition: 'none',
          });
        } else {
          traces.push({
            ...shared,
            type: 'scattergl',
            mode: markerColor ? 'lines+markers' : 'lines',
            line: { color: traceColor, width: 1.4 },
            ...(markerColor
              ? { marker: { color: markerColor, size: 4, line: { width: 0 } } }
              : {}),
            fill: useFacets ? 'tozeroy' : 'none',
            fillcolor: useFacets ? `${traceColor}33` : undefined,
          });
        }
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
      // b is only a floor: the x axis carries automargin, so Plotly grows the
      // bottom margin to whatever the tick labels plus the genome-name title
      // need. Raising the floor buys nothing, it only shortens the track.
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

    // The axis furniture (line, tick labels, and the genome-name title) is drawn
    // downwards from wherever the axis is anchored. Anchoring it to `y` put it at
    // the coverage panel's lower domain edge, which is `trackBase` (0.09) rather
    // than the bottom of the plotting area, so the tick labels landed inside the
    // annotation strip's band [0, 0.06] and the title came to rest across that
    // band's lower boundary. Anchoring free at position 0 puts all of it below
    // the strip, in the bottom margin, which is also what the facet branch was
    // already getting from `free` (position defaults to 0). automargin lets the
    // bottom margin grow for the title rather than clipping it.
    layout.xaxis = {
      title: { text: annotation ? `${annotation.displayName} (bp)` : config.position_col, font: { size: 11 } },
      zeroline: false,
      showgrid: true,
      gridcolor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
      anchor: 'free',
      position: 0,
      automargin: true,
      ...(annotation ? { range: [0, annotation.length] } : {}),
      // A followed region is narrower than the contig and wins over it.
      ...(regionRange ? { range: regionRange } : {}),
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
    mark,
    showAnnotationStrip,
    showIndividuals,
    annotation,
    aggregate,
    regionRange,
  ]);

  // Recolour by the dashboard's analysis groups. Slot 0 of `customdata` is the
  // sample, which is what a saved group of samples is matched on; a group of
  // anything else leaves the figure untouched.
  //
  // `facetable: false` is not a preference here, it is the only safe answer:
  // this renderer already owns its y-axes — one per sample in "Per-sample"
  // view, plus the gene strip's own axis, whose shapes are anchored to `y2` /
  // `y{N+1}` — and a figure-level facet would rebuild `xaxis`/`yaxis` from
  // scratch underneath them. Splitting by group is the dispatch's job anyway
  // (`SplitPanels` gives each group its own renderer).
  //
  // `contextTraces: 'drop'`: the traces without an identity are the cohort
  // median and its IQR ribbon, a summary over every sample. Repeating that band
  // inside a per-group panel would present the whole cohort's spread as the
  // group's own. It is unreachable while `facetable` is false, and stated so
  // that stays true if it ever is not.
  const groupedFigure = useMemo(
    () =>
      figureSpec
        ? splitFigureByGroups(figureSpec, {
            groupRender,
            identitySlot: 0,
            facetable: false,
            contextTraces: 'drop',
            showLegend: true,
          })
        : figureSpec,
    [figureSpec, groupRender],
  );
  // Whether any point matched, for the dispatch's "not grouped" badge.
  useReportGroupColouring(groupRender, figureSpec, groupedFigure);

  const controls = useMemo(
    () => (
      <>
        <VizControlGroup title="Traces">
          {viewMode === 'facet' &&
          data &&
          data.summary.samples.length > MAX_FACETED_SAMPLES_AUTO ? (
            <VizFullRow>
              <Text size="xs" c="dimmed">
                {data.summary.samples.length} samples stacked. Aggregate is usually
                more legible past ~{MAX_FACETED_SAMPLES_AUTO}.
              </Text>
            </VizFullRow>
          ) : null}
          {viewMode !== 'aggregate' ? (
            <VizSelect
              label="Mark"
              value={mark}
              onChange={(v) => setMark((v as typeof mark) || 'line')}
              data={[
                { value: 'line', label: 'Line' },
                { value: 'rect', label: 'Rect (bar per bin)' },
                { value: 'point', label: 'Point' },
              ]}
              allowDeselect={false}
            />
          ) : null}
          {viewMode !== 'aggregate' ? (
            <VizSegmented
              label="Colour by"
              value={colorBy}
              onChange={(v) => setColorBy(v as typeof colorBy)}
              data={[
                { value: 'single', label: 'Single' },
                { value: 'sample', label: 'Sample' },
                ...(config.category_col ? [{ value: 'category', label: 'Region' }] : []),
              ]}
            />
          ) : (
            <VizSwitch
              checked={showIndividuals}
              onChange={(e) => setShowIndividuals(e.currentTarget.checked)}
              label="Show individual traces"
            />
          )}
          {viewMode === 'aggregate' && data && data.summary.samples.length > AGGREGATE_DEFAULT_THRESHOLD ? (
            <VizFullRow>
              <Text size="xs" c="dimmed">
                Showing cohort median + IQR ribbon. Switch to Per-sample to drill in.
              </Text>
            </VizFullRow>
          ) : null}
        </VizControlGroup>
        <VizControlGroup title="Annotations">
          <VizSwitch
            checked={showAnnotationStrip}
            onChange={(e) => setShowAnnotationStrip(e.currentTarget.checked)}
            disabled={!annotation}
            label={annotation ? `Gene strip (${annotation.displayName})` : 'Gene strip (no map)'}
          />
        </VizControlGroup>
        {computeStatus ? (
          <VizFullRow>
            <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
              {computeStatus}
            </Badge>
          </VizFullRow>
        ) : null}
        {computeMs != null && !computeStatus ? (
          <VizFullRow>
            <Text size="xs" c="dimmed">
              Built in {computeMs} ms ({data?.row_count?.toLocaleString() ?? '?'} bins,
              {' '}{data?.summary.samples.length ?? 0} samples)
            </Text>
          </VizFullRow>
        ) : null}
        {data?.summary.bin_width ? (
          <VizFullRow>
            <Text size="xs" c="dimmed">
              Averaged into {data.summary.bin_width.toLocaleString()} bp bins from{' '}
              {(data.summary.input_rows ?? 0).toLocaleString()} rows; narrow the region for full
              resolution.
            </Text>
          </VizFullRow>
        ) : null}
      </>
    ),
    [
      viewMode,
      colorBy,
      mark,
      showAnnotationStrip,
      showIndividuals,
      annotation,
      config.category_col,
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

  // Themed once per figure so the annotation layer can memoise on them.
  const plotData = useMemo(
    () => (groupedFigure ? applyDataTheme(groupedFigure.data, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );
  const plotLayout = useMemo(
    () =>
      groupedFigure
        ? applyLayoutTheme(
            { ...(groupedFigure.layout as any), width: undefined, height: undefined, autosize: true },
            isDark,
            theme,
          )
        : null,
    [groupedFigure, isDark, theme],
  );
  // Chart annotations, on a single coverage panel only: the per-sample view
  // and the gene strip each add a y axis under the same component. Coverage
  // bins are not rows, so marked points are stored as coordinates. Called
  // ahead of the locus early return so the hook order never changes, and
  // switched off there since the locus view draws no Plotly figure of its own.
  const singlePanel =
    !!plotLayout && !Object.keys(plotLayout).some((k) => /^[xy]axis\d+$/.test(k));
  const annotations = usePlotAnnotationLayer({
    componentIndex: String(metadata.index),
    enabled: supportsAdvancedVizAnnotation(metadata) && singlePanel && activeView !== 'locus',
    data: plotData,
    layout: plotLayout,
  });

  /** The view switch itself. Drawn in the frame's header rather than inside the
   *  Settings popover: it picks which plot the tile is, not how that plot looks,
   *  and the locus view has no popover of this file's to live in. */
  const viewControl = useMemo(
    () =>
      offeredViews.length > 1 ? (
        <SegmentedControl
          size="xs"
          value={activeView}
          onChange={(v) => setView(v as CoverageView)}
          data={[
            { value: 'track', label: 'Track' },
            { value: 'locus', label: 'Locus' },
          ].filter((o) => offeredViews.includes(o.value as CoverageView))}
        />
      ) : null,
    [offeredViews, activeView, setView],
  );

  // Encoding tier: which view, how samples are laid out, the y scale and
  // smoothing, and which chromosomes and samples are drawn. Handed to the
  // frame as a flat fragment; the strip's grid owns the widths.
  const primaryControls = useMemo(
    () => (
      <>
        <VizControlGroup title="Layout">
          {viewControl ? <VizControlCell>{viewControl}</VizControlCell> : null}
          <VizSegmented
            aria-label="Sample layout"
            value={viewMode ?? 'overlay'}
            onChange={(v) => {
              setViewMode(v as ViewMode);
              writeConfig({ view_mode: v });
            }}
            data={[
              { value: 'aggregate', label: 'Aggregate' },
              { value: 'facet', label: 'Per-sample' },
              { value: 'overlay', label: 'Overlay' },
            ]}
          />
          <VizSegmented
            aria-label="Y scale"
            value={yScale}
            onChange={(v) => setYScale(v as 'linear' | 'log')}
            data={[
              { value: 'linear', label: 'Linear' },
              { value: 'log', label: 'Log' },
            ]}
          />
          <VizSelect
            label="Smoothing"
            value={String(smoothingWindow)}
            onChange={(v) => setSmoothingWindow(Number(v ?? '0'))}
            data={SMOOTHING_CHOICES}
          />
        </VizControlGroup>
        <VizControlGroup title="Data">
          <Tooltip
            label={
              followedRegion
                ? `Following the dashboard region ${followedRegion.chrom}${
                    regionRange
                      ? `:${Math.round(regionRange[0])}-${Math.round(regionRange[1])}`
                      : ''
                  }`
                : ''
            }
            disabled={!followedRegion}
          >
            <Box>
              <VizMultiSelect
                label="Chromosomes"
                value={selectedChromosomes}
                onChange={setSelectedChromosomes}
                data={(data?.summary.chromosomes ?? []).map((c) => ({ value: String(c), label: String(c) }))}
                placeholder={data ? 'All chromosomes' : 'Loading…'}
                searchable
                clearable
              />
            </Box>
          </Tooltip>
          <VizMultiSelect
            label="Samples"
            value={selectedSamples}
            onChange={setSelectedSamples}
            // A numeric sample column (hic binds `window` and `resolution`) arrives as
            // numbers; Mantine's search lowercases the value, so coerce here.
            data={(data?.summary.samples ?? []).map((s) => ({ value: String(s), label: String(s) }))}
            placeholder={data ? 'All samples' : 'Loading…'}
            searchable
            clearable
            disabled={!config.sample_col}
          />
        </VizControlGroup>
      </>
    ),
    [
      viewControl,
      viewMode,
      writeConfig,
      yScale,
      smoothingWindow,
      followedRegion,
      regionRange,
      selectedChromosomes,
      selectedSamples,
      data,
      config.sample_col,
    ],
  );

  // The same binding, read as a genome_view. Only the roles move: coverage's
  // chromosome/position/value are genome_view's chr/pos/score, and its `line`
  // has no GenomeSpy equivalent, so it draws as the bar profile instead.
  const locusMetadata = useMemo(
    () => ({
      ...metadata,
      viz_kind: 'genome_view',
      config: {
        chr_col: config.chromosome_col,
        pos_col: config.position_col,
        score_col: config.value_col,
        end_col: config.end_col ?? null,
        sample_col: config.sample_col ?? null,
        category_col: config.category_col ?? null,
        mark: mark === 'line' ? 'bar' : mark,
        facet_by_sample: config.facet_by_sample ?? false,
        annotation: config.locus_annotation ?? 'none',
        assembly: config.locus_assembly ?? null,
        score_title: config.value_col,
      } satisfies GenomeViewConfig,
    }),
    [
      metadata,
      config.chromosome_col,
      config.position_col,
      config.value_col,
      config.end_col,
      config.sample_col,
      config.category_col,
      config.facet_by_sample,
      config.locus_annotation,
      config.locus_assembly,
      mark,
    ],
  );

  // GenomeViewRenderer brings its own AdvancedVizFrame, title, controls and
  // data popover, so wrapping it in a second frame would double every one of
  // them. The view switch therefore sits on a bare row above it instead of in
  // the frame header it would normally use.
  if (activeView === 'locus') {
    return (
      <Stack h="100%" gap={4}>
        <Group justify="flex-end" gap="xs">
          {viewControl}
        </Group>
        <Box style={{ flex: 1, minHeight: 0 }}>
          <GenomeViewRenderer
            metadata={locusMetadata}
            filters={filters}
            refreshTick={refreshTick}
            onFilterChange={onFilterChange}
            groupRender={groupRender}
          />
        </Box>
      </Stack>
    );
  }

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Coverage track'}
      subtitle={(metadata as { description?: string; subtitle?: string }).description}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      dataRows={data?.rows ?? undefined}
      dataColumns={dataColumns}
      badges={annotations.badges}
    >
      {groupedFigure ? (
        <>
          <AdvancedVizPlot
            data={annotations.data as any}
            layout={annotations.layout as any}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
            config={{ displaylogo: false, responsive: true } as any}
            {...annotations.plotProps()}
          />
          {annotations.toolbar}
        </>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default CoverageTrackRenderer;
