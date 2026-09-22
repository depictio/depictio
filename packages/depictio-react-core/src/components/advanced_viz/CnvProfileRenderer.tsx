import React, { useEffect, useMemo, useState } from 'react';
import {
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { adaptGlTrace, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  buildGenomeAxis,
  classifyLog2,
  CnvClass,
  copyNumberBucket,
  decimateBins,
  genomeX,
  hoverText,
  parseCnvRows,
  segmentStrokes,
  sortChromosomes,
} from './cnv_profile/cnvLayout';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `CnvProfileConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface CnvProfileConfig {
  sample_col: string;
  chrom_col: string;
  start_col: string;
  end_col: string;
  log2_col: string;
  baf_col?: string | null;
  copy_number_col?: string | null;
  segment_col?: string | null;
  label_col?: string | null;
  sample?: string | null;
  chrom?: string | null;
  y_range?: number;
  show_baf?: boolean;
  point_size?: number;
  gain_threshold?: number;
  loss_threshold?: number;
  max_bins?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: CnvProfileConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// The server does not reduce this kind (`KIND_SAMPLING_POLICY["cnv_profile"]
// is "none"`): dropping rows at random would erase a focal amplification, and
// dropping segments would erase the call itself. The bin track is decimated
// here instead, by averaging consecutive windows, and every segment is drawn.
const CNV_PROFILE_VIZ_KIND: AdvancedVizKind = 'cnv_profile';

const ALL_CHROMOSOMES = '__all__';
const DEFAULT_MAX_BINS = 50000;
const DEFAULT_Y_RANGE = 3;
const DEFAULT_POINT_SIZE = 3;
const DEFAULT_GAIN_THRESHOLD = 0.3;
const DEFAULT_LOSS_THRESHOLD = -0.3;
/** Thickness of a called segment, in pixels. Deliberately far above the bin
 *  marker size: the segment is the call, the bins are the evidence for it. */
const SEGMENT_WIDTH = 5;
/** Vertical split when the BAF panel is drawn. */
const LOG2_DOMAIN_WITH_BAF: [number, number] = [0.36, 1];
const BAF_DOMAIN: [number, number] = [0, 0.28];

const PLOT_STYLE = { width: '100%', height: '100%' };
const PLOT_CONFIG = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
  scrollZoom: false,
};

type Theme = ReturnType<typeof useMantineTheme>;

/** Alternating bin tints, the two-tone grey a CNVkit scatter uses so the
 *  coloured segments read on top of them. Both tints stay legible against the
 *  plot background in either colour scheme. */
function binTints(isDark: boolean, theme: Theme): [string, string] {
  return isDark
    ? [theme.colors.gray[5], theme.colors.gray[7]]
    : [theme.colors.gray[7], theme.colors.gray[5]];
}

/** Gain / neutral / loss, from the Mantine palette rather than literals. */
function classColours(isDark: boolean, theme: Theme): Record<CnvClass, string> {
  return {
    gain: theme.colors.red[isDark ? 5 : 7],
    neutral: theme.colors.gray[isDark ? 5 : 6],
    loss: theme.colors.blue[isDark ? 4 : 7],
  };
}

/** Five-level copy-number ramp: homozygous loss, loss, neutral, gain, high
 *  amplification. Indexed by `copyNumberBucket`. */
function copyNumberRamp(isDark: boolean, theme: Theme): string[] {
  return [
    theme.colors.indigo[isDark ? 6 : 9],
    theme.colors.blue[isDark ? 4 : 7],
    theme.colors.gray[isDark ? 5 : 6],
    theme.colors.orange[isDark ? 4 : 7],
    theme.colors.red[isDark ? 5 : 8],
  ];
}

const CNV_CLASS_ORDER: CnvClass[] = ['loss', 'neutral', 'gain'];
const CNV_CLASS_LABEL: Record<CnvClass, string> = {
  gain: 'Gain',
  neutral: 'Neutral',
  loss: 'Loss',
};

const CnvProfilePlot = React.memo<{
  figure: { data?: unknown[]; layout?: Record<string, unknown> };
  isDark: boolean;
  theme: Theme;
}>(({ figure, isDark, theme }) => {
  const themedData = useMemo(
    () => applyDataTheme(figure.data, isDark, theme),
    [figure.data, isDark, theme],
  );
  const themedLayout = useMemo(
    () => applyLayoutTheme(figure.layout as any, isDark, theme),
    [figure.layout, isDark, theme],
  );
  return (
    <Plot
      data={themedData as any}
      layout={themedLayout as any}
      useResizeHandler
      style={PLOT_STYLE}
      config={PLOT_CONFIG as any}
    />
  );
});
CnvProfilePlot.displayName = 'CnvProfilePlot';

/**
 * Copy-number profile: the log2 ratio of every bin along the genome, the
 * called segments laid over it as thick horizontal strokes coloured gain /
 * neutral / loss, and the B-allele frequency underneath when the collection
 * carries one.
 *
 * The x axis is the genome, chromosomes laid end to end exactly as
 * `ManhattanRenderer` lays them, so the chromosome selector zooms onto one
 * contig rather than stranding it in an empty genome. Bins are drawn as a
 * `scattergl` trace and fall back to a downsampled SVG trace when the WebGL
 * budget is exhausted (`webglBudget.ts`), which is what keeps a whole-exome
 * profile of 200k bins on a dashboard next to other GL plots.
 */
const CnvProfileRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as CnvProfileConfig;
  const glGranted = useWebglSlot(true);

  const [sample, setSample] = usePersistedVizControl<string | null>(metadata, 'sample', config.sample ?? null);
  const [chrom, setChrom] = usePersistedVizControl<string | null>(metadata, 'chrom', config.chrom ?? null);
  const [showBaf, setShowBaf] = usePersistedVizControl<boolean>(metadata, 'show_baf', config.show_baf ?? true);
  const [yRange, setYRange] = usePersistedVizControl<number>(metadata, 'y_range', config.y_range ?? DEFAULT_Y_RANGE);
  const [pointSize, setPointSize] = usePersistedVizControl<number>(metadata, 'point_size', config.point_size ?? DEFAULT_POINT_SIZE);

  const gainThreshold = config.gain_threshold ?? DEFAULT_GAIN_THRESHOLD;
  const lossThreshold = config.loss_threshold ?? DEFAULT_LOSS_THRESHOLD;
  const maxBins = config.max_bins && config.max_bins > 0 ? config.max_bins : DEFAULT_MAX_BINS;

  const columns = useMemo(() => {
    const cols: string[] = [];
    for (const col of [
      config.sample_col,
      config.chrom_col,
      config.start_col,
      config.end_col,
      config.log2_col,
      config.baf_col,
      config.copy_number_col,
      config.segment_col,
      config.label_col,
    ]) {
      if (col && !cols.includes(col)) cols.push(col);
    }
    return cols;
  }, [
    config.sample_col,
    config.chrom_col,
    config.start_col,
    config.end_col,
    config.log2_col,
    config.baf_col,
    config.copy_number_col,
    config.segment_col,
    config.label_col,
  ]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    const wfId = metadata.wf_id;
    const dcId = metadata.dc_id;
    if (!wfId || !dcId || !config.chrom_col || !config.start_col || !config.log2_col) {
      setError('Copy-number profile: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId,
      dcId,
      columns,
      filters,
      vizKind: CNV_PROFILE_VIZ_KIND,
      roles: {
        sample: config.sample_col,
        chrom: config.chrom_col,
        start: config.start_col,
        end: config.end_col,
        log2: config.log2_col,
        ...(config.baf_col ? { baf: config.baf_col } : {}),
        ...(config.copy_number_col ? { copy_number: config.copy_number_col } : {}),
        ...(config.segment_col ? { segment: config.segment_col } : {}),
        ...(config.label_col ? { label: config.label_col } : {}),
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
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(columns), JSON.stringify(filters), refreshTick]);

  const parsed = useMemo(
    () =>
      rows
        ? parseCnvRows(rows, {
            sample: config.sample_col,
            chrom: config.chrom_col,
            start: config.start_col,
            end: config.end_col,
            log2: config.log2_col,
            baf: config.baf_col,
            copyNumber: config.copy_number_col,
            segment: config.segment_col,
            label: config.label_col,
          })
        : [],
    [rows, config],
  );

  // Sample and chromosome domains come from the whole frame, so narrowing the
  // drawing down to one of them never removes the option to go back.
  const samples = useMemo(() => {
    const seen = Array.from(new Set(parsed.map((r) => r.sample).filter((s) => s !== '')));
    return seen.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
  }, [parsed]);
  const allChroms = useMemo(() => sortChromosomes(parsed.map((r) => r.chrom)), [parsed]);

  const activeSample = sample && samples.includes(sample) ? sample : (samples[0] ?? null);
  const activeChrom = chrom && chrom !== ALL_CHROMOSOMES && allChroms.includes(chrom) ? chrom : null;

  const figure = useMemo(() => {
    if (!rows || parsed.length === 0) return null;

    const inScope = parsed.filter(
      (r) =>
        (activeSample === null || r.sample === '' || r.sample === activeSample) &&
        (activeChrom === null || r.chrom === activeChrom),
    );
    if (inScope.length === 0) return null;

    const drawnChroms = activeChrom ? [activeChrom] : allChroms;
    const axis = buildGenomeAxis(inScope, drawnChroms);
    // Rank lookup rather than `indexOf`: the sort below and the per-bin tint
    // both ask for it, and a whole-exome profile runs to 200k bins over 24
    // chromosomes, where a linear scan per comparison is the whole frame time.
    const chromRank = new Map(drawnChroms.map((c, i) => [c, i]));

    const segments = inScope.filter((r) => r.kind === 'segment');
    const rawBins = inScope
      .filter((r) => r.kind === 'bin')
      .sort((a, b) => {
        const d = (chromRank.get(a.chrom) ?? 0) - (chromRank.get(b.chrom) ?? 0);
        return d !== 0 ? d : a.start - b.start;
      });
    const bins = decimateBins(rawBins, maxBins);

    const { gridColor } = plotlyThemeColors(isDark, theme);
    const axisTheme = plotlyAxisOverrides(isDark, theme);
    const tints = binTints(isDark, theme);
    const classColour = classColours(isDark, theme);
    const ramp = copyNumberRamp(isDark, theme);
    const colourByCopyNumber = Boolean(config.copy_number_col);

    const binX: number[] = [];
    const binY: number[] = [];
    const binColour: string[] = [];
    const binHover: string[] = [];
    for (const row of bins) {
      const x = genomeX(axis, row.chrom, (row.start + row.end) / 2);
      if (x === null) continue;
      binX.push(x);
      binY.push(row.log2);
      binColour.push(
        colourByCopyNumber
          ? ramp[copyNumberBucket(row.copyNumber)]
          : tints[(chromRank.get(row.chrom) ?? 0) % tints.length],
      );
      binHover.push(hoverText(row, 'bin log2'));
    }

    const data: any[] = [
      adaptGlTrace(
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: binX,
          y: binY,
          name: 'Bins',
          marker: { color: binColour, size: pointSize, opacity: 0.75 },
          text: binHover,
          hovertemplate: '%{text}<extra></extra>',
          showlegend: false,
        },
        glGranted,
      ),
    ];

    for (const cls of CNV_CLASS_ORDER) {
      const ofClass = segments.filter(
        (s) => classifyLog2(s.log2, gainThreshold, lossThreshold) === cls,
      );
      if (ofClass.length === 0) continue;
      const strokes = segmentStrokes(ofClass, axis);
      data.push({
        type: 'scatter' as const,
        mode: 'lines' as const,
        x: strokes.x,
        y: strokes.y,
        name: `${CNV_CLASS_LABEL[cls]} (${ofClass.length})`,
        line: { color: classColour[cls], width: SEGMENT_WIDTH },
        text: strokes.hover,
        hovertemplate: '%{text}<extra></extra>',
        connectgaps: false,
      });
    }

    const drawBaf = Boolean(config.baf_col) && showBaf;
    const bafX: number[] = [];
    const bafY: number[] = [];
    const bafHover: string[] = [];
    if (drawBaf) {
      for (const row of bins) {
        if (row.baf === null) continue;
        const x = genomeX(axis, row.chrom, (row.start + row.end) / 2);
        if (x === null) continue;
        bafX.push(x);
        bafY.push(row.baf);
        bafHover.push(hoverText(row, 'bin log2'));
      }
    }
    const hasBafPanel = bafX.length > 0;
    if (hasBafPanel) {
      data.push(
        adaptGlTrace(
          {
            type: 'scattergl' as const,
            mode: 'markers' as const,
            x: bafX,
            y: bafY,
            name: 'BAF',
            marker: { color: theme.colors.teal[isDark ? 4 : 7], size: pointSize, opacity: 0.7 },
            text: bafHover,
            hovertemplate: '%{text}<extra></extra>',
            yaxis: 'y2',
            showlegend: false,
          },
          glGranted,
        ),
      );
    }

    // Chromosome separators, drawn across both panels so the eye carries a
    // boundary from the log2 track down into the BAF track.
    const shapes: any[] = axis.boundaries.map((x) => ({
      type: 'line',
      x0: x,
      x1: x,
      y0: 0,
      y1: 1,
      xref: 'x',
      yref: 'paper',
      line: { color: gridColor, width: 1 },
      layer: 'below',
    }));
    // The two thresholds, so a reader can see where the segment colours switch.
    for (const level of [gainThreshold, lossThreshold]) {
      shapes.push({
        type: 'line',
        x0: axis.range[0],
        x1: axis.range[1],
        y0: level,
        y1: level,
        xref: 'x',
        yref: 'y',
        line: { color: gridColor, width: 1, dash: 'dot' },
        layer: 'below',
      });
    }
    if (hasBafPanel) {
      // Balanced heterozygosity: the line an LOH region departs from.
      shapes.push({
        type: 'line',
        x0: axis.range[0],
        x1: axis.range[1],
        y0: 0.5,
        y1: 0.5,
        xref: 'x',
        yref: 'y2',
        line: { color: gridColor, width: 1, dash: 'dot' },
        layer: 'below',
      });
    }

    const wholeGenome = activeChrom === null;
    const xaxis: Record<string, unknown> = {
      ...axisTheme,
      title: { text: wholeGenome ? 'Genome position' : `${activeChrom} position` },
      range: axis.range,
      anchor: hasBafPanel ? 'y2' : 'y',
      ...(wholeGenome
        ? { tickmode: 'array', tickvals: axis.tickvals, ticktext: axis.ticktext, showgrid: false }
        : { showgrid: true }),
    };

    return {
      data,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        xaxis,
        yaxis: {
          ...axisTheme,
          title: { text: 'log2 ratio' },
          range: [-yRange, yRange],
          domain: hasBafPanel ? LOG2_DOMAIN_WITH_BAF : [0, 1],
        },
        ...(hasBafPanel
          ? {
              yaxis2: {
                ...axisTheme,
                title: { text: 'BAF' },
                range: [0, 1],
                domain: BAF_DOMAIN,
              },
            }
          : {}),
        shapes,
        hovermode: 'closest',
        showlegend: segments.length > 0,
        legend: { orientation: 'h', y: 1.04, yanchor: 'bottom', x: 0 },
        margin: { l: 60, r: 12, t: segments.length > 0 ? 28 : 12, b: 48 },
        autosize: true,
      },
    };
  }, [
    rows,
    parsed,
    activeSample,
    activeChrom,
    allChroms,
    config.baf_col,
    config.copy_number_col,
    gainThreshold,
    lossThreshold,
    maxBins,
    showBaf,
    yRange,
    pointSize,
    glGranted,
    isDark,
    theme,
  ]);

  const controls = (
    <Stack gap="xs">
      {samples.length > 1 ? (
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Sample
          </Text>
          <Select
            size="xs"
            data={samples}
            value={activeSample}
            onChange={(value) => setSample(value)}
            allowDeselect={false}
            searchable={samples.length > 8}
          />
        </Stack>
      ) : null}
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Chromosome
        </Text>
        <Select
          size="xs"
          data={[
            { value: ALL_CHROMOSOMES, label: 'Whole genome' },
            ...allChroms.map((c) => ({ value: c, label: c })),
          ]}
          value={activeChrom ?? ALL_CHROMOSOMES}
          onChange={(value) => setChrom(value === ALL_CHROMOSOMES ? null : value)}
          allowDeselect={false}
          searchable={allChroms.length > 8}
        />
      </Stack>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          log2 axis limit
        </Text>
        <Slider
          size="xs"
          min={0.5}
          max={6}
          step={0.5}
          value={yRange}
          onChange={setYRange}
          label={(v) => `+/- ${v}`}
        />
      </Stack>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Bin marker size
        </Text>
        <Slider size="xs" min={1} max={12} step={1} value={pointSize} onChange={setPointSize} />
      </Stack>
      {config.baf_col ? (
        <Switch
          size="xs"
          checked={showBaf}
          onChange={(e) => setShowBaf(e.currentTarget.checked)}
          label="Show BAF panel"
        />
      ) : null}
    </Stack>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Copy-number profile'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={columns}
    >
      {figure ? <CnvProfilePlot figure={figure} isDark={isDark} theme={theme} /> : null}
    </AdvancedVizFrame>
  );
};

export default CnvProfileRenderer;
