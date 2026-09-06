import React, { useEffect, useMemo, useState } from 'react';
import {
  alpha,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  type AdvancedVizKind,
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { resolveCategoricalPalette, stableColorMap } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/**
 * The canonical GSEA enrichment plot: three panels sharing one rank axis.
 *
 *   1. the running enrichment score walked along the ranked gene list,
 *   2. a hit rug — one tick per member gene, at its rank,
 *   3. the ranked metric the list was ordered by.
 *
 * Panels 2 and 3 exist only when the component binds `member_col` / `metric_col`;
 * the plot degrades to the curve alone, which is still the thing the reader came
 * for. Every panel is optional in the *layout* sense too: the domains below are
 * allocated from whichever panels survived, so a two-panel figure fills the tile
 * rather than leaving a gap where the third would have been.
 *
 * Mirrors EnrichmentRenderer's house shape: one `fetchAdvancedVizData` call, the
 * `plotlyTheme` helpers for dark mode, `AdvancedVizFrame` for the loading /
 * error / empty / Show-data / Settings chrome.
 */

interface GseaRunningScoreConfig {
  gene_set_col: string;
  rank_col: string;
  running_es_col: string;
  member_col?: string | null;
  metric_col?: string | null;
  show_leading_edge?: boolean;
  top_n_sets?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: GseaRunningScoreConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/**
 * Always sent with the fetch. The server looks the kind up in
 * `KIND_SAMPLING_POLICY`, where `gsea_running_score` is registered as `"none"`;
 * omitting it would fall back to a uniform sample, and a uniformly sampled
 * running score is a curve with holes in it.
 */
const VIZ_KIND: AdvancedVizKind = 'gsea_running_score';

const PLOT_STYLE = { width: '100%', height: '100%' };
const PLOT_CONFIG = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d'],
  // Wheel-zoom would swallow page scrolling whenever the pointer crossed the
  // tile; the modebar's Zoom button stays available for deliberate zooming.
  scrollZoom: false,
};

/** Vertical gap between stacked panels, in paper fraction. */
const PANEL_GAP = 0.045;

type LayoutMode = 'overlay' | 'facet';

/** One stacked panel, before its y-domain has been allocated. */
interface PanelSpec {
  id: string;
  /** Relative height; domains are shared out in proportion to these. */
  height: number;
}

/** A gene set's walk along the ranked list, plus the leading-edge interval. */
interface SetSeries {
  name: string;
  ranks: number[];
  es: number[];
  memberRanks: number[];
  /** Value of the running score at its extremum — the set's enrichment score. */
  peakEs: number;
  peakRank: number;
  /** Index range of the leading-edge subset within `ranks` / `es`. */
  leadStart: number;
  leadEnd: number;
}

function toNumber(value: unknown): number {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim() !== '') return Number(value);
  return Number.NaN;
}

/**
 * Whether a `member_col` cell marks this rank as a member of the gene set.
 *
 * The role is declared boolean, but a boolean column survives a TSV round-trip
 * as anything from `true` to `1` to `TRUE`, and Delta hands back whichever the
 * recipe wrote. Accept the spellings rather than silently drawing an empty rug.
 */
function isMember(value: unknown): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase();
    return v === 'true' || v === 't' || v === 'yes' || v === 'y' || v === '1';
  }
  return false;
}

/**
 * Pure presentation wrapper. Memoised on (figure, isDark, theme) so a parent
 * re-render driven by filter or refresh state doesn't hand Plotly fresh data +
 * layout objects and rebuild the figure mid-interaction.
 */
const GseaPlot = React.memo<{
  figure: { data: unknown[]; layout: Record<string, unknown> };
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
}>(({ figure, isDark, theme }) => {
  const themedData = useMemo(
    () => applyDataTheme(figure.data, isDark, theme),
    [figure.data, isDark, theme],
  );
  const themedLayout = useMemo(
    () => applyLayoutTheme(figure.layout, isDark, theme),
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
GseaPlot.displayName = 'GseaPlot';

const GseaRunningScoreRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as GseaRunningScoreConfig;
  const isDark = colorScheme === 'dark';
  const palette = resolveCategoricalPalette(theme);

  // Persisted Tier-2 controls — both keys are fields on GseaRunningScoreConfig.
  const [topNSets, setTopNSets] = usePersistedVizControl(metadata, 'top_n_sets', 5);
  const [showLeadingEdge, setShowLeadingEdge] = usePersistedVizControl(metadata, 'show_leading_edge', true);
  // Local-only controls: GseaRunningScoreConfig has no field to persist them
  // into, and inventing one here would make the component unloadable on its
  // next validation (the config model is extra="forbid"). They behave the way
  // every viz control did before the persistence hook existed — remembered for
  // the life of the mount.
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('overlay');
  const [showHits, setShowHits] = useState(true);
  const [showMetric, setShowMetric] = useState(true);

  const requiredCols = useMemo(() => {
    const cols = [config.gene_set_col, config.rank_col, config.running_es_col].filter(
      Boolean,
    ) as string[];
    if (config.member_col && !cols.includes(config.member_col)) cols.push(config.member_col);
    if (config.metric_col && !cols.includes(config.metric_col)) cols.push(config.metric_col);
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // The kind's sampling policy is "none" — the curve is read as an ordered whole.
  // Past `advanced_viz_no_sample_max_rows` the server samples anyway, and the
  // frame says so rather than presenting a punctured curve as the real one.
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('GSEA running score: missing data binding');
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
      vizKind: VIZ_KIND,
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
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filters),
    refreshTick,
  ]);

  /** Every gene set in the frame, walked and ranked by |enrichment score|. */
  const allSeries = useMemo<SetSeries[]>(() => {
    if (!rows) return [];
    const setArr = (rows[config.gene_set_col] || []) as unknown[];
    const rankArr = (rows[config.rank_col] || []) as unknown[];
    const esArr = (rows[config.running_es_col] || []) as unknown[];
    const memberArr = config.member_col ? ((rows[config.member_col] || []) as unknown[]) : null;

    const grouped = new Map<string, { rank: number; es: number; member: boolean }[]>();
    for (let i = 0; i < setArr.length; i++) {
      const rank = toNumber(rankArr[i]);
      const es = toNumber(esArr[i]);
      if (!Number.isFinite(rank) || !Number.isFinite(es)) continue;
      const name = String(setArr[i] ?? '');
      if (!name) continue;
      let bucket = grouped.get(name);
      if (!bucket) {
        bucket = [];
        grouped.set(name, bucket);
      }
      bucket.push({ rank, es, member: memberArr ? isMember(memberArr[i]) : false });
    }

    const out: SetSeries[] = [];
    for (const [name, points] of grouped) {
      points.sort((a, b) => a.rank - b.rank);
      let peakIdx = 0;
      for (let i = 1; i < points.length; i++) {
        if (Math.abs(points[i].es) > Math.abs(points[peakIdx].es)) peakIdx = i;
      }
      const peakEs = points[peakIdx]?.es ?? 0;
      // GSEA's leading-edge subset is the stretch of the ranked list on the
      // enriched side of the extremum: everything up to the peak for a
      // positively enriched set, everything from the trough onwards for a
      // negatively enriched one. Shading [0, peak] unconditionally would put
      // the highlight on the wrong half of a down-regulated set.
      const leadStart = peakEs >= 0 ? 0 : peakIdx;
      const leadEnd = peakEs >= 0 ? peakIdx : points.length - 1;
      out.push({
        name,
        ranks: points.map((p) => p.rank),
        es: points.map((p) => p.es),
        memberRanks: points.filter((p) => p.member).map((p) => p.rank),
        peakEs,
        peakRank: points[peakIdx]?.rank ?? 0,
        leadStart,
        leadEnd,
      });
    }
    // Strongest enrichment first, so the default top-N is the interesting one.
    out.sort((a, b) => Math.abs(b.peakEs) - Math.abs(a.peakEs));
    return out;
  }, [rows, config.gene_set_col, config.rank_col, config.running_es_col, config.member_col]);

  const shown = useMemo(() => allSeries.slice(0, Math.max(1, topNSets)), [allSeries, topNSets]);

  // Keyed on every set in the frame rather than on the visible slice, so a set
  // keeps its colour as the user changes top-N or filters the dashboard. The
  // universe is free here: the kind is served whole, so the frame already holds
  // every set — no second round-trip for the distinct values.
  const setNames = useMemo(() => allSeries.map((s) => s.name), [allSeries]);
  const colourMap = useMemo(
    () => stableColorMap(setNames, palette),
    [setNames.join(' '), palette],
  );

  /** rank → ranking metric, deduplicated: the metric repeats once per gene set. */
  const metricPoints = useMemo(() => {
    if (!rows || !config.metric_col) return { x: [] as number[], y: [] as number[] };
    const rankArr = (rows[config.rank_col] || []) as unknown[];
    const metricArr = (rows[config.metric_col] || []) as unknown[];
    const byRank = new Map<number, number>();
    for (let i = 0; i < rankArr.length; i++) {
      const rank = toNumber(rankArr[i]);
      const metric = toNumber(metricArr[i]);
      if (!Number.isFinite(rank) || !Number.isFinite(metric)) continue;
      if (!byRank.has(rank)) byRank.set(rank, metric);
    }
    const ordered = Array.from(byRank.entries()).sort((a, b) => a[0] - b[0]);
    return { x: ordered.map((e) => e[0]), y: ordered.map((e) => e[1]) };
  }, [rows, config.rank_col, config.metric_col]);

  const hasHits = useMemo(() => shown.some((s) => s.memberRanks.length > 0), [shown]);

  const figure = useMemo(() => {
    if (shown.length === 0) return null;

    const facet = layoutMode === 'facet';
    const drawRug = showHits && hasHits;
    const drawMetric = showMetric && metricPoints.x.length > 0;

    // Panels top → bottom, sized relative to one another. The rug grows with the
    // number of sets it has to stack; everything else is a fixed proportion.
    const panels: PanelSpec[] = [];
    if (facet) {
      shown.forEach((_, i) => panels.push({ id: `es:${i}`, height: 1 }));
    } else {
      panels.push({ id: 'es', height: 1.9 });
    }
    if (drawRug) panels.push({ id: 'rug', height: Math.min(0.8, 0.12 * shown.length + 0.1) });
    if (drawMetric) panels.push({ id: 'metric', height: 0.7 });

    const totalHeight = panels.reduce((acc, p) => acc + p.height, 0);
    const usable = Math.max(0.2, 1 - PANEL_GAP * (panels.length - 1));
    const domains = new Map<string, [number, number]>();
    const axisIndex = new Map<string, number>();
    let top = 1;
    panels.forEach((panel, i) => {
      const height = (panel.height / totalHeight) * usable;
      domains.set(panel.id, [Math.max(0, top - height), top]);
      axisIndex.set(panel.id, i + 1);
      top = top - height - PANEL_GAP;
    });
    const axisRef = (id: string) => {
      const n = axisIndex.get(id) ?? 1;
      return n === 1 ? 'y' : `y${n}`;
    };
    const axisKey = (id: string) => {
      const n = axisIndex.get(id) ?? 1;
      return n === 1 ? 'yaxis' : `yaxis${n}`;
    };

    const themeColors = plotlyThemeColors(isDark, theme);
    const data: Record<string, unknown>[] = [];
    const annotations: Record<string, unknown>[] = [];

    shown.forEach((series, i) => {
      const panelId = facet ? `es:${i}` : 'es';
      const yref = axisRef(panelId);
      const colour = colourMap.get(series.name);

      // Leading edge, drawn as the area under the running score up to (or from)
      // the extremum. A full-height band would be the textbook rendering, but
      // five overlaid bands read as mud; the filled segment says the same thing
      // per curve and survives the overlay layout.
      if (showLeadingEdge && series.leadEnd > series.leadStart) {
        data.push({
          type: 'scatter',
          mode: 'lines',
          x: series.ranks.slice(series.leadStart, series.leadEnd + 1),
          y: series.es.slice(series.leadStart, series.leadEnd + 1),
          fill: 'tozeroy',
          fillcolor: alpha(colour, 0.18),
          line: { width: 0 },
          xaxis: 'x',
          yaxis: yref,
          legendgroup: series.name,
          showlegend: false,
          hoverinfo: 'skip',
        });
      }

      data.push({
        type: 'scatter',
        mode: 'lines',
        x: series.ranks,
        y: series.es,
        name: series.name,
        line: { color: colour, width: 1.8 },
        xaxis: 'x',
        yaxis: yref,
        legendgroup: series.name,
        showlegend: !facet,
        hovertemplate: `<b>${series.name}</b><br>rank %{x}<br>running ES %{y:.3f}<extra></extra>`,
      });

      // The extremum, marked so the reader can read the enrichment score off the
      // curve rather than eyeballing where the shading stops.
      data.push({
        type: 'scatter',
        mode: 'markers',
        x: [series.peakRank],
        y: [series.peakEs],
        marker: { color: colour, size: 7, symbol: 'circle' },
        xaxis: 'x',
        yaxis: yref,
        legendgroup: series.name,
        showlegend: false,
        hovertemplate: `<b>${series.name}</b><br>peak ES %{y:.3f} at rank %{x}<extra></extra>`,
      });

      if (facet) {
        annotations.push({
          xref: 'paper',
          x: 0,
          xanchor: 'left',
          yref: `${yref} domain`,
          y: 1,
          yanchor: 'bottom',
          text: series.name,
          showarrow: false,
          font: { size: 9, color: colour },
        });
      }
    });

    if (drawRug) {
      const rugRef = axisRef('rug');
      shown.forEach((series, i) => {
        if (series.memberRanks.length === 0) return;
        // First set on the top row, matching the legend / facet order.
        const row = shown.length - 1 - i;
        data.push({
          type: 'scatter',
          mode: 'markers',
          x: series.memberRanks,
          y: series.memberRanks.map(() => row),
          marker: {
            symbol: 'line-ns-open',
            size: 9,
            color: colourMap.get(series.name),
            line: { width: 1, color: colourMap.get(series.name) },
          },
          xaxis: 'x',
          yaxis: rugRef,
          legendgroup: series.name,
          showlegend: false,
          hovertemplate: `<b>${series.name}</b><br>hit at rank %{x}<extra></extra>`,
        });
      });
    }

    if (drawMetric) {
      data.push({
        type: 'scatter',
        mode: 'lines',
        x: metricPoints.x,
        y: metricPoints.y,
        fill: 'tozeroy',
        fillcolor: alpha(themeColors.textColor, 0.28),
        line: { width: 0.6, color: themeColors.textColor },
        xaxis: 'x',
        yaxis: axisRef('metric'),
        showlegend: false,
        hovertemplate: 'rank %{x}<br>metric %{y:.3f}<extra></extra>',
      });
    }

    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      margin: { l: 58, r: 16, t: facet ? 14 : 30, b: 46 },
      autosize: true,
      hovermode: 'closest',
      showlegend: !facet,
      legend: { orientation: 'h', x: 0, y: 1.04, yanchor: 'bottom', font: { size: 10 } },
      annotations,
    };

    panels.forEach((panel) => {
      const domain = domains.get(panel.id) as [number, number];
      if (panel.id === 'rug') {
        layout[axisKey(panel.id)] = {
          ...plotlyAxisOverrides(isDark, theme),
          domain,
          anchor: 'x',
          range: [-0.6, shown.length - 0.4],
          showticklabels: false,
          showgrid: false,
          zeroline: false,
          fixedrange: true,
          title: { text: 'hits', font: { size: 9 }, standoff: 4 },
        };
      } else if (panel.id === 'metric') {
        layout[axisKey(panel.id)] = {
          ...plotlyAxisOverrides(isDark, theme),
          domain,
          anchor: 'x',
          zeroline: true,
          title: { text: 'ranked metric', font: { size: 10 }, standoff: 4 },
        };
      } else {
        layout[axisKey(panel.id)] = {
          ...plotlyAxisOverrides(isDark, theme),
          domain,
          anchor: 'x',
          zeroline: true,
          title: facet ? undefined : { text: 'running ES', font: { size: 10 }, standoff: 4 },
          tickfont: { size: 9 },
        };
      }
    });

    // One shared x axis for every panel, drawn under the bottom-most one — the
    // rank positions have to line up across the curve, the rug and the metric,
    // which is the whole point of the stack.
    const bottom = panels[panels.length - 1];
    layout.xaxis = {
      ...plotlyAxisOverrides(isDark, theme),
      title: { text: 'rank in ordered gene list', standoff: 8 },
      anchor: axisRef(bottom.id),
      zeroline: false,
      showgrid: true,
    };

    return { data: data as unknown[], layout };
  }, [
    shown,
    colourMap,
    layoutMode,
    showLeadingEdge,
    showHits,
    showMetric,
    hasHits,
    metricPoints,
    isDark,
    theme,
  ]);

  const counts = useMemo(() => {
    if (allSeries.length === 0) return undefined;
    const ranks = shown.reduce((acc, s) => Math.max(acc, s.ranks.length), 0);
    return { 'gene sets': shown.length, ranks };
  }, [allSeries.length, shown]);

  const controls = (
    <Stack gap="xs">
      <NumberInput
        size="xs"
        label="Top-N gene sets"
        description="Ranked by the size of their peak running score"
        value={topNSets}
        onChange={(v) => setTopNSets(Math.max(1, Math.min(20, Number(v) || 5)))}
        min={1}
        max={20}
      />
      <Select
        size="xs"
        label="Layout"
        description="One panel per set, or every curve on one axis"
        value={layoutMode}
        onChange={(v) => v && setLayoutMode(v as LayoutMode)}
        data={[
          { value: 'overlay', label: 'Overlay' },
          { value: 'facet', label: 'Facet by gene set' },
        ]}
        allowDeselect={false}
      />
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Panels
        </Text>
        <Switch
          size="xs"
          checked={showLeadingEdge}
          onChange={(e) => setShowLeadingEdge(e.currentTarget.checked)}
          label="Shade the leading edge"
        />
        {config.member_col ? (
          <Switch
            size="xs"
            checked={showHits}
            onChange={(e) => setShowHits(e.currentTarget.checked)}
            label="Hit rug"
            disabled={!hasHits}
          />
        ) : null}
        {config.metric_col ? (
          <Switch
            size="xs"
            checked={showMetric}
            onChange={(e) => setShowMetric(e.currentTarget.checked)}
            label="Ranked metric"
          />
        ) : null}
      </Stack>
    </Stack>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'GSEA running enrichment score'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      counts={counts}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && !figure ? 'No gene set to walk' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? <GseaPlot figure={figure} isDark={isDark} theme={theme} /> : null}
    </AdvancedVizFrame>
  );
};

export default GseaRunningScoreRenderer;
