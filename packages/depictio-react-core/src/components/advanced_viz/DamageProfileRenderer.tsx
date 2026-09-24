import React, { useEffect, useMemo, useState } from 'react';
import { Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';
import {
  VizFullRow,
  VizMultiSelect,
  VizNumberInput,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyThemeColors, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

type Ends = 'both' | '5p' | '3p';
type FacetBy = 'none' | 'length_bin';

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
  facet_by?: FacetBy;
  length_bin_col?: string;
  max_facets?: number;
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
const DEFAULT_LENGTH_BIN_COL = 'length_bin';
const DEFAULT_MAX_FACETS = 6;
// The lane key an unfacetted figure uses, so one nested loop below builds both
// the single-panel layout and the facetted one.
const SINGLE_LANE = '';

/** Read-length bins sort by their leading number, so `9-19` precedes `30-39`
 *  and `100+` lands last rather than between `10-19` and `20-29`. A label with
 *  no leading number sorts to the end, alphabetically among its peers. */
function lengthBinSortKey(label: string): number {
  const n = Number.parseFloat(label.replace(/^[^0-9.-]*/, ''));
  return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
}
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
  const [facetBy, setFacetBy] = usePersistedVizControl<FacetBy>(
    metadata,
    'facet_by',
    config.facet_by ?? 'none',
  );

  const lengthBinCol = config.length_bin_col || DEFAULT_LENGTH_BIN_COL;
  const maxFacets = Math.max(1, config.max_facets ?? DEFAULT_MAX_FACETS);

  const requiredCols = useMemo(() => {
    const cols = [
      config.sample_col,
      config.end_col,
      config.position_col,
      config.base_change_col,
      config.frequency_col,
    ].filter(Boolean) as string[];
    // Only fetched while the lanes are actually asked for. A collection that
    // has no such column simply comes back without it: the data endpoint
    // projects against the Delta schema and drops what it cannot find.
    if (facetBy === 'length_bin' && !cols.includes(lengthBinCol)) cols.push(lengthBinCol);
    return cols;
  }, [
    config.sample_col,
    config.end_col,
    config.position_col,
    config.base_change_col,
    config.frequency_col,
    facetBy,
    lengthBinCol,
  ]);

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

  // The lanes are inert unless the bound collection actually carries the
  // column: the endpoint projects against the Delta schema and drops what it
  // cannot find, so a missing column shows up as a key that never came back.
  // The tile then draws exactly what it drew before and the controls say why.
  const laneColumnMissing = Boolean(rows) && facetBy === 'length_bin' && !(lengthBinCol in rows!);
  const faceting = facetBy === 'length_bin' && !laneColumnMissing;

  const { figure, laneCount, lanesShown } = useMemo(() => {
    const empty = { figure: null, laneCount: 0, lanesShown: 0 };
    if (!rows) return empty;
    const samples = (rows[config.sample_col] || []) as unknown[];
    const endVals = (rows[config.end_col] || []) as unknown[];
    const positions = (rows[config.position_col] || []) as unknown[];
    const changes = (rows[config.base_change_col] || []) as unknown[];
    const freqs = (rows[config.frequency_col] || []) as unknown[];
    const laneVals = faceting ? ((rows[lengthBinCol] || []) as unknown[]) : null;

    const panels: Ends[] = ends === 'both' ? ['5p', '3p'] : [ends];

    type Pt = { position: number; frequency: number };
    // lane -> panel -> "sample|base_change" -> points. Without faceting there
    // is exactly one lane, and the layout below collapses to today's figure.
    const byLane = new Map<string, Map<Ends, Map<string, Pt[]>>>();
    const laneFor = (lane: string) => {
      let byPanel = byLane.get(lane);
      if (!byPanel) {
        byPanel = new Map();
        for (const p of panels) byPanel.set(p, new Map());
        byLane.set(lane, byPanel);
      }
      return byPanel;
    };
    if (!faceting) laneFor(SINGLE_LANE);

    const n = Math.min(endVals.length, positions.length, changes.length, freqs.length);
    for (let i = 0; i < n; i++) {
      const endRaw = String(endVals[i] ?? '');
      const panel: Ends | null = endRaw === '5p' || endRaw === '3p' ? (endRaw as Ends) : null;
      if (!panel || !panels.includes(panel)) continue;
      const position = num(positions[i]);
      const frequency = num(freqs[i]);
      if (position === null || frequency === null || position > maxPosition) continue;
      const sample = samples.length ? String(samples[i] ?? 'sample') : 'sample';
      const change = String(changes[i] ?? 'other');
      const key = `${sample}|${change}`;
      const bucket = laneFor(laneVals ? String(laneVals[i] ?? '') : SINGLE_LANE).get(panel)!;
      let pts = bucket.get(key);
      if (!pts) {
        pts = [];
        bucket.set(key, pts);
      }
      pts.push({ position, frequency });
    }
    for (const byPanel of byLane.values()) {
      for (const bucket of byPanel.values()) {
        for (const pts of bucket.values()) pts.sort((a, b) => a.position - b.position);
      }
    }

    const allLanes = faceting
      ? Array.from(byLane.keys()).sort(
          (a, b) => lengthBinSortKey(a) - lengthBinSortKey(b) || a.localeCompare(b),
        )
      : [SINGLE_LANE];
    const lanes = allLanes.slice(0, faceting ? maxFacets : 1);

    const highlightSet = new Set(highlight.length ? highlight : DEFAULT_HIGHLIGHT);
    const highlightNames = Array.from(highlightSet).sort();
    const highlightColours = stableColorMap(highlightNames, palette, null);
    const { textColor } = plotlyThemeColors(isDark, theme);

    const colWidth = 1 / panels.length;
    const gap = panels.length > 1 ? 0.06 : 0;
    // Lanes are stacked top to bottom in bin order, so the eye reads the
    // read-length axis the same way it reads the label column of a table.
    const vGap = lanes.length > 1 ? 0.08 : 0;
    const laneHeight = (1 - vGap * (lanes.length - 1)) / lanes.length;
    // "Frequency" once rather than once per lane: repeated down the left edge
    // it reads as six different axes instead of one shared scale.
    const titledLane = Math.floor((lanes.length - 1) / 2);
    const traces: any[] = [];
    const annotations: any[] = [];
    const axes: Record<string, unknown> = {};

    lanes.forEach((lane, laneIdx) => {
      const laneTop = 1 - laneIdx * (laneHeight + vGap);
      const laneBottom = laneTop - laneHeight;
      const isBottomLane = laneIdx === lanes.length - 1;

      panels.forEach((panel, panelIdx) => {
        const axisIdx = laneIdx * panels.length + panelIdx;
        const suffix = axisIdx === 0 ? '' : String(axisIdx + 1);
        const xaxisKey = axisIdx === 0 ? 'x' : `x${axisIdx + 1}`;
        const yaxisKey = axisIdx === 0 ? 'y' : `y${axisIdx + 1}`;
        const domainStart = panelIdx * colWidth + (panelIdx > 0 ? gap / 2 : 0);
        const domainEnd = (panelIdx + 1) * colWidth - (panelIdx < panels.length - 1 ? gap / 2 : 0);

        const bucket = byLane.get(lane)!.get(panel)!;
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
            showlegend: axisIdx === 0,
            line: {
              color: colour,
              width: isHighlighted ? 2 : 1,
              dash: isHighlighted ? 'solid' : 'dot',
            },
            opacity: isHighlighted ? 1 : 0.5,
            hovertemplate: lane
              ? `<b>${sample}</b> ${change}<br>${lane}<br>position: %{x}<br>frequency: %{y:.3f}<extra></extra>`
              : `<b>${sample}</b> ${change}<br>position: %{x}<br>frequency: %{y:.3f}<extra></extra>`,
          });
        }

        if (laneIdx === 0) {
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
        }

        axes[`xaxis${suffix}`] = {
          // The position axis is only labelled under the bottom lane: every
          // lane shares it, and six copies of the same title is noise.
          title: isBottomLane ? { text: 'Position from read end' } : undefined,
          domain: [domainStart, domainEnd],
          anchor: yaxisKey,
          showticklabels: isBottomLane,
        };
        axes[`yaxis${suffix}`] = {
          title: panelIdx === 0 && laneIdx === titledLane ? { text: 'Frequency' } : undefined,
          anchor: xaxisKey,
          domain: [laneBottom, laneTop],
          // Every lane on one frequency scale: the authenticity signal is the
          // interaction (short reads more deaminated than long ones), and it
          // only reads as one when the lanes cannot rescale independently.
          matches: axisIdx === 0 ? undefined : 'y',
          rangemode: 'tozero' as const,
        };
      });

      if (lane) {
        annotations.push({
          x: 0,
          y: laneTop,
          xref: 'paper' as const,
          yref: 'paper' as const,
          xanchor: 'left' as const,
          yanchor: 'bottom' as const,
          yshift: 2,
          text: lane,
          showarrow: false,
          font: { size: 10, color: textColor },
        });
      }
    });

    if (faceting && allLanes.length > lanes.length) {
      annotations.push({
        x: 1,
        y: 1,
        xref: 'paper' as const,
        yref: 'paper' as const,
        xanchor: 'right' as const,
        yanchor: 'bottom' as const,
        text: `showing ${lanes.length} of ${allLanes.length} length bins`,
        showarrow: false,
        font: { size: 10, color: textColor },
      });
    }

    return {
      figure: {
        data: traces,
        layout: {
          ...plotlyThemeFragment(isDark, theme),
          ...axes,
          annotations,
          margin: { l: 56, r: 12, t: faceting ? 28 : 24, b: 44 },
          autosize: true,
        },
      },
      laneCount: allLanes.length,
      lanesShown: lanes.length,
    };
  }, [
    rows,
    config,
    ends,
    maxPosition,
    highlight,
    faceting,
    lengthBinCol,
    maxFacets,
    palette,
    isDark,
    theme,
  ]);

  // Encoding tier: which read ends, which substitutions stand out and whether
  // read-length bins get their own lane decide what the profile shows. The
  // x extent and the notes about missing lanes are secondary.
  const primaryControls = (
    <>
      <VizSelect
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
      <VizMultiSelect
        label="Highlight"
        value={highlight}
        onChange={setHighlight}
        data={SUBSTITUTION_OPTIONS}
        placeholder="Substitutions to highlight"
      />
      <VizSwitch
        checked={facetBy === 'length_bin'}
        onChange={(e) => setFacetBy(e.currentTarget.checked ? 'length_bin' : 'none')}
        label="One lane per read-length bin"
      />
    </>
  );

  const controls = (
    <>
      <VizNumberInput
        label="Max position"
        value={maxPosition}
        onChange={(v) => setMaxPosition(Math.max(1, Number(v) || DEFAULT_MAX_POSITION))}
        min={1}
        max={200}
      />
      {laneColumnMissing ? (
        <VizFullRow>
          <Text size="xs" c="dimmed">
            {`This data collection has no "${lengthBinCol}" column, so the profile stays on one lane.`}
          </Text>
        </VizFullRow>
      ) : null}
      {faceting && laneCount > lanesShown ? (
        <VizFullRow>
          <Text size="xs" c="dimmed">
            {`Showing ${lanesShown} of ${laneCount} bins (max_facets).`}
          </Text>
        </VizFullRow>
      ) : null}
    </>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Damage profile'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
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
