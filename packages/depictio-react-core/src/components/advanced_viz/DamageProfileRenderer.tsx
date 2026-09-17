import React, { useEffect, useMemo, useState } from 'react';
import { MultiSelect, NumberInput, Select, Stack, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

type Ends = 'both' | '5p' | '3p';

/** Mirrors `DamageProfileConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface DamageProfileConfig {
  sample_col: string;
  end_col: string;
  position_col: string;
  base_change_col: string;
  frequency_col: string;
  ends?: Ends;
  max_position?: number;
  highlight?: string[];
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: DamageProfileConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// `damage_profile` is an already-aggregated (sample, end, position,
// base_change) table read whole (`KIND_SAMPLING_POLICY["damage_profile"] ==
// "none"`), same reasoning as `profile`.
const DAMAGE_PROFILE_VIZ_KIND: AdvancedVizKind = 'damage_profile';

const PLOT_STYLE = { width: '100%', height: '100%' };
const PLOT_CONFIG = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
  scrollZoom: false,
};

const DEFAULT_MAX_POSITION = 25;
const DEFAULT_HIGHLIGHT = ['C>T', 'G>A'];
// The substitution classes a damage table typically carries; a value outside
// this list (an unusual `base_change` string) still renders muted, unlabelled
// in the picker.
const SUBSTITUTION_OPTIONS = ['C>T', 'G>A', 'T>C', 'A>G', 'other'];
const MUTED_COLOUR = '#9aa0a6';
const HIGHLIGHT_PALETTE = TAB10_PALETTE;

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const DamageProfilePlot = React.memo<{
  figure: { data?: unknown[]; layout?: Record<string, unknown> };
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
}>(({ figure, isDark, theme }) => {
  const themedData = useMemo(() => applyDataTheme(figure.data, isDark, theme), [figure.data, isDark, theme]);
  const themedLayout = useMemo(
    () => applyLayoutTheme(figure.layout as any, isDark, theme),
    [figure.layout, isDark, theme],
  );
  return (
    <Plot data={themedData as any} layout={themedLayout as any} useResizeHandler style={PLOT_STYLE} config={PLOT_CONFIG as any} />
  );
});
DamageProfilePlot.displayName = 'DamageProfilePlot';

/**
 * Ancient-DNA misincorporation profile: substitution frequency by distance
 * from a read end, one panel each for 5p and 3p (or a single panel when
 * `ends` narrows to one side). C>T and G>A (the deamination signature) are
 * highlighted by default; every other substitution renders muted so the
 * damage curve stays the thing the eye is drawn to.
 *
 * Built as one figure with two x-axis domains rather than reusing
 * `SplitPanels`: `SplitPanels` deals a dashboard-wide *analysis group* into
 * independently-fetched panels, which doesn't fit a fixed 5p/3p split of one
 * already-fetched frame. `CoverageTrackRenderer`'s own per-sample facets
 * (built from axis domains, not `SplitPanels`) are the closer precedent.
 */
const DamageProfileRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const palette = resolveCategoricalPalette(theme, HIGHLIGHT_PALETTE);
  const config = (metadata.config || {}) as DamageProfileConfig;
  const isDark = colorScheme === 'dark';

  const [ends, setEnds] = usePersistedVizControl<Ends>(metadata, 'ends', config.ends ?? 'both');
  const [maxPosition, setMaxPosition] = usePersistedVizControl<number>(
    metadata,
    'max_position',
    config.max_position ?? DEFAULT_MAX_POSITION,
  );
  const [highlight, setHighlight] = usePersistedVizControl<string[]>(
    metadata,
    'highlight',
    config.highlight ?? DEFAULT_HIGHLIGHT,
  );

  const requiredCols = useMemo(
    () =>
      [config.sample_col, config.end_col, config.position_col, config.base_change_col, config.frequency_col].filter(
        Boolean,
      ) as string[],
    [config.sample_col, config.end_col, config.position_col, config.base_change_col, config.frequency_col],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 5) {
      setError('Damage profile: missing data binding');
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
      vizKind: DAMAGE_PROFILE_VIZ_KIND,
      roles: {
        sample: config.sample_col,
        end: config.end_col,
        position: config.position_col,
        base_change: config.base_change_col,
        frequency: config.frequency_col,
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
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), JSON.stringify(filters), refreshTick]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const samples = (rows[config.sample_col] || []) as unknown[];
    const endVals = (rows[config.end_col] || []) as unknown[];
    const positions = (rows[config.position_col] || []) as unknown[];
    const changes = (rows[config.base_change_col] || []) as unknown[];
    const freqs = (rows[config.frequency_col] || []) as unknown[];

    const panels: Ends[] = ends === 'both' ? ['5p', '3p'] : [ends];

    type Pt = { position: number; frequency: number };
    // panel -> "sample|base_change" -> points
    const byPanel = new Map<Ends, Map<string, Pt[]>>();
    for (const p of panels) byPanel.set(p, new Map());

    const n = Math.min(endVals.length, positions.length, changes.length, freqs.length);
    for (let i = 0; i < n; i++) {
      const endRaw = String(endVals[i] ?? '');
      const panel: Ends | null = endRaw === '5p' || endRaw === '3p' ? (endRaw as Ends) : null;
      if (!panel || !byPanel.has(panel)) continue;
      const position = num(positions[i]);
      const frequency = num(freqs[i]);
      if (position === null || frequency === null || position > maxPosition) continue;
      const sample = samples.length ? String(samples[i] ?? 'sample') : 'sample';
      const change = String(changes[i] ?? 'other');
      const key = `${sample}|${change}`;
      const bucket = byPanel.get(panel)!;
      let pts = bucket.get(key);
      if (!pts) {
        pts = [];
        bucket.set(key, pts);
      }
      pts.push({ position, frequency });
    }
    for (const bucket of byPanel.values()) {
      for (const pts of bucket.values()) pts.sort((a, b) => a.position - b.position);
    }

    const highlightSet = new Set(highlight.length ? highlight : DEFAULT_HIGHLIGHT);
    const highlightNames = Array.from(highlightSet).sort();
    const highlightColours = stableColorMap(highlightNames, palette, null);

    const colWidth = 1 / panels.length;
    const gap = panels.length > 1 ? 0.06 : 0;
    const traces: any[] = [];
    const annotations: any[] = [];
    const axes: Record<string, unknown> = {};

    panels.forEach((panel, panelIdx) => {
      const xaxisKey = panelIdx === 0 ? 'x' : `x${panelIdx + 1}`;
      const yaxisKey = panelIdx === 0 ? 'y' : `y${panelIdx + 1}`;
      const domainStart = panelIdx * colWidth + (panelIdx > 0 ? gap / 2 : 0);
      const domainEnd = (panelIdx + 1) * colWidth - (panelIdx < panels.length - 1 ? gap / 2 : 0);

      const bucket = byPanel.get(panel)!;
      for (const [key, pts] of bucket) {
        const [sample, change] = key.split('|');
        const isHighlighted = highlightSet.has(change);
        const colour = isHighlighted ? highlightColours.get(change) : MUTED_COLOUR;
        traces.push({
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: pts.map((p) => p.position),
          y: pts.map((p) => p.frequency),
          xaxis: xaxisKey,
          yaxis: yaxisKey,
          name: change,
          legendgroup: change,
          showlegend: panelIdx === 0,
          line: {
            color: colour,
            width: isHighlighted ? 2 : 1,
            dash: isHighlighted ? 'solid' : 'dot',
          },
          opacity: isHighlighted ? 1 : 0.5,
          hovertemplate: `<b>${sample}</b> ${change}<br>position: %{x}<br>frequency: %{y:.3f}<extra></extra>`,
        });
      }

      annotations.push({
        x: (domainStart + domainEnd) / 2,
        y: 1,
        xref: 'paper' as const,
        yref: 'paper' as const,
        xanchor: 'center' as const,
        yanchor: 'bottom' as const,
        text: panel,
        showarrow: false,
        font: { size: 11 },
      });

      axes[`xaxis${panelIdx === 0 ? '' : panelIdx + 1}`] = {
        title: { text: 'Position from read end' },
        domain: [domainStart, domainEnd],
        anchor: yaxisKey,
      };
      axes[`yaxis${panelIdx === 0 ? '' : panelIdx + 1}`] = {
        title: panelIdx === 0 ? { text: 'Frequency' } : undefined,
        anchor: xaxisKey,
        matches: panelIdx === 0 ? undefined : 'y',
        rangemode: 'tozero' as const,
      };
    });

    return {
      data: traces,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        ...axes,
        annotations,
        margin: { l: 56, r: 12, t: 24, b: 44 },
        autosize: true,
      },
    };
  }, [rows, config, ends, maxPosition, highlight, palette, isDark, theme]);

  const controls = (
    <Stack gap="xs">
      <Select
        size="xs"
        label="Ends"
        value={ends}
        onChange={(v) => setEnds((v as Ends) || 'both')}
        data={[
          { value: 'both', label: '5p and 3p' },
          { value: '5p', label: "5' only" },
          { value: '3p', label: "3' only" },
        ]}
        allowDeselect={false}
      />
      <NumberInput
        size="xs"
        label="Max position"
        value={maxPosition}
        onChange={(v) => setMaxPosition(Math.max(1, Number(v) || DEFAULT_MAX_POSITION))}
        min={1}
        max={200}
      />
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Highlight
        </Text>
        <MultiSelect
          size="xs"
          value={highlight}
          onChange={setHighlight}
          data={SUBSTITUTION_OPTIONS}
          placeholder="Substitutions to highlight"
        />
      </Stack>
    </Stack>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Damage profile'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? <DamageProfilePlot figure={figure} isDark={isDark} theme={theme} /> : null}
    </AdvancedVizFrame>
  );
};

export default DamageProfileRenderer;
