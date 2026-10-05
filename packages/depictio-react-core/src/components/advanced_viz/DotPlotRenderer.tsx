import React, { useEffect, useMemo, useState } from 'react';
import {
  alpha,
  Group,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { adaptGlTrace, SVG_MAX_POINTS, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  VizControlGroup,
  VizFullRow,
  VizMultiSelect,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';
import { usePlotAnnotationLayer } from '../annotations/usePlotAnnotationLayer';
import { supportsAdvancedVizAnnotation } from '../../annotations/plotDecorate';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import { dotSizeKey, dotSizes, type DotSizeKeyEntry } from './dotSizes';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { useReportGroupColouring } from '../../groupReach';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';
import { demandForItems } from './contentDemand';

/** Room one y-axis category needs: a dot at its largest plus the gap that
 *  keeps two neighbouring rows from touching. */
const DOT_ROW_PX = 22;
/** Fixed furniture around the rows: the tilted cluster labels along the
 *  bottom (b: 100 in the layout), the top margin, and the dot-size key drawn
 *  under the plot. */
const DOT_PLOT_CHROME_PX = 170;

/** Same marks, same size and colour channels, a different table.
 *
 *  `dotplot` is the single-cell marker layout (cluster by gene). `enrichment`
 *  puts a pathway on the y axis and its NES on x, which is that same grammar
 *  read over a gene-set table, so the two share a tile rather than a renderer
 *  each. Which views a tile offers follows from its bindings. */
const ALL_VIEWS = ['dotplot', 'enrichment'] as const;
type View = (typeof ALL_VIEWS)[number];

const VIEW_LABELS: Record<View, string> = {
  dotplot: 'Markers',
  enrichment: 'Enrichment',
};

interface DotPlotConfig {
  cluster_col: string;
  gene_col: string;
  mean_expression_col: string;
  frac_expressing_col: string;
  max_dot_size?: number;
  min_dot_size?: number;
  /** Enrichment-view bindings. All optional: a marker dot plot binds none. */
  term_col?: string | null;
  nes_col?: string | null;
  padj_col?: string | null;
  gene_count_col?: string | null;
  source_col?: string | null;
  view?: View;
  views?: View[] | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: DotPlotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Dashboard-wide analysis grouping, recoloured into the built figure.
   *  Colour only: this plot is keyed per feature, so panels would repeat the
   *  same marks. See `splitFigureByGroups`. */
  groupRender?: GroupRenderState;
}

type AxisSort = 'name' | 'mean' | 'frac';
type TermSort = 'nes' | 'significance' | 'gene_count' | 'name';
type ColourBy = 'neg_log10_padj' | 'abs_nes' | 'nes_sign' | 'gene_count';
// 'Auto' keeps the per-mode, per-theme palette the enrichment view has always
// drawn; any named scale overrides it, in either view.
type DotPlotColourScale = 'Auto' | ColourScale;

/** The scale a plain sequential channel draws with.
 *
 *  'Auto' has no per-mode answer outside the enrichment view's colour-by, so
 *  here it only follows the theme: Plasma holds its contrast on a dark canvas
 *  where Viridis sinks into it. */
const sequentialScale = (scale: DotPlotColourScale, isDark: boolean): ColourScale =>
  scale === 'Auto' ? (isDark ? 'Plasma' : 'Viridis') : scale;

/** Significant digits that separate the key's steps without printing noise.
 *  The steps fall by quarters, so two digits keep 0.097 / 0.024 / 0.0060 apart
 *  while a fixed decimal count would round the smallest of them to zero. */
const formatKeyValue = (v: number): string =>
  v === 0 ? '0' : Number(v.toPrecision(2)).toString();

/** Row of reference circles explaining the marker-size channel.
 *
 *  Circles are drawn at the diameters `dotSizes` produced, so the key is the
 *  scale rather than a restatement of it. Renders nothing when there is no
 *  scale to explain (an empty or all-zero frame). */
const DotSizeKey: React.FC<{ entries: DotSizeKeyEntry[]; label: string }> = ({
  entries,
  label,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  if (entries.length === 0) return null;
  const widest = Math.max(...entries.map((e) => e.diameter));
  const stroke = colorScheme === 'dark' ? theme.colors.dark[1] : theme.colors.gray[6];
  return (
    // Top padding keeps the row clear of the x-axis title, which Plotly draws
    // hard against the bottom of its own box.
    <Group gap="sm" wrap="nowrap" justify="center" style={{ padding: '10px 0 4px' }}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      {/* Largest first, matching how the eye scans a bubble key. */}
      {entries.map((e) => (
        <Group key={e.value} gap={4} wrap="nowrap">
          <svg width={widest} height={widest} aria-hidden focusable="false">
            <circle
              cx={widest / 2}
              cy={widest / 2}
              r={e.diameter / 2}
              fill="none"
              stroke={stroke}
              strokeWidth={1}
            />
          </svg>
          <Text size="xs" c="dimmed">
            {formatKeyValue(e.value)}
          </Text>
        </Group>
      ))}
    </Group>
  );
};

const DotPlotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, groupRender }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as DotPlotConfig;

  const [view, setView] = usePersistedVizControl<View>(metadata, 'view', 'dotplot');
  const [maxSize, setMaxSize] = usePersistedVizControl(metadata, 'max_dot_size', 22);
  const [minSize, setMinSize] = usePersistedVizControl(metadata, 'min_dot_size', 2);
  const [reverseScale, setReverseScale] = usePersistedVizControl(metadata, 'reverse_scale', false);
  const [colourScale, setColourScale] = usePersistedVizControl<DotPlotColourScale>(metadata, 'colour_scale', 'Viridis');
  const [logTransform, setLogTransform] = usePersistedVizControl(metadata, 'log_transform', false);
  const [geneSort, setGeneSort] = usePersistedVizControl<AxisSort>(metadata, 'gene_sort', 'name');
  const [clusterSort, setClusterSort] = usePersistedVizControl<AxisSort>(metadata, 'cluster_sort', 'name');
  const [annotateTopN, setAnnotateTopN] = usePersistedVizControl(metadata, 'annotate_top_n', 0);
  const [markerOutline, setMarkerOutline] = usePersistedVizControl(metadata, 'marker_outline', true);
  // A dot plot of every gene is both illegible and slow, so by default only the
  // most cluster-discriminating genes are shown; Load-All (below) lifts the cap.
  const [maxGenes, setMaxGenes] = usePersistedVizControl(metadata, 'max_genes', 50);
  const [fullGenes, setFullGenes] = useState<boolean>(false);
  // Enrichment view. The source filter stays local state: it narrows what is on
  // screen rather than saying how the tile should look.
  const [topN, setTopN] = usePersistedVizControl(metadata, 'top_n', 20);
  const [padjThreshold, setPadjThreshold] = usePersistedVizControl(metadata, 'padj_threshold', 0.05);
  const [colourBy, setColourBy] = usePersistedVizControl<ColourBy>(metadata, 'default_colour_by', 'neg_log10_padj');
  const [termSort, setTermSort] = usePersistedVizControl<TermSort>(metadata, 'term_sort', 'nes');
  const [selectedSources, setSelectedSources] = useState<string[]>([]);

  const hasMarkerBinding = Boolean(
    config.cluster_col &&
      config.gene_col &&
      config.mean_expression_col &&
      config.frac_expressing_col,
  );
  const hasEnrichmentBinding = Boolean(config.term_col && config.nes_col);

  const offeredViews = useMemo<View[]>(() => {
    const drawable = ALL_VIEWS.filter((v) =>
      v === 'dotplot' ? hasMarkerBinding : hasEnrichmentBinding,
    );
    const requested = config.views;
    const offered = requested ? drawable.filter((v) => requested.includes(v)) : drawable;
    // An author may narrow the switch, but not to nothing: a tile with no view
    // has no figure to build. With neither table bound the fetch guard below is
    // what reports the missing binding.
    if (offered.length > 0) return offered;
    return drawable.length > 0 ? drawable : ['dotplot'];
  }, [hasMarkerBinding, hasEnrichmentBinding, config.views]);

  // The persisted pick is honoured only while it is on offer, and the fallback
  // happens here rather than through the setter: a config that binds only the
  // enrichment columns keeps the default `view` of 'dotplot' and still renders.
  const activeView: View = offeredViews.includes(view) ? view : offeredViews[0];

  // Union over the offered views, so switching view never refetches.
  const requiredCols = useMemo(() => {
    const cols: string[] = [];
    const add = (col?: string | null) => {
      if (col && !cols.includes(col)) cols.push(col);
    };
    if (offeredViews.includes('dotplot')) {
      add(config.cluster_col);
      add(config.gene_col);
      add(config.mean_expression_col);
      add(config.frac_expressing_col);
    }
    if (offeredViews.includes('enrichment')) {
      add(config.term_col);
      add(config.nes_col);
      add(config.padj_col);
      add(config.gene_count_col);
      add(config.source_col);
    }
    return cols;
  }, [config, offeredViews]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // The server serves this kind whole because the renderer aggregates its rows;
  // past `advanced_viz_no_sample_max_rows` it samples anyway and says so here.
  const [estimated, setEstimated] = useState(false);
  const [clusterUniverse, setClusterUniverse] = useState<string[] | null>(null);
  const [geneUniverse, setGeneUniverse] = useState<string[] | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length === 0) {
      setError('Dot plot: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      filters,
      vizKind: 'dot_plot',
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), JSON.stringify(filters), refreshTick]);

  useEffect(() => {
    if (!metadata.dc_id || !config.cluster_col) return;
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.cluster_col)
      .then((v) => !cancelled && setClusterUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.cluster_col]);

  useEffect(() => {
    if (!metadata.dc_id || !config.gene_col) return;
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.gene_col)
      .then((v) => !cancelled && setGeneUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.gene_col]);

  // A dot plot draws one marker cloud, so it always competes for a bounded
  // WebGL slot; without one the trace renders as downsampled SVG — see
  // webglBudget. The enrichment view draws a top-N of terms, small enough for
  // SVG, so it hands the slot back to whichever tile wants it.
  const glGranted = useWebglSlot(activeView === 'dotplot');

  const markerFigure = useMemo(() => {
    if (!rows || activeView !== 'dotplot') return null;
    // Raw per-(cluster, gene) rows, before the gene cap.
    const clusterAll = (rows[config.cluster_col] || []) as (string | number)[];
    const geneAll = (rows[config.gene_col] || []) as (string | number)[];
    const meanRawAll = (rows[config.mean_expression_col] || []) as number[];
    const fracAll = (rows[config.frac_expressing_col] || []) as number[];

    const meanValsAll = logTransform
      ? meanRawAll.map((v) => Math.log10(Math.max(0, Number(v) || 0) + 1))
      : meanRawAll.map((v) => Number(v) || 0);

    const genesInDataAll = Array.from(new Set(geneAll.map(String)));
    const capActive = !fullGenes && genesInDataAll.length > maxGenes;

    // Gene cap — keep the genes whose mean-expression varies most across
    // clusters: the cluster-discriminating markers a dot plot exists to show.
    // A dot plot of thousands of near-flat genes is both illegible and slow.
    // `geneSort` still orders the visible axis independently (see below);
    // Load-All (`fullGenes`) lifts the cap. When the cap is inactive the raw
    // arrays pass through untouched — no ranking, no per-point copies.
    let clusterVals = clusterAll;
    let geneVals = geneAll;
    let meanRaw = meanRawAll;
    let meanVals = meanValsAll;
    let fracVals = fracAll;
    let pointsShown = geneAll.length;
    if (capActive) {
      const meanByGene = new Map<string, number[]>();
      for (let i = 0; i < geneAll.length; i++) {
        const g = String(geneAll[i]);
        const bucket = meanByGene.get(g);
        if (bucket) bucket.push(meanValsAll[i]);
        else meanByGene.set(g, [meanValsAll[i]]);
      }
      const geneVariance = new Map<string, number>();
      meanByGene.forEach((vals, g) => {
        const n = vals.length;
        if (n === 0) {
          geneVariance.set(g, 0);
          return;
        }
        const mean = vals.reduce((a, b) => a + b, 0) / n;
        const varr = vals.reduce((a, b) => a + (b - mean) * (b - mean), 0) / n;
        geneVariance.set(g, varr);
      });
      const keptSet = new Set(
        [...genesInDataAll]
          .sort((a, b) => (geneVariance.get(b) ?? 0) - (geneVariance.get(a) ?? 0))
          .slice(0, maxGenes),
      );
      // Subset every per-point array to the kept genes so the trace, sizes,
      // annotations and axis aggregation stay aligned.
      const keepIdx: number[] = [];
      for (let i = 0; i < geneAll.length; i++) {
        if (keptSet.has(String(geneAll[i]))) keepIdx.push(i);
      }
      clusterVals = keepIdx.map((i) => clusterAll[i]);
      geneVals = keepIdx.map((i) => geneAll[i]);
      meanRaw = keepIdx.map((i) => meanRawAll[i]);
      meanVals = keepIdx.map((i) => meanValsAll[i]);
      fracVals = keepIdx.map((i) => fracAll[i]);
      pointsShown = keepIdx.length;
    }

    const clustersInData = Array.from(new Set(clusterVals.map(String)));
    const genesInData = Array.from(new Set(geneVals.map(String)));

    // Per-axis aggregation for the "mean" / "frac" sort orders.
    const axisAgg = (key: 'cluster' | 'gene', metric: 'mean' | 'frac'): Map<string, number> => {
      const agg = new Map<string, { sum: number; n: number }>();
      for (let i = 0; i < clusterVals.length; i++) {
        const k = key === 'cluster' ? String(clusterVals[i]) : String(geneVals[i]);
        const v = metric === 'mean' ? meanVals[i] : Math.max(0, Math.min(1, Number(fracVals[i]) || 0));
        const a = agg.get(k) ?? { sum: 0, n: 0 };
        a.sum += v;
        a.n += 1;
        agg.set(k, a);
      }
      const out = new Map<string, number>();
      agg.forEach((v, k) => out.set(k, v.n === 0 ? 0 : v.sum / v.n));
      return out;
    };

    const sortAxis = (
      members: string[],
      sortKey: AxisSort,
      universe: string[] | null,
      axisKey: 'cluster' | 'gene',
    ): string[] => {
      if (sortKey === 'name') {
        return universe ? universe.filter((c) => members.includes(c)) : [...members].sort();
      }
      const score = axisAgg(axisKey, sortKey === 'mean' ? 'mean' : 'frac');
      return [...members].sort((a, b) => (score.get(b) ?? 0) - (score.get(a) ?? 0));
    };

    const clusters = sortAxis(clustersInData, clusterSort, clusterUniverse, 'cluster');
    const genes = sortAxis(genesInData, geneSort, geneUniverse, 'gene');

    // Area-mapped against the data's own maximum, not a linear map onto a unit
    // domain — see dotSizes for why both of those matter here.
    const sizes = dotSizes(fracVals, minSize, maxSize);

    // Annotation overlay: top-N (cluster, gene) cells by frac_expressing.
    const annotations: any[] = [];
    if (annotateTopN > 0) {
      const ranked = fracVals
        .map((f, i) => ({ i, f: Number(f) || 0 }))
        .filter((r) => r.f > 0)
        .sort((a, b) => b.f - a.f)
        .slice(0, annotateTopN);
      for (const r of ranked) {
        annotations.push({
          x: String(clusterVals[r.i] ?? ''),
          y: String(geneVals[r.i] ?? ''),
          text: r.f.toFixed(2),
          showarrow: false,
          font: { size: 9, color: colorScheme === 'dark' ? '#fff' : '#111' },
        });
      }
    }

    const meanLabel = logTransform
      ? `log10(${config.mean_expression_col}+1)`
      : config.mean_expression_col;

    return {
      pointsShown,
      pointsTotal: geneAll.length,
      capActive,
      // Categories on the y axis, i.e. the rows the tile actually has to be
      // tall enough for, post-cap, post-sort. Feeds the content demand.
      rowsDrawn: genes.length,
      // Built from the same values the markers were, so the key states the
      // scale actually on screen — including after the gene cap narrowed it.
      sizeKey: dotSizeKey(fracVals, minSize, maxSize),
      data: [
        adaptGlTrace(
          {
            type: 'scattergl' as const,
            mode: 'markers' as const,
            x: clusterVals.map(String),
            y: geneVals.map(String),
            customdata: fracVals.map((f, i) => [
              String(geneVals[i] ?? ''),
              String(clusterVals[i] ?? ''),
              Number(f).toFixed(3),
              Number(meanRaw[i]).toFixed(3),
            ]),
            hovertemplate:
              `<b>%{customdata[0]}</b> in <b>%{customdata[1]}</b>` +
              `<br>${config.mean_expression_col}: %{customdata[3]}` +
              `<br>${config.frac_expressing_col}: %{customdata[2]}` +
              `<extra></extra>`,
            marker: {
              size: sizes,
              color: meanVals,
              colorscale: sequentialScale(colourScale, isDark),
              reversescale: reverseScale,
              showscale: true,
              colorbar: {
                title: { text: meanLabel, side: 'right' as const },
                thickness: 12,
                len: 0.85,
              },
              // marker.line (outline) is poorly supported under scattergl, so
              // the outline is honoured only on the SVG fallback path.
              line:
                markerOutline && !glGranted
                  ? {
                      width: 0.6,
                      color: colorScheme === 'dark' ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.85)',
                    }
                  : { width: 0 },
            },
          },
          glGranted,
        ),
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 120, r: 60, t: 20, b: 100 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          type: 'category' as const,
          categoryorder: 'array' as const,
          categoryarray: clusters,
          tickangle: -45,
          title: { text: config.cluster_col },
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          type: 'category' as const,
          categoryorder: 'array' as const,
          categoryarray: genes,
          autorange: 'reversed' as const,
          title: { text: config.gene_col },
        },
        annotations,
        showlegend: false,
        autosize: true,
      },
    };
  }, [
    rows,
    activeView,
    config,
    maxSize,
    minSize,
    reverseScale,
    colourScale,
    logTransform,
    geneSort,
    clusterSort,
    annotateTopN,
    markerOutline,
    maxGenes,
    fullGenes,
    glGranted,
    colorScheme,
    theme,
    isDark,
    clusterUniverse,
    geneUniverse,
  ]);

  const sources = useMemo(() => {
    if (!rows || !config.source_col) return [] as string[];
    const seen = new Set<string>();
    for (const v of (rows[config.source_col] || []) as unknown[]) seen.add(String(v ?? ''));
    return Array.from(seen).sort();
  }, [rows, config.source_col]);

  const enrichmentFigure = useMemo(() => {
    if (!rows || activeView !== 'enrichment') return null;
    const terms = (rows[config.term_col as string] || []) as (string | number)[];
    const nesArr = (rows[config.nes_col as string] || []) as number[];
    const padjArr = config.padj_col ? ((rows[config.padj_col] || []) as number[]) : null;
    const countArr = config.gene_count_col
      ? ((rows[config.gene_count_col] || []) as number[])
      : null;
    const srcArr = config.source_col ? (rows[config.source_col] as (string | number)[]) : null;

    type Row = { term: string; nes: number; padj: number; count: number; src: string };
    const collected: Row[] = [];
    for (let i = 0; i < terms.length; i++) {
      const nes = Number(nesArr[i]);
      if (!Number.isFinite(nes)) continue;
      // The significance column is an optional binding, so an unbound one means
      // "no cutoff to apply" rather than "cut everything".
      const padj = padjArr ? Number(padjArr[i]) : 1;
      if (padjArr && (!Number.isFinite(padj) || padj > padjThreshold)) continue;
      const src = srcArr ? String(srcArr[i] ?? '') : '';
      if (selectedSources.length > 0 && srcArr && !selectedSources.includes(src)) continue;
      collected.push({
        term: String(terms[i] ?? ''),
        nes,
        padj,
        count: countArr ? Number(countArr[i]) || 0 : 0,
        src,
      });
    }
    // Top-N by significance (smallest padj wins).
    collected.sort((a, b) => a.padj - b.padj);
    const top = collected.slice(0, topN);
    // Then re-sort for the y-axis. Plotly draws the first item at the bottom,
    // so each comparator puts the most notable term last.
    top.sort((a, b) => {
      if (termSort === 'significance') return b.padj - a.padj;
      if (termSort === 'gene_count') return a.count - b.count;
      if (termSort === 'name') return b.term.localeCompare(a.term);
      return a.nes - b.nes;
    });

    if (top.length === 0) {
      return null;
    }

    // Gene-set size drives the marker area, through the very scale the marker
    // view uses, so whoever learned to read one dot plot can read this one.
    const counts = top.map((r) => r.count);
    const sizes = dotSizes(counts, minSize, maxSize);

    // Annotation overlay: the N most significant terms get their gene count
    // written beside the dot, since size alone is hard to read off precisely.
    const annotations: any[] = [];
    if (annotateTopN > 0) {
      const ranked = [...top].sort((a, b) => a.padj - b.padj).slice(0, annotateTopN);
      for (const r of ranked) {
        annotations.push({
          x: r.nes,
          y: r.term,
          text: String(r.count),
          showarrow: false,
          xanchor: 'left',
          // Clear the marker itself, which grows with max_dot_size.
          xshift: maxSize / 2 + 4,
          // No font colour: applyLayoutTheme tints unstyled annotations.
          font: { size: 9 },
        });
      }
    }

    // Colour-by maps the user's choice to (a) per-point colour values and
    // (b) the colourscale + colourbar title. NES sign is the only discrete
    // mode, encoded as the integer sign so plotly draws two colour buckets.
    const colourValues: number[] =
      colourBy === 'neg_log10_padj'
        ? top.map((r) => -Math.log10(Math.max(r.padj, 1e-300)))
        : colourBy === 'abs_nes'
          ? top.map((r) => Math.abs(r.nes))
          : colourBy === 'gene_count'
            ? top.map((r) => r.count)
            : top.map((r) => Math.sign(r.nes));
    // 'Auto': NES sign uses a discrete blue (down) / red (up) palette; the
    // other modes use perceptually-uniform sequential scales. YlOrRd reads
    // better than Viridis when the user picked |NES| (magnitude-only, warm
    // end signals "stronger enrichment"). A named scale wins over all of it,
    // including NES sign, where cmin/cmax below keep the two buckets apart.
    const autoScale: string | (string | number)[][] =
      colourBy === 'nes_sign'
        ? [
            [0.0, '#1f77b4'],
            [0.49, '#1f77b4'],
            [0.51, '#d62728'],
            [1.0, '#d62728'],
          ]
        : colourBy === 'abs_nes'
          ? isDark
            ? 'Plasma'
            : 'YlOrRd'
          : isDark
            ? 'Plasma'
            : 'Viridis';
    const colorscale: string | (string | number)[][] =
      colourScale === 'Auto' ? autoScale : colourScale;
    const colourbarTitle: string =
      colourBy === 'neg_log10_padj'
        ? '-log10(padj)'
        : colourBy === 'abs_nes'
          ? '|NES|'
          : colourBy === 'gene_count'
            ? 'gene count'
            : 'NES sign';

    return {
      // Terms on the y axis after the top-N cut, the enrichment view's answer
      // to the marker view's gene count. Feeds the content demand.
      rowsDrawn: top.length,
      sizeKey: dotSizeKey(counts, minSize, maxSize),
      data: [
        {
          type: 'scatter' as const,
          mode: 'markers' as const,
          x: top.map((r) => r.nes),
          y: top.map((r) => r.term),
          // Slot 3 carries the term, so an analysis group can be read back off
          // a point the way the marker view reads its gene and its cluster.
          customdata: top.map((r) => [r.padj, r.count, r.src, r.term]),
          hovertemplate:
            `<b>%{y}</b><br>NES: %{x:.2f}` +
            (config.padj_col ? `<br>padj: %{customdata[0]:.2e}` : '') +
            (config.gene_count_col ? `<br>genes: %{customdata[1]}` : '') +
            (config.source_col ? `<br>source: %{customdata[2]}` : '') +
            `<extra></extra>`,
          marker: {
            size: sizes,
            color: colourValues,
            colorscale: colorscale,
            reversescale: reverseScale,
            showscale: true,
            // Discrete two-bucket palette needs an explicit min/max so the
            // boundary lands at 0 rather than auto-fitting to the data.
            ...(colourBy === 'nes_sign' ? { cmin: -1, cmax: 1 } : {}),
            colorbar: {
              title: { text: colourbarTitle, side: 'right' },
              thickness: 10,
              len: 0.85,
              ...(colourBy === 'nes_sign'
                ? { tickvals: [-1, 1], ticktext: ['down', 'up'] }
                : {}),
            },
            line: markerOutline
              ? {
                  width: 0.6,
                  color: isDark ? alpha(theme.black, 0.7) : alpha(theme.white, 0.85),
                }
              : { width: 0 },
          },
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 220, r: 60, t: 16, b: 48 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: 'NES (normalized enrichment score)' },
          zeroline: true,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          automargin: true,
          ticks: '',
          showgrid: true,
        },
        annotations,
        showlegend: false,
        autosize: true,
      },
    };
  }, [
    rows,
    activeView,
    config,
    topN,
    padjThreshold,
    selectedSources,
    colourBy,
    colourScale,
    reverseScale,
    maxSize,
    minSize,
    termSort,
    annotateTopN,
    markerOutline,
    isDark,
    theme,
  ]);

  const figure = activeView === 'enrichment' ? enrichmentFigure : markerFigure;

  // Rows on the y axis (genes, or enriched terms) at a height a dot and its
  // tick label stay legible at, inside the axis furniture: the tilted cluster
  // labels along the bottom, the title strip, and the dot-size key drawn
  // under the plot. Keyed on the count, so re-sorting or recolouring the same
  // rows republishes nothing.
  const rowsDrawn = figure?.rowsDrawn ?? 0;
  const contentDemand = useMemo(
    () => demandForItems(rowsDrawn, DOT_ROW_PX, DOT_PLOT_CHROME_PX),
    [rowsDrawn],
  );

  const viewControl =
    offeredViews.length > 1 ? (
      <VizSegmented
        aria-label="View"
        value={activeView}
        onChange={(v) => setView(v as View)}
        data={offeredViews.map((v) => ({ value: v, label: VIEW_LABELS[v] }))}
      />
    ) : null;

  // Encoding tier: which view, which terms or genes are on the axes, in what
  // order and under which colour semantics. Handed to the frame as a flat
  // fragment; the strip's grid owns the widths.
  const primaryControls = useMemo(
    () => (
      <>
        {viewControl}
        {activeView === 'enrichment' ? (
          <>
            <VizControlGroup title="Terms">
              {sources.length > 0 ? (
                <VizMultiSelect
                  label="Source"
                  value={selectedSources}
                  onChange={setSelectedSources}
                  data={sources}
                  placeholder="all sources"
                  clearable
                />
              ) : null}
              <VizNumberInput
                label="Top-N pathways"
                value={topN}
                onChange={(v) => setTopN(Math.max(1, Number(v) || 20))}
                min={1}
                max={100}
              />
              <VizNumberInput
                label="padj threshold"
                value={padjThreshold}
                onChange={(v) => setPadjThreshold(Math.max(0, Math.min(1, Number(v) || 0.05)))}
                min={0}
                max={1}
                step={0.01}
                decimalScale={3}
              />
            </VizControlGroup>
            <VizControlGroup title="Colour and order">
              <VizSelect
                label="Colour by"
                value={colourBy}
                onChange={(v) => v && setColourBy(v as ColourBy)}
                data={[
                  { value: 'neg_log10_padj', label: '-log10(padj)' },
                  { value: 'abs_nes', label: '|NES|' },
                  { value: 'nes_sign', label: 'NES sign (up / down)' },
                  { value: 'gene_count', label: 'Gene count' },
                ]}
                allowDeselect={false}
              />
              <VizSelect
                label="Sort terms"
                value={termSort}
                onChange={(v) => v && setTermSort(v as TermSort)}
                data={[
                  { value: 'nes', label: 'NES' },
                  { value: 'significance', label: 'Significance' },
                  { value: 'gene_count', label: 'Gene count' },
                  { value: 'name', label: 'Name' },
                ]}
                allowDeselect={false}
              />
            </VizControlGroup>
          </>
        ) : (
          <VizControlGroup title="Axes">
            <VizSelect
              label="Sort genes"
              value={geneSort}
              onChange={(v) => v && setGeneSort(v as AxisSort)}
              data={[
                { value: 'name', label: 'Name' },
                { value: 'mean', label: 'Mean expression' },
                { value: 'frac', label: 'Fraction expressing' },
              ]}
              allowDeselect={false}
            />
            <VizSelect
              label="Sort clusters"
              value={clusterSort}
              onChange={(v) => v && setClusterSort(v as AxisSort)}
              data={[
                { value: 'name', label: 'Name' },
                { value: 'mean', label: 'Mean expression' },
                { value: 'frac', label: 'Fraction expressing' },
              ]}
              allowDeselect={false}
            />
            <VizNumberInput
              label="Max genes"
              value={maxGenes}
              onChange={(v) => setMaxGenes(Math.max(5, Math.min(500, Number(v) || 50)))}
              min={5}
              max={500}
              disabled={fullGenes}
            />
          </VizControlGroup>
        )}
      </>
    ),
    [
      viewControl,
      activeView,
      sources,
      selectedSources,
      topN,
      padjThreshold,
      colourBy,
      termSort,
      geneSort,
      clusterSort,
      maxGenes,
      fullGenes,
    ],
  );

  // Cosmetic tier: how the same dots are painted.
  const controls = useMemo(
    () => (
      <>
        <VizControlGroup title="Colour">
          <VizSelect
            label="Colourscale"
            description="Auto follows the colour-by mode and the theme"
            value={colourScale}
            onChange={(v) => v && setColourScale(v as DotPlotColourScale)}
            data={['Auto', ...COLOUR_SCALES]}
            allowDeselect={false}
          />
          <VizSwitch
            checked={reverseScale}
            onChange={(e) => setReverseScale(e.currentTarget.checked)}
            label="Reverse colourscale"
          />
          {activeView === 'dotplot' ? (
            <VizSwitch
              checked={logTransform}
              onChange={(e) => setLogTransform(e.currentTarget.checked)}
              label={`log10(${config.mean_expression_col}+1)`}
            />
          ) : null}
        </VizControlGroup>
        <VizControlGroup title="Markers">
          <VizNumberInput
            label="Max dot size"
            value={maxSize}
            onChange={(v) => setMaxSize(Math.max(4, Math.min(60, Number(v) || 22)))}
            min={4}
            max={60}
          />
          <VizNumberInput
            label="Min dot size"
            value={minSize}
            onChange={(v) => setMinSize(Math.max(0, Math.min(20, Number(v) || 2)))}
            min={0}
            max={20}
          />
          <VizSwitch
            checked={markerOutline}
            onChange={(e) => setMarkerOutline(e.currentTarget.checked)}
            label="Outline"
          />
        </VizControlGroup>
        <VizControlGroup title="Labels">
          <VizNumberInput
            label={activeView === 'enrichment' ? 'Annotate top-N' : 'Annotate top-N frac'}
            value={annotateTopN}
            onChange={(v) => setAnnotateTopN(Math.max(0, Math.min(40, Number(v) || 0)))}
            min={0}
            max={40}
          />
          <VizFullRow>
            <Text size="xs" c="dimmed">
              {activeView === 'enrichment'
                ? 'Gene count on the most significant dots; 0 = off'
                : '0 = off'}
            </Text>
          </VizFullRow>
        </VizControlGroup>
      </>
    ),
    [
      activeView,
      colourScale,
      reverseScale,
      logTransform,
      maxSize,
      minSize,
      annotateTopN,
      markerOutline,
      config.mean_expression_col,
    ],
  );

  // Recolour by the dashboard's analysis groups. The join is on values, and
  // `splitFigureByGroups` returns the figure untouched when no point matches.
  // A dot plot is a matrix: slot 0 of `customdata` is the feature, slot 1 the
  // cluster/sample. Both are legitimate group keys here — a group of samples is
  // the common case and slot 0 alone never matched it — so both are offered and
  // the first that belongs to a group wins. The enrichment view has a single
  // identity, the term, and carries it in slot 3.
  const groupedFigure = useMemo(
    () =>
      figure
        ? splitFigureByGroups(figure, {
            groupRender,
            identitySlot: activeView === 'enrichment' ? 3 : 0,
            identitySlots: activeView === 'enrichment' ? [] : [1],
            facetable: false,
            showLegend: true,
          })
        : figure,
    [figure, groupRender, activeView],
  );
  // Whether any dot matched, for the dispatch's "not grouped" badge.
  useReportGroupColouring(groupRender, figure, groupedFigure);

  const sizeKeyLabel =
    activeView === 'enrichment'
      ? config.gene_count_col || 'gene set size'
      : config.frac_expressing_col;

  // Themed once per figure so the annotation layer can memoise on them.
  const plotData = useMemo(
    () => (groupedFigure ? applyDataTheme(groupedFigure.data, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );
  const plotLayout = useMemo(
    () => (groupedFigure ? applyLayoutTheme(groupedFigure.layout as any, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );
  // Chart annotations. In the marker view a dot is a gene in a cluster, keyed
  // on two columns, so marked dots are stored as (category) coordinates. In
  // the enrichment view a dot is a term, carried in slot 3 of `customdata`,
  // which is what marked points are keyed on. The views have different axes,
  // so annotations are stored per view once the tile offers both.
  const annotations = usePlotAnnotationLayer({
    componentIndex: String(metadata.index),
    enabled: supportsAdvancedVizAnnotation(metadata),
    data: plotData,
    layout: plotLayout,
    ...(activeView === 'enrichment'
      ? { pointIdIndex: 3, pointIdColumn: config.term_col || undefined }
      : {}),
    variant: offeredViews.length > 1 ? activeView : undefined,
  });

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || (activeView === 'enrichment' ? 'Pathway enrichment' : 'Dot plot')}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      badges={annotations.badges}
      reduction={
        markerFigure && (markerFigure.capActive || fullGenes)
          ? {
              // Points on screen — post-cap, and clamped to the SVG budget when
              // this plot missed a WebGL slot and fell back to downsampled SVG.
              displayed: glGranted
                ? markerFigure.pointsShown
                : Math.min(markerFigure.pointsShown, SVG_MAX_POINTS),
              total: markerFigure.pointsTotal,
              sampled: markerFigure.capActive,
              full: fullGenes,
              loading: false,
              onToggle: () => setFullGenes((v) => !v),
            }
          : undefined
      }
    >
      {groupedFigure ? (
        <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}>
          <Plot
            data={annotations.data as any}
            layout={annotations.layout as any}
            useResizeHandler
            style={{ width: '100%', flex: 1, minHeight: 0 }}
            config={{ displaylogo: false, responsive: true } as any}
            {...annotations.plotProps()}
          />
          {/* Plotly has no size legend, and a legend-only trace cannot stand in
              for one: it clamps legend markers to 16 px (legend/style.js), so
              the top of a 3-26 px scale would collapse and the key would
              understate the very dots it explains. Drawn here in SVG instead,
              at the exact diameters the plot used. */}
          <DotSizeKey entries={figure?.sizeKey ?? []} label={sizeKeyLabel} />
          {annotations.toolbar}
        </div>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default DotPlotRenderer;
