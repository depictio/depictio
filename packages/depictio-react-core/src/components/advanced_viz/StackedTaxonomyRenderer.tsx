import React, { useEffect, useMemo, useState } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';
import {
  VizControlGroup,
  VizNumberInput,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { isStaleFetch } from '../../fetchQueue';
import { columnCategoryColors } from '../../categoryColors';
import { resolveCategoricalPalette, stableColorMap } from '../../colors';
import { useCategoryColorSource } from '../../hooks/useCategoryColors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { usePlotAnnotationLayer } from '../annotations/usePlotAnnotationLayer';
import { supportsAdvancedVizAnnotation } from '../../annotations/plotDecorate';
import { usePersistedVizControl } from './usePersistedVizControl';
import { withRanksInOrder } from './phylo/view';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { demandForPx } from './contentDemand';

/** The stacked bars run vertically: samples are the x axis, so the tile's
 *  height is furniture, not a count. This is the plot area a stack of
 *  proportions stays readable in once the tilted sample labels and the axis
 *  title have taken their share. */
const TAXONOMY_PLOT_PX = 300;
/** One wrapped row of the horizontal legend under the plot. */
const LEGEND_ROW_PX = 22;
/** Legend entries that fit on one row at a typical tile width. */
const LEGEND_PER_ROW = 4;
/** One annotation strip, matching the 22 px the figure's margins reserve. */
const STRIP_BAND_PX = 22;

/** Generic per-sample categorical annotation strip drawn above/below the
 *  stacked bars. Reusable across any viz with a sample axis when the DC
 *  carries a categorical metadata column the user wants visualised as a
 *  colour band (habitat, batch, treatment, timepoint, …). */
interface AnnotationStrip {
  /** Metadata column in the DC; values are looked up per sample. */
  column: string;
  /** Optional label shown to the left of the strip. Defaults to `column`. */
  label?: string;
  /** Where to draw the strip relative to the chart. */
  position?: 'top' | 'bottom';
  /** Per-category colour overrides; falls back to TAB10-style cycling. */
  palette?: Record<string, string> | null;
}

interface StackedTaxonomyConfig {
  sample_id_col: string;
  taxon_col: string;
  rank_col: string;
  abundance_col: string;
  default_rank?: string | null;
  top_n?: number;
  sort_by?: 'abundance' | 'alphabetical';
  normalise_to_one?: boolean;
  /** Categorical annotation strips drawn alongside the bars. Each strip
   *  reads its values from the row's metadata column at the matching
   *  sample. Renderer ensures the fetched column list includes these. */
  annotation_strips?: AnnotationStrip[] | null;
  /** Taxon → colour overrides. The default cycle has twelve hues, so a top-15
   *  view always repeats some; pinning the taxa a reader compares keeps them
   *  apart and keeps them the same colour across dashboards. */
  taxon_palette?: Record<string, string> | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: StackedTaxonomyConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/** Fallback cycle for an unbranded deployment; a brand's colorway wins. */
const PALETTE = [
  '#1c7ed6', '#e64980', '#fab005', '#37b24d', '#7048e8', '#f76707',
  '#0ca678', '#d6336c', '#15aabf', '#fd7e14', '#82c91e', '#ae3ec9',
];

/** Runs of equal consecutive values, by position. */
function categoryRuns(values: readonly string[]): { value: string; start: number; end: number }[] {
  const runs: { value: string; start: number; end: number }[] = [];
  values.forEach((v, i) => {
    const last = runs[runs.length - 1];
    if (last && last.value === v && last.end === i - 1) last.end = i;
    else runs.push({ value: v, start: i, end: i });
  });
  return runs;
}

/** Dark or light text, whichever reads on a fill. */
function textOn(fill: string | undefined): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(fill ?? '').trim());
  if (!m) return '#212529';
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return lum < 0.4 ? '#ffffff' : '#212529';
}

const StackedTaxonomyRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as StackedTaxonomyConfig;
  const palette = resolveCategoricalPalette(theme, PALETTE);
  const categorySource = useCategoryColorSource();

  const [rank, setRank] = usePersistedVizControl<string | null>(metadata, 'default_rank', null);
  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n', 20);
  const [normalise, setNormalise] = usePersistedVizControl<boolean>(
    metadata,
    'normalise_to_one',
    true,
  );
  type SampleSort = 'input' | 'total_abundance' | 'first_taxon';
  const [sampleSort, setSampleSort] = usePersistedVizControl<SampleSort>(metadata, 'sample_sort', 'input');
  const [showLegend, setShowLegend] = usePersistedVizControl(metadata, 'show_legend', true);
  const [logY, setLogY] = usePersistedVizControl(metadata, 'log_y', false);

  // Stable taxon→colour universe so a habitat filter doesn't shuffle the
  // top-N taxon colours. Pulled from the DC's unique values for taxon_col;
  // falls back to the filtered ordering when the endpoint is slow/errors.
  const [taxonUniverse, setTaxonUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    if (!metadata.dc_id || !config.taxon_col) {
      setTaxonUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.taxon_col)
      .then((values) => {
        if (!cancelled) setTaxonUniverse(values);
      })
      .catch(() => {
        /* best-effort — colours stay reactive to the current filter */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.taxon_col]);

  const requiredCols = useMemo(
    () => {
      const base = [
        config.sample_id_col,
        config.taxon_col,
        config.rank_col,
        config.abundance_col,
      ].filter(Boolean) as string[];
      // Append columns required by any annotation strip so the renderer can
      // look up per-sample categorical values without a second fetch.
      for (const s of config.annotation_strips ?? []) {
        if (s.column && !base.includes(s.column)) base.push(s.column);
      }
      return base;
    },
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // Server-side downsampling state (mirrors the scatter-figure Load-All UX).
  const [fullLoad, setFullLoad] = useState(false);
  const [reduction, setReduction] = useState<{
    displayed: number;
    total: number;
    sampled: boolean;
    degraded: boolean;
  } | null>(null);

  const filterSig = JSON.stringify(filters);
  useEffect(() => {
    setFullLoad(false);
  }, [filterSig]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Stacked taxonomy: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchAdvancedVizData(
      {
        wfId: metadata.wf_id,
        dcId: metadata.dc_id,
        columns: requiredCols,
        filters,
        fullLoad,
        vizKind: 'stacked_taxonomy',
      },
      ctrl.signal,
    )
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setReduction({
          displayed: res.row_count,
          total: res.total_rows ?? res.row_count,
          sampled: Boolean(res.sampled),
          degraded: Boolean(res.sampling?.degraded),
        });
      })
      .catch((err: unknown) => {
        if (cancelled || isStaleFetch(err)) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), filterSig, refreshTick, fullLoad]);

  const { figure, allRanks, seriesCount, stripCount } = useMemo(() => {
    if (!rows) return { figure: null, allRanks: [] as string[], seriesCount: 0, stripCount: 0 };
    const samples = (rows[config.sample_id_col] || []).map((v) => String(v ?? '')) as string[];
    // A lineage that stops above the shown rank ("Eukaryota;") has a blank leaf.
    // Named, so it gets a legend entry a reader can identify rather than an
    // unlabelled swatch.
    const taxa = (rows[config.taxon_col] || []).map(
      (v) => String(v ?? '').trim() || 'Unclassified',
    ) as string[];
    const ranks = (rows[config.rank_col] || []).map((v) => String(v ?? '')) as string[];
    const ab = (rows[config.abundance_col] || []) as number[];

    const seen = Array.from(new Set(ranks));
    // Root to leaf in the picker; unset, the rank stays the one the table
    // lists first, as before.
    const allRanks = withRanksInOrder(seen);
    const activeRank = rank || seen[0] || null;

    // Filter to active rank, then aggregate (sample × taxon → abundance).
    const cellTotals = new Map<string, Map<string, number>>(); // sample -> taxon -> abundance
    for (let i = 0; i < samples.length; i++) {
      if (activeRank && ranks[i] !== activeRank) continue;
      const s = samples[i];
      const t = taxa[i];
      const v = Number(ab[i]) || 0;
      if (!cellTotals.has(s)) cellTotals.set(s, new Map());
      const inner = cellTotals.get(s)!;
      inner.set(t, (inner.get(t) || 0) + v);
    }

    // Rank taxa by total abundance and keep top-N; lump others into "Other".
    const taxonTotals = new Map<string, number>();
    for (const inner of cellTotals.values()) {
      for (const [t, v] of inner.entries()) {
        taxonTotals.set(t, (taxonTotals.get(t) || 0) + v);
      }
    }
    const topTaxa = Array.from(taxonTotals.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, topN)
      .map(([t]) => t);
    const topSet = new Set(topTaxa);

    // Sort samples by the user's choice. `input` preserves insertion order
    // (Map preserves insertion order, so just spread the keys); `total_abundance`
    // sorts descending by per-sample sum; `first_taxon` sorts descending by
    // the most-abundant taxon's value per sample so the most-abundant cohort
    // forms a clear left-to-right gradient.
    const topTaxaSorted = Array.from(taxonTotals.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([t]) => t);
    const firstTaxon = topTaxaSorted[0];
    const sampleKeys = Array.from(cellTotals.keys());
    const orderedSamples = (() => {
      if (sampleSort === 'input') return sampleKeys;
      const score = (s: string): number => {
        const inner = cellTotals.get(s) || new Map();
        if (sampleSort === 'first_taxon' && firstTaxon) return inner.get(firstTaxon) || 0;
        let total = 0;
        for (const v of inner.values()) total += v;
        return total;
      };
      return [...sampleKeys].sort((a, b) => score(b) - score(a));
    })();

    const tracesByTaxon = new Map<string, number[]>();
    for (const t of [...topTaxa, 'Other']) tracesByTaxon.set(t, orderedSamples.map(() => 0));

    orderedSamples.forEach((s, sIdx) => {
      const inner = cellTotals.get(s) || new Map();
      let total = 0;
      for (const v of inner.values()) total += v;
      for (const [t, v] of inner.entries()) {
        const bucket = topSet.has(t) ? t : 'Other';
        const arr = tracesByTaxon.get(bucket)!;
        arr[sIdx] += normalise && total > 0 ? v / total : v;
      }
    });

    // Stable taxon→colour map so filtering (e.g. by habitat) doesn't reshuffle
    // the top-N colours. Universe = all taxa in the DC; fallback = the filtered
    // top-N set ordered as they appear in tracesByTaxon.
    const taxaForPalette = Array.from(tracesByTaxon.keys()).filter((t) => t !== 'Other');
    // A taxon wears the dashboard's colour for it: under the rank shown (a
    // Phylum pinned in `category_colors.Phylum`), else under the taxon column,
    // the component's own `taxon_palette` winning value by value.
    const taxonPinned = columnCategoryColors(categorySource, config.taxon_col, {
      ...(columnCategoryColors(categorySource, activeRank) ?? {}),
      ...(config.taxon_palette ?? {}),
    });
    const colourSource = stableColorMap(taxonUniverse ?? taxaForPalette, palette, taxonPinned);
    const data = Array.from(tracesByTaxon.entries())
      .filter(([, arr]) => arr.some((v) => v > 0))
      .map(([t, arr]) => ({
        type: 'bar' as const,
        name: t,
        x: orderedSamples,
        y: arr,
        marker: { color: t === 'Other' ? '#adb5bd' : colourSource.get(t) },
      }));

    // Annotation strips — one row of per-sample coloured cells per configured
    // strip, each a one-row heatmap on its own y-axis sharing the bars' x-axis.
    // A heatmap rather than layout shapes: shapes take no hover and no legend,
    // so a strip told nothing about which category a colour stood for.
    const strips = (config.annotation_strips ?? []).filter((s) => s && s.column);
    const stripTraces: Record<string, unknown>[] = [];
    // A strip's categories were legend entries after the taxa, one legend
    // holding two keys that read as one. A strip whose categories each hold a
    // block wide enough is labelled on itself instead; the others get a key
    // of their own above the plot.
    const stripLabels: Record<string, unknown>[] = [];
    let stripKey = false;
    const stripAxes: Record<string, unknown> = {};
    const STRIP_BAND = 0.045; // each strip occupies ~4.5% of paper height
    const STRIP_GAP = 0.012;
    const step = STRIP_BAND + STRIP_GAP;
    const nTop = strips.filter((s) => s.position === 'top').length;
    const nBottom = strips.length - nTop;
    const barDomain: [number, number] = [nBottom * step, 1 - nTop * step];
    if (strips.length > 0) {
      const sampleCol = rows[config.sample_id_col] as unknown[] | undefined;
      let topCursor = 1;
      let bottomCursor = 0;
      strips.forEach((strip, k) => {
        const sampleToValue = new Map<string, string>();
        const stripCol = rows[strip.column] as unknown[] | undefined;
        if (sampleCol && stripCol) {
          for (let i = 0; i < sampleCol.length; i++) {
            const key = String(sampleCol[i] ?? '');
            if (!sampleToValue.has(key)) sampleToValue.set(key, String(stripCol[i] ?? '—'));
          }
        }
        const values = orderedSamples.map((s) => sampleToValue.get(s) ?? '—');
        // Stable category→colour for THIS strip's categories: the dashboard's
        // colours for its column, the strip's own `palette` winning per value.
        const categories = Array.from(new Set(values)).sort();
        const stripPalette = stableColorMap(
          categories,
          palette,
          columnCategoryColors(categorySource, strip.column, strip.palette),
        );
        const n = categories.length;
        // Category i gets z = i; zmin/zmax at ±0.5 put each category in its own
        // [i/n, (i+1)/n] band of the colorscale, a step function.
        const colorscale = categories.flatMap((c, i) => [
          [i / n, stripPalette.get(c)],
          [(i + 1) / n, stripPalette.get(c)],
        ]);

        const isTop = strip.position === 'top';
        const domain: [number, number] = isTop
          ? [topCursor - STRIP_BAND, topCursor]
          : [bottomCursor, bottomCursor + STRIP_BAND];
        if (isTop) topCursor -= step;
        else bottomCursor += step;

        const axis = `y${k + 2}`;
        const label = strip.label || strip.column;
        stripAxes[`yaxis${k + 2}`] = {
          domain,
          anchor: 'x',
          fixedrange: true,
          showgrid: false,
          zeroline: false,
          ticks: '',
          tickfont: { size: 10, color: isDark ? '#ced4da' : '#495057' },
        };
        stripTraces.push({
          type: 'heatmap',
          x: orderedSamples,
          y: [label],
          z: [values.map((v) => categories.indexOf(v))],
          customdata: [values],
          zmin: -0.5,
          zmax: n - 0.5,
          colorscale,
          showscale: false,
          xgap: 0,
          yaxis: axis,
          hovertemplate: `%{x}<br>${label}: %{customdata}<extra></extra>`,
        });
        const runs = categoryRuns(values);
        const minRun = Math.max(2, Math.ceil(values.length * 0.12));
        const longest = new Map<string, { start: number; end: number }>();
        for (const r of runs) {
          const best = longest.get(r.value);
          if (!best || r.end - r.start > best.end - best.start) longest.set(r.value, r);
        }
        const labelled = categories.every((c) => {
          const r = longest.get(c);
          return r != null && r.end - r.start + 1 >= minRun;
        });
        if (labelled) {
          for (const c of categories) {
            const r = longest.get(c)!;
            stripLabels.push({
              xref: 'x',
              yref: axis,
              // A category axis places numbers by position: the run's middle.
              x: (r.start + r.end) / 2,
              y: 0,
              text: c,
              showarrow: false,
              font: { size: 10, color: textOn(stripPalette.get(c)) },
            });
          }
        } else {
          stripKey = true;
          categories.forEach((c) =>
            stripTraces.push({
              type: 'scatter',
              mode: 'markers',
              x: [null],
              y: [null],
              name: c,
              legend: 'legend2',
              legendgroup: `strip-${strip.column}`,
              legendgrouptitle: { text: label },
              marker: { color: stripPalette.get(c), symbol: 'square', size: 10 },
              hoverinfo: 'skip',
            }),
          );
        }
      });
    }

    return {
      // The legend and the strips are what actually grows this tile, so the
      // figure reports them back rather than the renderer re-deriving them.
      seriesCount: data.length,
      stripCount: strips.length,
      figure: {
        data: [...data, ...stripTraces],
        layout: {
          ...plotlyThemeFragment(isDark, theme),
          barmode: 'stack' as const,
          margin: { l: 60, r: 20, t: stripKey ? 44 : 30, b: 70 },
          annotations: stripLabels,
          xaxis: {
            ...plotlyAxisOverrides(isDark, theme),
            title: { text: config.sample_id_col },
            tickangle: -45,
            // Pinned to the bottom of the plot area, below any bottom strip,
            // and to the bars' sample order so the strips line up with them.
            anchor: 'free' as const,
            position: 0,
            categoryorder: 'array' as const,
            categoryarray: orderedSamples,
          },
          ...stripAxes,
          // When normalise is ON we lock the y-axis to [0, 1] and format ticks
          // as percentages — this gives the toggle a visible effect even when
          // the input data is already pre-normalised (the old behaviour: both
          // toggle states rendered identically because each sample already
          // summed to 1).
          yaxis: normalise
            ? {
                ...plotlyAxisOverrides(isDark, theme),
                domain: barDomain,
                title: { text: 'Relative abundance' },
                range: [0, 1],
                tickformat: '.0%',
              }
            : {
                ...plotlyAxisOverrides(isDark, theme),
                domain: barDomain,
                title: { text: config.abundance_col },
                // Log y is only meaningful for raw counts — normalised data
                // is bounded [0,1] and log would compress to noise.
                ...(logY ? { type: 'log' as const } : {}),
              },
          showlegend: showLegend,
          // The taxa's key, titled with the rank they are.
          legend: {
            orientation: 'h',
            y: -0.25,
            title: { text: `${activeRank ?? 'Taxon'} ` },
          },
          ...(stripKey
            ? {
                legend2: {
                  orientation: 'h',
                  x: 1,
                  xanchor: 'right',
                  y: 1,
                  yanchor: 'bottom',
                  font: { size: 10 },
                },
              }
            : {}),
          autosize: true,
        },
      },
      allRanks,
    };
  }, [rows, config, rank, topN, normalise, sampleSort, showLegend, logY, isDark, theme, taxonUniverse, categorySource]);

  // Memoised so AdvancedVizFrame's `extras` useMemo stays stable — an unmemoised
  // element re-fires the frame's publish effect and loops it against
  // ComponentRenderer's setState ("Maximum update depth exceeded").
  // Encoding tier: rank, how many taxa survive the pooling, sample order, and
  // whether the bars are read as proportions. Most used first: a docked panel
  // shows the first few (DockedControls). Change one of those and it is a
  // different figure; the legend and the log scale only change how it looks.
  const primaryControls = useMemo(
    () => (
      <>
        <VizSelect
          label="Rank"
          value={rank}
          onChange={setRank}
          data={allRanks}
          clearable
        />
        <VizNumberInput
          label="Top-N taxa"
          value={topN}
          onChange={(v) => setTopN(Math.max(1, Number(v) || 20))}
          min={1}
          max={50}
        />
        <VizSelect
          label="Sort samples"
          value={sampleSort}
          onChange={(v) => v && setSampleSort(v as SampleSort)}
          data={[
            { value: 'input', label: 'Input order' },
            { value: 'total_abundance', label: 'Total abundance' },
            { value: 'first_taxon', label: 'Top taxon' },
          ]}
          allowDeselect={false}
        />
        <VizSwitch
          checked={normalise}
          onChange={(e) => setNormalise(e.currentTarget.checked)}
          label="Normalise"
        />
      </>
    ),
    [rank, sampleSort, topN, normalise, allRanks],
  );

  const controls = useMemo(
    () => (
      <VizControlGroup title="Display">
        <VizSwitch
          checked={showLegend}
          onChange={(e) => setShowLegend(e.currentTarget.checked)}
          label="Legend"
        />
        {!normalise ? (
          <VizSwitch
            checked={logY}
            onChange={(e) => setLogY(e.currentTarget.checked)}
            label="Log y"
          />
        ) : null}
      </VizControlGroup>
    ),
    [normalise, showLegend, logY],
  );

  // Vertical bars, so the sample count is the tile's width problem, not its
  // height: the demand is the plot area plus whatever the legend and the
  // annotation strips take off it.
  const contentDemand = useMemo(
    () =>
      figure
        ? demandForPx(
            TAXONOMY_PLOT_PX +
              (showLegend ? Math.ceil(seriesCount / LEGEND_PER_ROW) * LEGEND_ROW_PX : 0) +
              stripCount * STRIP_BAND_PX,
          )
        : undefined,
    [figure, showLegend, seriesCount, stripCount],
  );

  // Themed once per figure so the annotation layer can memoise on them.
  const plotData = useMemo(
    () => (figure ? applyDataTheme(figure.data, isDark, theme) : null),
    [figure, isDark, theme],
  );
  const plotLayout = useMemo(
    () => (figure ? applyLayoutTheme(figure.layout as any, isDark, theme) : null),
    [figure, isDark, theme],
  );
  // Chart annotations. A bar is a taxon's total in one sample, not a row,
  // so marked bars are stored as coordinates.
  const annotations = usePlotAnnotationLayer({
    componentIndex: String(metadata.index),
    enabled: supportsAdvancedVizAnnotation(metadata),
    data: plotData,
    layout: plotLayout,
  });

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Stacked taxonomy'}
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
      estimated={Boolean(reduction?.degraded)}
      reduction={
        reduction && (reduction.sampled || fullLoad)
          ? {
              displayed: reduction.displayed,
              total: reduction.total,
              sampled: reduction.sampled,
              full: fullLoad,
              loading,
              onToggle: () => setFullLoad((v) => !v),
            }
          : undefined
      }
    >
      {figure ? (
        <>
          <Plot
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

export default StackedTaxonomyRenderer;
