import React, { useEffect, useMemo, useState } from 'react';
import {
  alpha,
  Group,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

interface EnrichmentConfig {
  term_col: string;
  nes_col: string;
  padj_col: string;
  gene_count_col: string;
  source_col?: string | null;
  padj_threshold?: number;
  top_n?: number;
  colour_scale?: EnrichmentColourScale;
  reverse_scale?: boolean;
  max_dot_size?: number;
  min_dot_size?: number;
  term_sort?: TermSort;
  annotate_top_n?: number;
  marker_outline?: boolean;
}

// 'Auto' keeps the per-mode, per-theme palette the renderer has always drawn;
// any named scale overrides it for every colour-by mode.
type EnrichmentColourScale = 'Auto' | ColourScale;
type TermSort = 'nes' | 'significance' | 'gene_count' | 'name';

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: EnrichmentConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const EnrichmentRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as EnrichmentConfig;
  const isDark = colorScheme === 'dark';

  const [topN, setTopN] = usePersistedVizControl(metadata, 'top_n', 20);
  const [padjThreshold, setPadjThreshold] = usePersistedVizControl(metadata, 'padj_threshold', 0.05);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  type ColourBy = 'neg_log10_padj' | 'abs_nes' | 'nes_sign' | 'gene_count';
  const [colourBy, setColourBy] = usePersistedVizControl<ColourBy>(metadata, 'default_colour_by', 'neg_log10_padj');
  // Display options, same vocabulary as the dot plot. Every fallback below is
  // what the renderer drew before these controls existed.
  const [colourScale, setColourScale] = usePersistedVizControl<EnrichmentColourScale>(
    metadata,
    'colour_scale',
    'Auto',
  );
  const [reverseScale, setReverseScale] = usePersistedVizControl(metadata, 'reverse_scale', false);
  const [maxSize, setMaxSize] = usePersistedVizControl(metadata, 'max_dot_size', 30);
  const [minSize, setMinSize] = usePersistedVizControl(metadata, 'min_dot_size', 6);
  const [termSort, setTermSort] = usePersistedVizControl<TermSort>(metadata, 'term_sort', 'nes');
  const [annotateTopN, setAnnotateTopN] = usePersistedVizControl(metadata, 'annotate_top_n', 0);
  const [markerOutline, setMarkerOutline] = usePersistedVizControl(metadata, 'marker_outline', false);

  const requiredCols = useMemo(() => {
    const cols = [
      config.term_col,
      config.nes_col,
      config.padj_col,
      config.gene_count_col,
    ].filter(Boolean) as string[];
    if (config.source_col && !cols.includes(config.source_col)) cols.push(config.source_col);
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // The server serves this kind whole because the renderer aggregates its rows;
  // past `advanced_viz_no_sample_max_rows` it samples anyway and says so here.
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Enrichment: missing data binding');
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
      vizKind: 'enrichment',
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

  const sources = useMemo(() => {
    if (!rows || !config.source_col) return [] as string[];
    const seen = new Set<string>();
    for (const v of (rows[config.source_col] || []) as unknown[]) seen.add(String(v ?? ''));
    return Array.from(seen).sort();
  }, [rows, config.source_col]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const terms = (rows[config.term_col] || []) as (string | number)[];
    const nesArr = (rows[config.nes_col] || []) as number[];
    const padjArr = (rows[config.padj_col] || []) as number[];
    const counts = (rows[config.gene_count_col] || []) as number[];
    const srcArr = config.source_col ? (rows[config.source_col] as (string | number)[]) : null;

    type Row = { term: string; nes: number; padj: number; count: number; src: string };
    const collected: Row[] = [];
    for (let i = 0; i < terms.length; i++) {
      const padj = Number(padjArr[i]);
      const nes = Number(nesArr[i]);
      if (!Number.isFinite(padj) || !Number.isFinite(nes)) continue;
      if (padj > padjThreshold) continue;
      const src = srcArr ? String(srcArr[i] ?? '') : '';
      if (
        selectedSources.length > 0 &&
        srcArr &&
        !selectedSources.includes(src)
      )
        continue;
      collected.push({
        term: String(terms[i] ?? ''),
        nes,
        padj,
        count: Number(counts[i]) || 0,
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

    // Map gene_count → marker size (sqrt scaled, capped). sqrt rather than
    // linear because the eye reads dot area, not radius.
    const counts2 = top.map((r) => r.count);
    const cMax = Math.max(...counts2, 1);
    const sizeSpan = Math.max(0, maxSize - minSize);
    const sizes = counts2.map((c) => minSize + Math.sqrt(c / cMax) * sizeSpan);

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
    // mode — encoded as the integer sign so plotly draws two colour buckets.
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
    // better than Viridis when the user picked |NES| (magnitude-only — warm
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
      data: [
        {
          type: 'scatter' as const,
          mode: 'markers' as const,
          x: top.map((r) => r.nes),
          y: top.map((r) => r.term),
          customdata: top.map((r) => [r.padj, r.count, r.src]),
          hovertemplate:
            `<b>%{y}</b><br>NES: %{x:.2f}<br>padj: %{customdata[0]:.2e}` +
            `<br>genes: %{customdata[1]}` +
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

  const controls = (
    <Stack gap="xs">
      {sources.length > 0 ? (
        <MultiSelect
          size="xs"
          label="Source"
          value={selectedSources}
          onChange={setSelectedSources}
          data={sources}
          placeholder="all sources"
          clearable
        />
      ) : null}
      <NumberInput
        size="xs"
        label="Top-N pathways"
        value={topN}
        onChange={(v) => setTopN(Math.max(1, Number(v) || 20))}
        min={1}
        max={100}
      />
      <NumberInput
        size="xs"
        label="padj threshold"
        description="Hide pathways with padj above this cutoff"
        value={padjThreshold}
        onChange={(v) => setPadjThreshold(Math.max(0, Math.min(1, Number(v) || 0.05)))}
        min={0}
        max={1}
        step={0.01}
        decimalScale={3}
      />
      <Select
        size="xs"
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
      <Select
        size="xs"
        label="Colourscale"
        description="Auto follows the colour-by mode and the theme"
        value={colourScale}
        onChange={(v) => v && setColourScale(v as EnrichmentColourScale)}
        data={['Auto', ...COLOUR_SCALES]}
        allowDeselect={false}
      />
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Direction
        </Text>
        <Switch
          size="xs"
          checked={reverseScale}
          onChange={(e) => setReverseScale(e.currentTarget.checked)}
          label="Reverse colourscale"
        />
      </Stack>
      <Select
        size="xs"
        label="Sort terms"
        description="Which term sits at the top of the axis"
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
      <Group gap="xs" grow>
        <NumberInput
          size="xs"
          label="Max dot size"
          value={maxSize}
          onChange={(v) => setMaxSize(Math.max(4, Math.min(60, Number(v) || 30)))}
          min={4}
          max={60}
        />
        <NumberInput
          size="xs"
          label="Min dot size"
          value={minSize}
          onChange={(v) => setMinSize(Math.max(0, Math.min(20, Number(v) || 6)))}
          min={0}
          max={20}
        />
      </Group>
      <NumberInput
        size="xs"
        label="Annotate top-N"
        description="Gene count on the most significant dots; 0 = off"
        value={annotateTopN}
        onChange={(v) => setAnnotateTopN(Math.max(0, Math.min(40, Number(v) || 0)))}
        min={0}
        max={40}
      />
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Markers
        </Text>
        <Switch
          size="xs"
          checked={markerOutline}
          onChange={(e) => setMarkerOutline(e.currentTarget.checked)}
          label="Marker outline"
        />
      </Stack>
    </Stack>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Pathway enrichment'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
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

export default EnrichmentRenderer;
