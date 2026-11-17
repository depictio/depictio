import React, { useEffect, useMemo, useState } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from './LegendAwarePlot';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import { usePinnedCategoryColors } from '../../hooks/useCategoryColors';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  VizControlGroup,
  VizMultiSelect,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';
import { demandForItems } from './contentDemand';

/** Room one gene's row of cells needs to read as a band rather than a line. */
const DEFAULT_ROW_PX = 22;
/** Fixed furniture: the per-sample mutation-count track along the top
 *  (xaxis2), the tilted sample labels along the bottom and the figure's own
 *  top margin. Without the count track the matrix gets that height back. */
const ONCOPLOT_CHROME_PX = 220;
const ONCOPLOT_CHROME_NO_TRACK_PX = 150;

type SampleOrder = 'auto' | 'frequency' | 'name' | 'memo';
type LegendPosition = 'bottom' | 'right';

interface OncoplotConfig {
  sample_id_col: string;
  gene_col: string;
  mutation_type_col: string;
  sort_by_freq?: boolean;
  top_genes?: number | null;
  top_samples?: number | null;
  min_gene_count?: number;
  hidden_mutation_types?: string[];
  sample_order?: SampleOrder;
  frequent_on_top?: boolean;
  show_sample_counts?: boolean;
  show_gene_counts?: boolean;
  show_sample_labels?: boolean;
  show_gene_labels?: boolean;
  cell_gap?: number;
  row_height?: number;
  show_legend?: boolean;
  legend_position?: LegendPosition;
}

const SAMPLE_ORDER_OPTIONS = [
  { value: 'auto', label: 'Follow gene order' },
  { value: 'frequency', label: 'Mutation count' },
  { value: 'name', label: 'Name' },
  { value: 'memo', label: 'Top genes first (memo)' },
];

const asCount = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) && v >= 1 ? Math.floor(v) : null;

/** Sort ascending by a numeric score descending, then by name. */
function byScoreThenName(score: Record<string, number>) {
  return (a: string, b: string) => (score[b] || 0) - (score[a] || 0) || a.localeCompare(b);
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: OncoplotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const OncoplotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as OncoplotConfig;

  const [sortByFreq, setSortByFreq] = usePersistedVizControl(metadata, 'sort_by_freq', true);
  const [sampleOrder, setSampleOrder] = usePersistedVizControl<SampleOrder>(
    metadata,
    'sample_order',
    'auto',
  );
  const [frequentOnTop, setFrequentOnTop] = usePersistedVizControl(
    metadata,
    'frequent_on_top',
    false,
  );
  const [topGenes, setTopGenes] = usePersistedVizControl<number | null>(metadata, 'top_genes', null);
  const [topSamples, setTopSamples] = usePersistedVizControl<number | null>(
    metadata,
    'top_samples',
    null,
  );
  const [minGeneCount, setMinGeneCount] = usePersistedVizControl<number>(
    metadata,
    'min_gene_count',
    1,
  );
  const [hiddenTypes, setHiddenTypes] = usePersistedVizControl<string[]>(
    metadata,
    'hidden_mutation_types',
    [],
  );
  const [showSampleCounts, setShowSampleCounts] = usePersistedVizControl(
    metadata,
    'show_sample_counts',
    true,
  );
  const [showGeneCounts, setShowGeneCounts] = usePersistedVizControl(
    metadata,
    'show_gene_counts',
    true,
  );
  const [showSampleLabels, setShowSampleLabels] = usePersistedVizControl(
    metadata,
    'show_sample_labels',
    true,
  );
  const [showGeneLabels, setShowGeneLabels] = usePersistedVizControl(
    metadata,
    'show_gene_labels',
    true,
  );
  const [cellGap, setCellGap] = usePersistedVizControl<number>(metadata, 'cell_gap', 1);
  const [rowHeight, setRowHeight] = usePersistedVizControl<number>(
    metadata,
    'row_height',
    DEFAULT_ROW_PX,
  );
  const [showLegend, setShowLegend] = usePersistedVizControl(metadata, 'show_legend', true);
  const [legendPosition, setLegendPosition] = usePersistedVizControl<LegendPosition>(
    metadata,
    'legend_position',
    'bottom',
  );

  const requiredCols = useMemo(
    () =>
      [config.sample_id_col, config.gene_col, config.mutation_type_col].filter(
        Boolean,
      ) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // The server serves this kind whole because the renderer aggregates its rows;
  // past `advanced_viz_no_sample_max_rows` it samples anyway and says so here.
  const [estimated, setEstimated] = useState(false);
  const [mutationUniverse, setMutationUniverse] = useState<string[] | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Oncoplot: missing data binding');
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
      vizKind: 'oncoplot',
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
    if (!metadata.dc_id || !config.mutation_type_col) return;
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.mutation_type_col)
      .then((v) => !cancelled && setMutationUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.mutation_type_col]);
  // A mutation type wears the dashboard's colour for it.
  const mutationPinned = usePinnedCategoryColors(config.mutation_type_col);

  const figure = useMemo(() => {
    if (!rows) return null;
    const samples = (rows[config.sample_id_col] || []) as (string | number)[];
    const genes = (rows[config.gene_col] || []) as (string | number)[];
    const muts = (rows[config.mutation_type_col] || []) as (string | number)[];

    // Rows left after the mutation-type filter, then the gene and sample cuts.
    // Counts are taken from what survives, so the bars describe what is drawn.
    const hidden = new Set(hiddenTypes);
    let keep: number[] = [];
    for (let i = 0; i < samples.length; i++) {
      if (!hidden.has(String(muts[i]))) keep.push(i);
    }
    const tally = (idx: number[], col: (string | number)[]) => {
      const out: Record<string, number> = {};
      for (const i of idx) {
        const k = String(col[i]);
        out[k] = (out[k] || 0) + 1;
      }
      return out;
    };
    const geneCut = asCount(topGenes);
    const sampleCut = asCount(topSamples);
    if (geneCut != null || minGeneCount > 1) {
      const gc = tally(keep, genes);
      let allowed = Object.keys(gc).filter((g) => gc[g] >= minGeneCount);
      if (geneCut != null) allowed = allowed.sort(byScoreThenName(gc)).slice(0, geneCut);
      const ok = new Set(allowed);
      keep = keep.filter((i) => ok.has(String(genes[i])));
    }
    if (sampleCut != null) {
      const sc = tally(keep, samples);
      const ok = new Set(Object.keys(sc).sort(byScoreThenName(sc)).slice(0, sampleCut));
      keep = keep.filter((i) => ok.has(String(samples[i])));
    }

    // Per-gene and per-sample mutation count for axis ordering + strips.
    const geneCount = tally(keep, genes);
    const sampleCount = tally(keep, samples);
    const geneList = Object.keys(geneCount);
    const sampleList = Object.keys(sampleCount);
    const mutList = Array.from(new Set(keep.map((i) => String(muts[i]))));

    const orderedGenes = sortByFreq
      ? [...geneList].sort(byScoreThenName(geneCount))
      : [...geneList].sort();
    const effectiveSampleOrder: Exclude<SampleOrder, 'auto'> =
      sampleOrder === 'auto' ? (sortByFreq ? 'frequency' : 'name') : sampleOrder;
    let orderedSamples: string[];
    if (effectiveSampleOrder === 'frequency') {
      orderedSamples = [...sampleList].sort(byScoreThenName(sampleCount));
    } else if (effectiveSampleOrder === 'memo') {
      // The classic oncoplot cascade: a sample's key is which of the genes, in
      // gene order, it carries; samples with the first gene come first.
      const carried = new Map<string, Set<string>>();
      for (const i of keep) {
        const s = String(samples[i]);
        if (!carried.has(s)) carried.set(s, new Set());
        carried.get(s)!.add(String(genes[i]));
      }
      const key = new Map<string, string>();
      for (const s of sampleList) {
        const have = carried.get(s)!;
        key.set(s, orderedGenes.map((g) => (have.has(g) ? '1' : '0')).join(''));
      }
      orderedSamples = [...sampleList].sort((a, b) =>
        key.get(b)! < key.get(a)! ? -1 : key.get(b)! > key.get(a)! ? 1 : a.localeCompare(b),
      );
    } else {
      orderedSamples = [...sampleList].sort();
    }

    // Cell colour from stable mutation-type palette. Background is NaN so
    // missing cells stay blank — plotly skips them in the heatmap.
    const colourSource = stableColorMap(
      mutationUniverse ?? mutList,
      resolveCategoricalPalette(theme, TAB10_PALETTE),
      mutationPinned,
    );
    const mutToIdx = new Map<string, number>();
    mutList.forEach((m, i) => mutToIdx.set(m, i));

    // Build a discrete colourscale from the stable palette.
    const colorscale: [number, string][] = [];
    const n = mutList.length || 1;
    for (let i = 0; i < n; i++) {
      const lo = i / n;
      const hi = (i + 1) / n;
      const colour = colourSource.get(mutList[i]) ?? '#888';
      colorscale.push([lo, colour]);
      colorscale.push([hi, colour]);
    }

    // Matrix: rows = genes, cols = samples. Cell = mutation-type index.
    const matrix: (number | null)[][] = orderedGenes.map(() =>
      orderedSamples.map(() => null),
    );
    const textMatrix: string[][] = orderedGenes.map(() => orderedSamples.map(() => ''));
    const geneIdx = new Map<string, number>(orderedGenes.map((g, i) => [g, i]));
    const sampleIdx = new Map<string, number>(orderedSamples.map((s, i) => [s, i]));
    for (const i of keep) {
      const g = String(genes[i]);
      const s = String(samples[i]);
      const m = String(muts[i]);
      const gi = geneIdx.get(g);
      const si = sampleIdx.get(s);
      const mi = mutToIdx.get(m);
      if (gi == null || si == null || mi == null) continue;
      matrix[gi][si] = mi + 0.5;
      textMatrix[gi][si] = m;
    }

    const barColour = isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)';
    const axisBase = plotlyAxisOverrides(isDark, theme);
    const axisTitle = (text: string, extra: Record<string, unknown> = {}) => ({
      ...axisBase.title,
      text,
      ...extra,
    });
    // The matrix gives up the strip room of a hidden count track, so the cells
    // grow rather than leaving a gap.
    const matrixX: [number, number] = [0, showGeneCounts ? 0.85 : 1];
    const matrixY: [number, number] = [0, showSampleCounts ? 0.85 : 1];
    const legendRight = legendPosition === 'right';

    return {
      // Matrix rows on screen, one per gene. Feeds the content demand.
      genesDrawn: orderedGenes.length,
      data: [
        // Main heatmap on a 4-row x 4-col layout. Bottom-left (xaxis=x,
        // yaxis=y) is the matrix; xaxis2 (top) is per-sample mutation
        // count; yaxis2 (right) is per-gene mutation count.
        {
          type: 'heatmap' as const,
          x: orderedSamples,
          y: orderedGenes,
          z: matrix,
          text: textMatrix,
          xgap: cellGap,
          ygap: cellGap,
          colorscale,
          zmin: 0,
          zmax: n,
          showscale: false,
          hovertemplate: `<b>%{y}</b> in <b>%{x}</b><br>%{text}<extra></extra>`,
        },
        ...(showSampleCounts
          ? [
              {
                type: 'bar' as const,
                orientation: 'v' as const,
                x: orderedSamples,
                y: orderedSamples.map((s) => sampleCount[s] || 0),
                xaxis: 'x',
                yaxis: 'y2',
                marker: { color: barColour },
                hovertemplate: `<b>%{x}</b>: %{y} mutations<extra></extra>`,
                showlegend: false,
              },
            ]
          : []),
        ...(showGeneCounts
          ? [
              {
                type: 'bar' as const,
                orientation: 'h' as const,
                y: orderedGenes,
                x: orderedGenes.map((g) => geneCount[g] || 0),
                xaxis: 'x2',
                yaxis: 'y',
                marker: { color: barColour },
                hovertemplate: `<b>%{y}</b>: %{x} mutations<extra></extra>`,
                showlegend: false,
              },
            ]
          : []),
        // Discrete legend rendered via dummy scatter traces, one per
        // mutation type. Their markers carry the palette colour, so plotly
        // builds a real legend the user can use as a colour key.
        ...mutList.map((m) => ({
          type: 'scatter' as const,
          mode: 'markers' as const,
          x: [null],
          y: [null],
          name: m,
          marker: { color: colourSource.get(m), size: 10 },
          showlegend: true,
          hoverinfo: 'skip' as const,
        })),
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        // The axes size their own margins (automargin) around the tick labels
        // and the title; the legend is placed against the figure's edge
        // (yref/xref "container"), where plotly reserves the room it needs on
        // top of that. Together they cannot overlap, however many rows a
        // wrapping legend takes. These base margins are only the breathing
        // room around them.
        margin: { l: 24, r: legendRight ? 12 : 24, t: 30, b: 10 },
        xaxis: {
          ...axisBase,
          domain: matrixX,
          tickangle: -45,
          title: axisTitle(config.sample_id_col, { standoff: 12 }),
          showgrid: false,
          showticklabels: showSampleLabels,
          automargin: true,
        },
        yaxis: {
          ...axisBase,
          domain: matrixY,
          title: axisTitle(config.gene_col, { standoff: 8 }),
          showgrid: false,
          showticklabels: showGeneLabels,
          automargin: true,
          ...(frequentOnTop ? { autorange: 'reversed' as const } : {}),
        },
        xaxis2: {
          ...axisBase,
          domain: [0.86, 1],
          showgrid: false,
          zeroline: false,
          anchor: 'y' as const,
        },
        yaxis2: {
          ...axisBase,
          domain: [0.86, 1],
          showgrid: false,
          zeroline: false,
          anchor: 'x' as const,
        },
        showlegend: showLegend,
        legend: legendRight
          ? {
              orientation: 'v' as const,
              xref: 'container' as const,
              x: 1,
              xanchor: 'right' as const,
              yref: 'paper' as const,
              y: matrixY[1],
              yanchor: 'top' as const,
              font: { color: plotlyThemeColors(isDark, theme).textColor },
              bgcolor: 'rgba(0,0,0,0)',
            }
          : {
              orientation: 'h' as const,
              xref: 'paper' as const,
              x: 0.5,
              xanchor: 'center' as const,
              yref: 'container' as const,
              y: 0,
              yanchor: 'bottom' as const,
              font: { color: plotlyThemeColors(isDark, theme).textColor },
              bgcolor: 'rgba(0,0,0,0)',
            },
        autosize: true,
      },
    };
  }, [
    rows,
    config,
    sortByFreq,
    sampleOrder,
    frequentOnTop,
    topGenes,
    topSamples,
    minGeneCount,
    hiddenTypes,
    showSampleCounts,
    showGeneCounts,
    showSampleLabels,
    showGeneLabels,
    cellGap,
    showLegend,
    legendPosition,
    colorScheme,
    theme,
    mutationUniverse,
    mutationPinned,
  ]);


  // Every mutation type the data holds, so a hidden one can be offered back.
  const mutationTypes = useMemo(() => {
    const seen = new Set<string>(mutationUniverse ?? []);
    for (const m of (rows?.[config.mutation_type_col] || []) as (string | number)[]) {
      seen.add(String(m));
    }
    return Array.from(seen).sort();
  }, [rows, config.mutation_type_col, mutationUniverse]);

  // Encoding tier: what is counted and in which order. The frame draws it in
  // the header, the rail or ahead of the popover, per placement.
  const primaryControls = (
    <>
      <VizControlGroup title="Data">
        <VizNumberInput
          label="Top genes"
          placeholder="All"
          min={1}
          allowDecimal={false}
          value={topGenes ?? ''}
          onChange={(v) => setTopGenes(asCount(v))}
        />
        <VizNumberInput
          label="Top samples"
          placeholder="All"
          min={1}
          allowDecimal={false}
          value={topSamples ?? ''}
          onChange={(v) => setTopSamples(asCount(v))}
        />
        <VizNumberInput
          label="Min mutations per gene"
          min={1}
          allowDecimal={false}
          value={minGeneCount}
          onChange={(v) => setMinGeneCount(asCount(v) ?? 1)}
        />
        {mutationTypes.length > 1 ? (
          <VizMultiSelect
            label="Hide mutation types"
            data={mutationTypes}
            value={hiddenTypes}
            onChange={setHiddenTypes}
            placeholder="None"
            clearable
            searchable={mutationTypes.length > 8}
          />
        ) : null}
      </VizControlGroup>
      <VizControlGroup title="Order">
        <VizSwitch
          checked={sortByFreq}
          onChange={(e) => setSortByFreq(e.currentTarget.checked)}
          label="Sort genes by mutation frequency"
        />
        <VizSwitch
          checked={frequentOnTop}
          onChange={(e) => setFrequentOnTop(e.currentTarget.checked)}
          label="First gene at the top"
        />
        <VizSelect
          label="Sample order"
          data={SAMPLE_ORDER_OPTIONS}
          value={sampleOrder}
          onChange={(v) => setSampleOrder((v as SampleOrder) ?? 'auto')}
          allowDeselect={false}
        />
      </VizControlGroup>
    </>
  );

  // Cosmetic tier: how the matrix and its legend are drawn.
  const controls = (
    <>
      <VizControlGroup title="Display">
        <VizSlider
          label="Gene row height"
          min={12}
          max={44}
          step={2}
          value={rowHeight}
          onChange={setRowHeight}
          thumbLabel={(v) => `${v}px`}
        />
        <VizSlider
          label="Cell gap"
          min={0}
          max={4}
          step={1}
          value={cellGap}
          onChange={setCellGap}
          thumbLabel={(v) => `${v}px`}
        />
        <VizSwitch
          checked={showSampleCounts}
          onChange={(e) => setShowSampleCounts(e.currentTarget.checked)}
          label="Sample count bars"
        />
        <VizSwitch
          checked={showGeneCounts}
          onChange={(e) => setShowGeneCounts(e.currentTarget.checked)}
          label="Gene count bars"
        />
        <VizSwitch
          checked={showSampleLabels}
          onChange={(e) => setShowSampleLabels(e.currentTarget.checked)}
          label="Sample labels"
        />
        <VizSwitch
          checked={showGeneLabels}
          onChange={(e) => setShowGeneLabels(e.currentTarget.checked)}
          label="Gene labels"
        />
      </VizControlGroup>
      <VizControlGroup title="Legend">
        <VizSwitch
          checked={showLegend}
          onChange={(e) => setShowLegend(e.currentTarget.checked)}
          label="Show legend"
        />
        {showLegend ? (
          <VizSegmented
            label="Position"
            value={legendPosition}
            onChange={(v) => setLegendPosition(v as LegendPosition)}
            data={[
              { value: 'bottom', label: 'Bottom' },
              { value: 'right', label: 'Right' },
            ]}
          />
        ) : null}
      </VizControlGroup>
    </>
  );

  // One matrix row per gene, under the per-sample count track. Keyed on the
  // count, so re-sorting the same genes republishes nothing.
  const genesDrawn = figure?.genesDrawn ?? 0;
  const contentDemand = useMemo(
    () =>
      demandForItems(
        genesDrawn,
        rowHeight,
        showSampleCounts ? ONCOPLOT_CHROME_PX : ONCOPLOT_CHROME_NO_TRACK_PX,
      ),
    [genesDrawn, rowHeight, showSampleCounts],
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Oncoplot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <Plot
          data={applyDataTheme(figure.data, isDark, theme) as any}
          layout={applyLayoutTheme(figure.layout as any, isDark, theme) as any}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default OncoplotRenderer;
