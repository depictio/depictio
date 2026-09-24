import React, { useEffect, useMemo, useState } from 'react';
import { Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { plotlyColorscale } from '../../utils/colorScale';
import AdvancedVizFrame from './AdvancedVizFrame';
import AdvancedVizPlot from './AdvancedVizPlot';
import {
  VizControlGroup,
  VizFullRow,
  VizSegmented,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import {
  blockBars,
  buildLanes,
  chevronPoints,
  intronSpans,
  laneLabels,
  listGenes,
  toBlocks,
  type TranscriptBlock,
} from './transcript_structure/layout';
import { regionXRange, useFollowedRegion } from './genomicAxis';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `TranscriptStructureConfig` in
 *  `depictio/models/components/advanced_viz/configs.py`. Every key this file
 *  reads off `config` has to exist there; `test_advanced_viz_config_alignment`
 *  reads this source and fails the build otherwise. */
interface TranscriptStructureConfig {
  transcript_id_col: string;
  gene_id_col: string;
  chrom_col: string;
  start_col: string;
  end_col: string;
  feature_col: string;
  strand_col: string;
  sample_col?: string | null;
  gene_name_col?: string | null;
  transcript_class_col?: string | null;
  expression_col?: string | null;
  gene?: string | null;
  max_transcripts?: number;
  exon_feature?: string;
  cds_feature?: string;
  colour_by?: ColourMode;
  colour_scale?: ColourScale;
}

type ColourMode = 'transcript_class' | 'expression' | 'none';

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: TranscriptStructureConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/** Sent with every fetch: the kind is what selects the server's `"none"`
 *  sampling policy, and a uniformly sampled annotation is a transcript with
 *  holes in its exon chain, which reads as a different isoform. */
const VIZ_KIND: AdvancedVizKind = 'transcript_structure';

const DEFAULT_MAX_TRANSCRIPTS = 30;

/** Lane-unit height of a block. A coding block is drawn taller than the
 *  untranslated parts of the same exon chain: that difference is the only cue
 *  saying where the ORF is, and every isoform browser draws it. */
const EXON_HEIGHT = 0.4;
const CDS_HEIGHT = 0.64;

/** Fraction of the plot width the right-hand expression panel takes. */
const EXPRESSION_PANEL = 0.18;

/** Chevrons are spaced at this fraction of the drawn span, so their density
 *  stays the same whether the gene is 2 kb or 2 Mb wide. */
const CHEVRON_STEP_FRACTION = 0.035;

const PLOT_STYLE = { width: '100%', height: '100%' };
const PLOT_CONFIG = { displaylogo: false, responsive: true };

const MAX_TRANSCRIPT_MARKS = [
  { value: 5, label: '5' },
  { value: 15, label: '15' },
  { value: 30, label: '30' },
  { value: 60, label: '60' },
];

/** Class labels that carry no novelty claim. They keep a neutral grey so the
 *  palette hues are left for the isoforms a run actually discovered. */
const NEUTRAL_CLASSES = new Set(['known', 'reference', 'annotated', '', 'other', 'na', 'n/a']);

const ALL_SAMPLES = '__all__';

/**
 * Isoform structures of one gene: one lane per transcript, exon and CDS blocks
 * on a base-pair axis, introns as thin lines carrying strand chevrons.
 *
 * Blocks are **horizontal bar traces**, not layout shapes and not filled
 * scatter rings. A bar takes its thickness from `width` per point, which is
 * exactly the exon-versus-CDS distinction the drawing needs, and unlike a shape
 * it keeps a hover label and a legend entry. It also lets the expression
 * colouring ride on Plotly's own `marker.colorscale`, so the colour bar is
 * exact rather than a locally sampled approximation of the ramp.
 *
 * One gene at a time is the whole design. A track showing every locus at once
 * is a genome browser, which is `genome_view`'s job; what this kind answers is
 * "what do the isoforms of *this* gene look like, and which of them did the run
 * call novel".
 *
 * `transcript_structure` declares no selection, so this renderer emits none.
 */
const TranscriptStructureRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const config = (metadata.config || {}) as TranscriptStructureConfig;
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const [gene, setGene] = usePersistedVizControl<string | null>(metadata, 'gene', null);
  const [maxTranscripts, setMaxTranscripts] = usePersistedVizControl<number>(metadata, 'max_transcripts', DEFAULT_MAX_TRANSCRIPTS);
  const [colourBy, setColourBy] = usePersistedVizControl<ColourMode>(metadata, 'colour_by', 'transcript_class');
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(metadata, 'colour_scale', 'Viridis');

  // View-only controls: the model has no field for either, and a config key
  // with no field is not merely unvalidated, `extra="forbid"` makes the whole
  // component unloadable. They stay local.
  const [sample, setSample] = useState<string>(ALL_SAMPLES);
  const [showExpressionPanel, setShowExpressionPanel] = useState<boolean>(true);

  const exonLabel = config.exon_feature ?? 'exon';
  const cdsLabel = config.cds_feature ?? 'CDS';

  const requiredCols = useMemo(() => {
    const cols = [
      config.transcript_id_col,
      config.gene_id_col,
      config.chrom_col,
      config.start_col,
      config.end_col,
      config.feature_col,
      config.strand_col,
      config.sample_col,
      config.gene_name_col,
      config.transcript_class_col,
      config.expression_col,
    ];
    return Array.from(new Set(cols.filter((c): c is string => Boolean(c))));
  }, [
    config.transcript_id_col,
    config.gene_id_col,
    config.chrom_col,
    config.start_col,
    config.end_col,
    config.feature_col,
    config.strand_col,
    config.sample_col,
    config.gene_name_col,
    config.transcript_class_col,
    config.expression_col,
  ]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState<boolean>(false);

  const bound = Boolean(
    metadata.wf_id &&
      metadata.dc_id &&
      config.transcript_id_col &&
      config.gene_id_col &&
      config.chrom_col &&
      config.start_col &&
      config.end_col &&
      config.feature_col &&
      config.strand_col,
  );

  useEffect(() => {
    if (!bound) {
      setError('Transcript structure: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id as string,
      dcId: metadata.dc_id as string,
      columns: requiredCols,
      filters,
      vizKind: VIZ_KIND,
      roles: {
        transcript_id: config.transcript_id_col,
        gene_id: config.gene_id_col,
        chrom: config.chrom_col,
        start: config.start_col,
        end: config.end_col,
        feature: config.feature_col,
        strand: config.strand_col,
      },
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
  }, [
    bound,
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filters),
    refreshTick,
  ]);

  /** Long rows to blocks, dropping everything that is neither exon nor CDS. */
  const blocks = useMemo<TranscriptBlock[]>(
    () =>
      toBlocks(
        rows,
        {
          transcriptId: config.transcript_id_col,
          geneId: config.gene_id_col,
          chrom: config.chrom_col,
          start: config.start_col,
          end: config.end_col,
          feature: config.feature_col,
          strand: config.strand_col,
          sample: config.sample_col,
          geneName: config.gene_name_col,
          transcriptClass: config.transcript_class_col,
          expression: config.expression_col,
        },
        { exon: exonLabel, cds: cdsLabel },
      ),
    [
      rows,
      config.transcript_id_col,
      config.gene_id_col,
      config.chrom_col,
      config.start_col,
      config.end_col,
      config.feature_col,
      config.strand_col,
      config.sample_col,
      config.gene_name_col,
      config.transcript_class_col,
      config.expression_col,
      exonLabel,
      cdsLabel,
    ],
  );

  const geneOptions = useMemo(() => listGenes(blocks), [blocks]);

  // ---- Following a region someone else brushed ----------------------------
  // One gene at a time is this kind's whole design, so "follow the region"
  // means: draw the gene the region is over, and clamp the axis to the window
  // rather than to the gene's full span. A region on a contig this tile does
  // not hold, or between two genes, changes nothing.
  const followedRegion = useFollowedRegion(metadata, config, filters);
  const regionGene = useMemo(() => {
    if (!followedRegion) return null;
    const overlapping = new Set<string>();
    for (const b of blocks) {
      if (b.chrom !== followedRegion.chrom) continue;
      if (b.end < followedRegion.start || b.start > followedRegion.end) continue;
      overlapping.add(b.geneId);
    }
    if (!overlapping.size) return null;
    // `geneOptions` is already ordered by isoform count, so this is the
    // busiest gene in the window.
    return geneOptions.find((g) => overlapping.has(g.id))?.id ?? null;
  }, [followedRegion, blocks, geneOptions]);

  // The gene the region is over, else the author's or the reader's pick, else
  // the gene with the most isoforms. The region wins over the saved pick for
  // the same reason it does in `cnv_profile`: navigating the section just now
  // is a more recent intent than the tile's saved default.
  const pickedGene = gene && geneOptions.some((g) => g.id === gene) ? gene : null;
  const effectiveGene = regionGene ?? pickedGene ?? (geneOptions[0]?.id ?? null);

  const { lanes, truncated, samples } = useMemo(() => {
    if (!effectiveGene) return { lanes: [], truncated: 0, samples: [] as string[] };
    return buildLanes(blocks, {
      geneId: effectiveGene,
      sample: sample === ALL_SAMPLES ? null : sample,
      maxTranscripts,
    });
  }, [blocks, effectiveGene, sample, maxTranscripts]);

  const hasExpression = Boolean(config.expression_col) && lanes.some((l) => l.expression !== null);
  const hasClasses = Boolean(config.transcript_class_col);
  // A colouring the bound columns cannot support falls back rather than drawing
  // every lane at the same end of the ramp.
  const colourMode: ColourMode =
    (colourBy === 'expression' && !hasExpression) || (colourBy === 'transcript_class' && !hasClasses)
      ? 'none'
      : colourBy;
  const expressionPanel = hasExpression && showExpressionPanel && colourMode !== 'expression';

  /** Mantine hues for the class colouring, the list the other track kinds use. */
  const palette = useMemo<string[]>(
    () => [
      theme.colors.orange[5],
      theme.colors.grape[5],
      theme.colors.teal[5],
      theme.colors.red[5],
      theme.colors.violet[5],
      theme.colors.cyan[5],
      theme.colors.lime[6],
      theme.colors.indigo[5],
    ],
    [theme.colors],
  );
  const neutralColour = isDark ? theme.colors.gray[6] : theme.colors.gray[5];
  const baseColour = theme.colors.blue[isDark ? 4 : 6];
  // The intron backbone reads as an axis rule, so it takes the shared theme's
  // zero-line colour rather than a second literal to keep in step with it.
  const lineColour = plotlyThemeColors(isDark, theme).zeroLineColor;
  // Stronger than the intron line: a chevron may land on a coloured block (a
  // single-exon transcript has no intron), and a 35% mark would vanish there.
  const chevronColour = isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.55)';

  const figure = useMemo<{ data: unknown[]; layout: Record<string, unknown> } | null>(() => {
    if (!lanes.length) return null;

    const xMin = Math.min(...lanes.map((l) => l.start));
    const xMax = Math.max(...lanes.map((l) => l.end));
    const span = Math.max(xMax - xMin, 1);
    const pad = span * 0.02;
    const chrom = lanes[0]?.blocks[0]?.chrom ?? '';
    const perSample = sample === ALL_SAMPLES && samples.length > 1;

    // ---- introns and their chevrons ---------------------------------------
    const intronX: Array<number | null> = [];
    const intronY: Array<number | null> = [];
    const chevronX: number[] = [];
    const chevronY: number[] = [];
    const chevronSymbol: string[] = [];
    lanes.forEach((lane, i) => {
      // The backbone runs the whole transcript, so a single-exon transcript
      // still reads as a transcript rather than as a lone block.
      intronX.push(lane.start, lane.end, null);
      intronY.push(i, i, null);
      const spans = intronSpans(lane);
      const marks = chevronPoints(
        spans.length ? spans : [[lane.start, lane.end]],
        span * CHEVRON_STEP_FRACTION,
      );
      marks.forEach((x) => {
        chevronX.push(x);
        chevronY.push(i);
        chevronSymbol.push(lane.strand === '-' ? 'triangle-left' : 'triangle-right');
      });
    });

    const traces: unknown[] = [
      {
        type: 'scatter',
        mode: 'lines',
        x: intronX,
        y: intronY,
        line: { color: lineColour, width: 1 },
        hoverinfo: 'skip',
        showlegend: false,
      },
    ];

    // ---- blocks -------------------------------------------------------------
    // Grouped by class so the legend is per class and the trace count stays at
    // O(classes) rather than O(blocks).
    const byGroup = blockBars(lanes, {
      exonHeight: EXON_HEIGHT,
      cdsHeight: CDS_HEIGHT,
      exonLabel,
      cdsLabel,
      byClass: colourMode === 'transcript_class',
    });

    const hoverTemplate =
      '<b>%{customdata[0]}</b>' +
      (perSample ? '<br>sample: %{customdata[1]}' : '') +
      '<br>%{customdata[2]} on %{customdata[3]}' +
      '<br>%{customdata[6]} %{customdata[4]:,} to %{customdata[5]:,} bp (%{customdata[7]})' +
      (hasClasses ? '<br>class: %{customdata[8]}' : '') +
      (hasExpression ? '<br>expression: %{customdata[9]:.4g}' : '') +
      '<extra></extra>';

    const groupNames = Array.from(byGroup.keys()).sort((a, b) => a.localeCompare(b));
    const groupColour = new Map<string, string>();
    let hue = 0;
    groupNames.forEach((name) => {
      if (NEUTRAL_CLASSES.has(name.toLowerCase())) groupColour.set(name, neutralColour);
      else groupColour.set(name, palette[hue++ % palette.length]);
    });

    const expressions = lanes
      .map((l) => l.expression)
      .filter((v): v is number => v !== null && Number.isFinite(v));
    const cmin = expressions.length ? Math.min(...expressions) : 0;
    const cmax = expressions.length ? Math.max(...expressions) : 1;

    const showClassLegend = colourMode === 'transcript_class' && groupNames.length > 1;
    groupNames.forEach((name) => {
      const points = byGroup.get(name) ?? [];
      traces.push({
        type: 'bar',
        orientation: 'h',
        base: points.map((p) => p.base),
        x: points.map((p) => p.width),
        y: points.map((p) => p.y),
        width: points.map((p) => p.height),
        customdata: points.map((p) => p.hover),
        marker:
          colourMode === 'expression'
            ? {
                color: points.map((p) => p.expression ?? cmin),
                colorscale: plotlyColorscale(colourScale),
                cmin,
                cmax,
                colorbar: { thickness: 10, len: 0.7, title: { text: 'Expression' } },
                line: { width: 0 },
              }
            : {
                color: colourMode === 'transcript_class' ? groupColour.get(name) : baseColour,
                line: { width: 0 },
              },
        name: name || 'Blocks',
        legendgroup: name || 'Blocks',
        showlegend: showClassLegend,
        hovertemplate: hoverTemplate,
      });
    });

    // ---- strand chevrons, last so they sit on top --------------------------
    // A single-exon transcript has no intron to put them in, so the marks fall
    // on the block itself, which is where IGV draws them too. Emitting the
    // trace after the bars is what keeps them visible there.
    traces.push({
      type: 'scatter',
      mode: 'markers',
      x: chevronX,
      y: chevronY,
      marker: { symbol: chevronSymbol, size: 6, color: chevronColour },
      hoverinfo: 'skip',
      showlegend: false,
    });

    // ---- right-hand expression panel ---------------------------------------
    if (expressionPanel) {
      traces.push({
        type: 'bar',
        orientation: 'h',
        x: lanes.map((l) => l.expression ?? 0),
        y: lanes.map((_, i) => i),
        width: lanes.map(() => CDS_HEIGHT),
        xaxis: 'x2',
        marker: { color: baseColour, line: { width: 0 } },
        hovertemplate: 'expression: %{x:.4g}<extra></extra>',
        showlegend: false,
      });
    }

    const trackRight = expressionPanel ? 1 - EXPRESSION_PANEL : 1;
    const labels = laneLabels(lanes, { perSample, neutralClasses: NEUTRAL_CLASSES });

    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      margin: { l: 8, r: 12, t: 8, b: 44 },
      autosize: true,
      barmode: 'overlay',
      bargap: 0,
      hovermode: 'closest',
      showlegend: showClassLegend,
      legend: { orientation: 'h', x: 0, y: 1.08, font: { size: 10 } },
      xaxis: {
        ...plotlyAxisOverrides(isDark, theme),
        domain: [0, trackRight],
        title: { text: chrom ? `Position on ${chrom} (bp)` : 'Position (bp)', font: { size: 11 } },
        // A followed region that overlaps the drawn gene is the window the
        // section is on; otherwise the gene's own span, padded.
        range: (() => {
          const window =
            followedRegion && followedRegion.chrom === chrom ? regionXRange(followedRegion) : null;
          if (!window) return [xMin - pad, xMax + pad];
          return window[1] < xMin || window[0] > xMax ? [xMin - pad, xMax + pad] : window;
        })(),
        zeroline: false,
        automargin: true,
      },
      yaxis: {
        ...plotlyAxisOverrides(isDark, theme),
        tickmode: 'array',
        tickvals: lanes.map((_, i) => i),
        ticktext: labels,
        tickfont: { size: 9 },
        // Reversed, so the first lane is the top one and the stack grows
        // downwards the way a list of tracks is read.
        range: [lanes.length - 0.5, -0.6],
        showgrid: false,
        zeroline: false,
        automargin: true,
      },
      ...(expressionPanel
        ? {
            xaxis2: {
              ...plotlyAxisOverrides(isDark, theme),
              domain: [trackRight + 0.03, 1],
              anchor: 'y',
              title: { text: 'Expression', font: { size: 10 } },
              tickfont: { size: 9 },
              zeroline: false,
              showgrid: false,
              automargin: true,
            },
          }
        : {}),
    };

    return { data: traces, layout };
  }, [
    lanes,
    samples,
    sample,
    colourMode,
    colourScale,
    hasClasses,
    hasExpression,
    expressionPanel,
    palette,
    neutralColour,
    baseColour,
    lineColour,
    chevronColour,
    isDark,
    theme,
    exonLabel,
    cdsLabel,
    followedRegion,
  ]);

  // Encoding tier: which gene, which sample's expression and what colours the
  // isoform lanes. The colour scale, the expression bars and the isoform
  // budget are how that same selection is painted.
  const primaryControls = useMemo(
    () => (
      <>
        <VizControlGroup title="Data">
          <VizSelect
            label={regionGene ? 'Gene (following the region)' : 'Gene'}
            value={effectiveGene}
            onChange={(v) => setGene(v)}
            data={geneOptions.map((g) => ({
              value: g.id,
              label: `${g.name && g.name !== g.id ? `${g.name} (${g.id})` : g.id} · ${g.transcripts} isoform${g.transcripts === 1 ? '' : 's'}`,
            }))}
            placeholder={rows ? 'No gene in this frame' : 'Loading…'}
            searchable
            allowDeselect={false}
          />
          {samples.length > 1 ? (
            <VizSelect
              label="Sample"
              value={sample}
              onChange={(v) => setSample(v ?? ALL_SAMPLES)}
              data={[
                { value: ALL_SAMPLES, label: 'All samples' },
                ...samples.map((s) => ({ value: s, label: s })),
              ]}
              allowDeselect={false}
            />
          ) : null}
          <VizSegmented
            label="Colour lanes by"
            value={colourMode}
            onChange={(v) => setColourBy(v as ColourMode)}
            data={[
              { value: 'transcript_class', label: 'Class', disabled: !hasClasses },
              { value: 'expression', label: 'Expression', disabled: !hasExpression },
              { value: 'none', label: 'Off' },
            ]}
          />
        </VizControlGroup>
      </>
    ),
    [
      effectiveGene,
      regionGene,
      geneOptions,
      rows,
      samples,
      sample,
      colourMode,
      hasClasses,
      hasExpression,
      setGene,
      setColourBy,
    ],
  );

  const controls = useMemo(
    () => (
      <>
        {colourMode === 'expression' || hasExpression ? (
          <VizControlGroup title="Expression">
            {colourMode === 'expression' ? (
              <VizSelect
                label="Colour scale"
                value={colourScale}
                onChange={(v) => setColourScale((v as ColourScale) || 'Viridis')}
                data={COLOUR_SCALES as unknown as string[]}
                allowDeselect={false}
              />
            ) : null}
            {hasExpression && colourMode !== 'expression' ? (
              <VizSwitch
                checked={showExpressionPanel}
                onChange={(e) => setShowExpressionPanel(e.currentTarget.checked)}
                label="Bar beside each lane"
              />
            ) : null}
          </VizControlGroup>
        ) : null}
        <VizControlGroup title="Isoforms">
          <VizSlider
            label="Isoforms drawn"
            min={5}
            max={60}
            step={5}
            value={maxTranscripts}
            onChange={setMaxTranscripts}
            marks={MAX_TRANSCRIPT_MARKS}
            thumbLabel={(v) => String(v)}
          />
          {truncated > 0 ? (
            <VizFullRow>
              <Text size="xs" c="dimmed">
                {truncated} lower-expressed isoform{truncated === 1 ? '' : 's'} not shown. Raise the
                budget above to see them.
              </Text>
            </VizFullRow>
          ) : null}
        </VizControlGroup>
      </>
    ),
    [
      colourMode,
      colourScale,
      hasExpression,
      showExpressionPanel,
      maxTranscripts,
      truncated,
      setColourScale,
      setMaxTranscripts,
    ],
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Transcript structure'}
      subtitle={(metadata as { description?: string; subtitle?: string }).description}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={
        rows && (blocks.length === 0 || lanes.length === 0)
          ? 'No exon or CDS blocks to draw'
          : undefined
      }
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <AdvancedVizPlot
          data={applyDataTheme(figure.data, isDark, theme) as any}
          layout={
            applyLayoutTheme(
              { ...(figure.layout as any), width: undefined, height: undefined, autosize: true },
              isDark,
              theme,
            ) as any
          }
          useResizeHandler
          style={PLOT_STYLE}
          config={PLOT_CONFIG as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default TranscriptStructureRenderer;
