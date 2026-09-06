import React, { useEffect, useMemo, useState } from 'react';
import {
  Group,
  NumberInput,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import AdvancedVizPlot from './AdvancedVizPlot';

import {
  AdvancedVizKind,
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { brandColorway, stableColorMap, TAB10_PALETTE } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `FusionStructureConfig` in
 *  depictio/models/components/advanced_viz/configs.py. Every key read off
 *  `config` below must exist there — `tests/models/test_advanced_viz_config_alignment.py`
 *  reads this source and fails CI otherwise. */
interface FusionStructureConfig {
  fusion_id_col: string;
  partner_col: string;
  feature_col: string;
  start_col: string;
  end_col: string;
  breakpoint_col?: string | null;
  retained_col?: string | null;
  colour_by_col?: string | null;
  top_n?: number;
  show_breakpoint?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: FusionStructureConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/** Sent so the server applies this kind's reduction policy: `"none"`, see
 *  models/components/advanced_viz/sampling.py. */
const VIZ_KIND: AdvancedVizKind = 'fusion_structure';

/** A domain bar is `retained` when essentially all of it survives the fusion.
 *  Arriba reports whole percentages, so anything at or above this is "100%". */
const FULLY_RETAINED = 0.999;

/** Label longer than this is truncated in the bar; the full name stays in the
 *  hover. Domain names run to 60+ characters
 *  ("Transforming_acidic_coiled-coil-containing_protein_(TACC)__C-terminal"). */
const MAX_LABEL_CHARS = 26;

/** Paper-space band the facets share. The strip below it holds the legend. */
const BAND_BOTTOM = 0.12;
/** Reserved above each facet for its fusion-id title. */
const TITLE_BAND = 0.03;

interface DomainBar {
  feature: string;
  start: number;
  end: number;
  /** 0..1. Always 1 when no `retained_col` is bound. */
  retained: number;
  category: string;
}

interface Lane {
  partner: string;
  /** First-appearance index, the tie-break when two lanes share a min start. */
  seen: number;
  bars: DomainBar[];
}

interface Facet {
  id: string;
  lanes: Lane[];
  breakpoint: number | null;
  xMin: number;
  xMax: number;
}

const num = (value: unknown, fallback: number): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const truncate = (label: string): string =>
  label.length > MAX_LABEL_CHARS ? `${label.slice(0, MAX_LABEL_CHARS - 1)}…` : label;

/**
 * A gene fusion drawn as its two partners, one horizontal lane each, with a bar
 * per annotated protein domain positioned by `start`/`end` along that partner.
 * The bar's full extent is the domain's footprint; the solid part is the
 * fraction that survives the fusion (`retained_col`), so a partially retained
 * domain reads as a half-filled slot rather than as a colour the eye has to
 * decode. `config.top_n` fusions are faceted, one small multiple each.
 *
 * The kind declares no selection, so this renderer emits no `onFilterChange`.
 */
const FusionStructureRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as FusionStructureConfig;

  const [topN, setTopN] = usePersistedVizControl(metadata, 'top_n', 6);
  const [showBreakpoint, setShowBreakpoint] = usePersistedVizControl(metadata, 'show_breakpoint', true);
  // Presentation-only, and no field on FusionStructureConfig to persist them
  // into. Kept as plain state rather than inventing config keys the model would
  // reject (`extra="forbid"`) — see the report in dev/advanced_viz_kinds/.
  const [barHeight, setBarHeight] = useState<number>(0.45);
  const [showLabels, setShowLabels] = useState<boolean>(true);
  const [showAxis, setShowAxis] = useState<boolean>(false);

  const brandPalette = brandColorway(theme);

  const bound = Boolean(
    config.fusion_id_col &&
      config.partner_col &&
      config.feature_col &&
      config.start_col &&
      config.end_col,
  );

  const requiredCols = useMemo(() => {
    const cols = [
      config.fusion_id_col,
      config.partner_col,
      config.feature_col,
      config.start_col,
      config.end_col,
      ...(config.breakpoint_col ? [config.breakpoint_col] : []),
      ...(config.retained_col ? [config.retained_col] : []),
      ...(config.colour_by_col ? [config.colour_by_col] : []),
    ].filter(Boolean) as string[];
    // `colour_by_col` is often one of the bound roles; the endpoint projects a
    // column set, so ask for each name once.
    return Array.from(new Set(cols));
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !bound) {
      setError('Fusion structure: missing data binding');
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
  }, [metadata.wf_id, metadata.dc_id, bound, JSON.stringify(requiredCols), JSON.stringify(filters), refreshTick]);

  /** Group the long frame into one facet per fusion, one lane per partner.
   *
   *  Lanes are ordered by their smallest `start`, which is what puts the 5'
   *  partner first when the recipe lays the two partners end to end on one
   *  axis. Data that is partner-relative instead (every partner starting at 0)
   *  falls back to first-appearance order, so both conventions render. */
  const { facets, categories, hasRetained } = useMemo(() => {
    const empty = { facets: [] as Facet[], categories: [] as string[], hasRetained: false };
    if (!rows) return empty;

    const fusionIds = (rows[config.fusion_id_col] || []) as unknown[];
    const partners = (rows[config.partner_col] || []) as unknown[];
    const features = (rows[config.feature_col] || []) as unknown[];
    const starts = (rows[config.start_col] || []) as unknown[];
    const ends = (rows[config.end_col] || []) as unknown[];
    const breakpoints = config.breakpoint_col
      ? ((rows[config.breakpoint_col] || []) as unknown[])
      : null;
    const retainedRaw = config.retained_col
      ? ((rows[config.retained_col] || []) as unknown[])
      : null;
    const colourValues = config.colour_by_col
      ? ((rows[config.colour_by_col] || []) as unknown[])
      : null;

    // The role is documented as a fraction, but a pipeline that publishes whole
    // percentages is the likelier mistake to hit than a genuine >150% value.
    // Decide once over the whole frame so every bar uses the same scale.
    let retainedScale = 1;
    if (retainedRaw) {
      let maxRetained = 0;
      for (const value of retainedRaw) {
        const n = Number(value);
        if (Number.isFinite(n) && n > maxRetained) maxRetained = n;
      }
      if (maxRetained > 1.5) retainedScale = 0.01;
    }

    const byFusion = new Map<string, Facet>();
    const lanesByFusion = new Map<string, Map<string, Lane>>();
    const cats = new Set<string>();

    for (let i = 0; i < fusionIds.length; i++) {
      const fusionId = String(fusionIds[i] ?? '');
      if (!fusionId) continue;
      const partner = String(partners[i] ?? '');
      const start = num(starts[i], NaN);
      const end = num(ends[i], NaN);
      if (!Number.isFinite(start) || !Number.isFinite(end)) continue;

      const retained = retainedRaw
        ? Math.max(0, Math.min(1, num(retainedRaw[i], 1) * retainedScale))
        : 1;
      const category = colourValues
        ? String(colourValues[i] ?? '')
        : retainedRaw
          ? retained >= FULLY_RETAINED
            ? 'Retained'
            : retained > 0
              ? 'Partially retained'
              : 'Not retained'
          : 'Domain';
      cats.add(category);

      let facet = byFusion.get(fusionId);
      if (!facet) {
        facet = {
          id: fusionId,
          lanes: [],
          breakpoint: null,
          xMin: Number.POSITIVE_INFINITY,
          xMax: Number.NEGATIVE_INFINITY,
        };
        byFusion.set(fusionId, facet);
        lanesByFusion.set(fusionId, new Map());
      }
      const lanes = lanesByFusion.get(fusionId)!;
      let lane = lanes.get(partner);
      if (!lane) {
        lane = { partner, seen: lanes.size, bars: [] };
        lanes.set(partner, lane);
        facet.lanes.push(lane);
      }
      lane.bars.push({
        feature: String(features[i] ?? ''),
        start: Math.min(start, end),
        end: Math.max(start, end),
        retained,
        category,
      });
      facet.xMin = Math.min(facet.xMin, start, end);
      facet.xMax = Math.max(facet.xMax, start, end);
      if (breakpoints && facet.breakpoint === null) {
        const bp = Number(breakpoints[i]);
        if (Number.isFinite(bp)) {
          facet.breakpoint = bp;
          facet.xMin = Math.min(facet.xMin, bp);
          facet.xMax = Math.max(facet.xMax, bp);
        }
      }
    }

    const ordered = Array.from(byFusion.values());
    for (const facet of ordered) {
      facet.lanes.sort((a, b) => {
        const aMin = Math.min(...a.bars.map((bar) => bar.start));
        const bMin = Math.min(...b.bars.map((bar) => bar.start));
        return aMin === bMin ? a.seen - b.seen : aMin - bMin;
      });
      // A single zero-width feature would otherwise give the facet an empty range.
      if (!(facet.xMax > facet.xMin)) facet.xMax = facet.xMin + 1;
    }

    return {
      facets: ordered,
      categories: Array.from(cats),
      hasRetained: Boolean(retainedRaw),
    };
  }, [rows, config]);

  const shownFacets = useMemo(
    () => facets.slice(0, Math.max(1, topN)),
    [facets, topN],
  );

  const figure = useMemo(() => {
    if (shownFacets.length === 0) return null;
    const { textColor } = plotlyThemeColors(isDark, theme);
    const paletteArr = (brandPalette ?? TAB10_PALETTE) as readonly string[];
    const colourFor = stableColorMap(categories, paletteArr);
    // The unfilled part of a domain slot: a neutral track, so the category
    // colour is only ever spent on the part of the domain that survives.
    const trackColour = isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.06)';
    const baselineColour = isDark ? 'rgba(255,255,255,0.28)' : 'rgba(0,0,0,0.22)';
    const breakpointColour = isDark ? theme.colors.red[4] : theme.colors.red[7];

    const data: any[] = [];
    const shapes: any[] = [];
    const annotations: any[] = [];
    const axes: Record<string, any> = {};
    const legendSeen = new Set<string>();

    const nFacets = shownFacets.length;
    const bandHeight = (1 - BAND_BOTTOM) / nFacets;
    const gap = showAxis ? 0.045 : 0.028;

    shownFacets.forEach((facet, f) => {
      const suffix = f === 0 ? '' : String(f + 1);
      const xref = `x${suffix}`;
      const yref = `y${suffix}`;
      const top = 1 - f * bandHeight - TITLE_BAND;
      const bottom = Math.max(
        0,
        Math.min(1 - (f + 1) * bandHeight + gap, top - 0.012),
      );

      const pad = (facet.xMax - facet.xMin) * 0.02;
      const nLanes = facet.lanes.length;

      axes[`xaxis${suffix}`] = {
        ...plotlyAxisOverrides(isDark, theme),
        anchor: yref,
        domain: [0, 1],
        range: [facet.xMin - pad, facet.xMax + pad],
        showgrid: false,
        zeroline: false,
        showticklabels: showAxis,
        tickfont: { size: 8, color: textColor },
        title:
          showAxis && f === nFacets - 1
            ? { text: `${config.start_col} → ${config.end_col}`, font: { size: 10 } }
            : { text: '' },
      };
      axes[`yaxis${suffix}`] = {
        ...plotlyAxisOverrides(isDark, theme),
        anchor: xref,
        domain: [bottom, top],
        // Reversed so the first lane (the 5' partner) sits on top, the way a
        // fusion is written.
        range: [nLanes - 0.5, -0.5],
        tickmode: 'array' as const,
        tickvals: facet.lanes.map((_, index) => index),
        ticktext: facet.lanes.map((lane) => lane.partner),
        tickfont: { size: 10, color: textColor },
        showgrid: false,
        zeroline: false,
        automargin: true,
      };

      annotations.push({
        xref: 'paper' as const,
        yref: 'paper' as const,
        x: 0,
        xanchor: 'left' as const,
        y: Math.min(1, top + 0.004),
        yanchor: 'bottom' as const,
        text: `<b>${facet.id}</b>`,
        showarrow: false,
        font: { size: 11, color: textColor },
      });

      // The protein backbone each partner's domains sit on.
      facet.lanes.forEach((_, index) => {
        shapes.push({
          type: 'line' as const,
          xref,
          yref,
          x0: facet.xMin,
          x1: facet.xMax,
          y0: index,
          y1: index,
          line: { color: baselineColour, width: 1 },
          layer: 'below' as const,
        });
      });

      if (showBreakpoint && config.breakpoint_col && facet.breakpoint !== null) {
        shapes.push({
          type: 'line' as const,
          xref,
          yref,
          x0: facet.breakpoint,
          x1: facet.breakpoint,
          y0: -0.5,
          y1: nLanes - 0.5,
          line: { color: breakpointColour, width: 1.4, dash: 'dot' as const },
        });
        if (f === 0) {
          annotations.push({
            xref,
            yref: 'paper' as const,
            x: facet.breakpoint,
            xanchor: 'left' as const,
            y: Math.min(1, top + 0.004),
            yanchor: 'bottom' as const,
            text: 'breakpoint',
            showarrow: false,
            font: { size: 9, color: breakpointColour },
          });
        }
      }

      // One extent trace for the whole facet: the domain's footprint, the
      // labels and the hover. The retained overlays below carry the colour and
      // the legend but skip hover, so one bar never reports itself twice.
      const extentBase: number[] = [];
      const extentLen: number[] = [];
      const extentY: number[] = [];
      const extentLine: string[] = [];
      const extentText: string[] = [];
      const extentCustom: (string | number)[][] = [];
      facet.lanes.forEach((lane, laneIndex) => {
        lane.bars.forEach((bar) => {
          extentBase.push(bar.start);
          extentLen.push(Math.max(bar.end - bar.start, 0));
          extentY.push(laneIndex);
          extentLine.push(colourFor.get(bar.category) ?? paletteArr[0]);
          extentText.push(showLabels ? truncate(bar.feature) : '');
          extentCustom.push([
            lane.partner,
            bar.feature,
            `${(bar.retained * 100).toFixed(0)}%`,
            bar.start,
            bar.end,
            bar.category,
          ]);
        });
      });

      data.push({
        type: 'bar' as const,
        orientation: 'h' as const,
        base: extentBase,
        x: extentLen,
        y: extentY,
        width: barHeight,
        xaxis: xref,
        yaxis: yref,
        marker: { color: trackColour, line: { color: extentLine, width: 1 } },
        text: extentText,
        textposition: 'auto' as const,
        constraintext: 'none' as const,
        insidetextanchor: 'middle' as const,
        textfont: { size: 9, color: textColor },
        customdata: extentCustom,
        hovertemplate:
          `<b>%{customdata[1]}</b><br>${config.partner_col}: %{customdata[0]}` +
          `<br>${config.start_col}–${config.end_col}: %{customdata[3]}–%{customdata[4]}` +
          (hasRetained ? `<br>${config.retained_col}: %{customdata[2]}` : '') +
          (config.colour_by_col ? `<br>${config.colour_by_col}: %{customdata[5]}` : '') +
          `<extra></extra>`,
        showlegend: false,
      });

      // The retained slice of each domain, one trace per category so the legend
      // reads as the colour key it is.
      for (const category of categories) {
        const base: number[] = [];
        const length: number[] = [];
        const ys: number[] = [];
        facet.lanes.forEach((lane, laneIndex) => {
          lane.bars.forEach((bar) => {
            if (bar.category !== category) return;
            const width = (bar.end - bar.start) * bar.retained;
            if (!(width > 0)) return;
            base.push(bar.start);
            length.push(width);
            ys.push(laneIndex);
          });
        });
        if (base.length === 0) continue;
        const showInLegend = !legendSeen.has(category);
        legendSeen.add(category);
        data.push({
          type: 'bar' as const,
          orientation: 'h' as const,
          name: category,
          legendgroup: category,
          showlegend: showInLegend,
          base,
          x: length,
          y: ys,
          width: barHeight,
          xaxis: xref,
          yaxis: yref,
          marker: { color: colourFor.get(category) ?? paletteArr[0], line: { width: 0 } },
          hoverinfo: 'skip' as const,
        });
      }
    });

    return {
      data,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        barmode: 'overlay' as const,
        bargap: 0,
        margin: { l: 110, r: 18, t: 24, b: showAxis ? 40 : 14 },
        hovermode: 'closest' as const,
        showlegend: true,
        legend: {
          orientation: 'h' as const,
          x: 0,
          xanchor: 'left' as const,
          y: BAND_BOTTOM - 0.03,
          yanchor: 'top' as const,
          font: { size: 10, color: textColor },
          bgcolor: 'rgba(0,0,0,0)',
        },
        ...axes,
        shapes,
        annotations,
        autosize: true,
      },
    };
  }, [
    shownFacets,
    categories,
    hasRetained,
    config,
    isDark,
    theme,
    brandPalette,
    barHeight,
    showLabels,
    showAxis,
    showBreakpoint,
  ]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Group gap="xs" grow>
          <NumberInput
            size="xs"
            label="Fusions"
            description={facets.length ? `of ${facets.length}` : undefined}
            value={topN}
            onChange={(v) => setTopN(Math.max(1, Math.min(20, Number(v) || 1)))}
            min={1}
            max={20}
          />
          <NumberInput
            size="xs"
            label="Bar height"
            value={barHeight}
            onChange={(v) => setBarHeight(Math.max(0.1, Math.min(0.9, Number(v) || 0.45)))}
            min={0.1}
            max={0.9}
            step={0.05}
            decimalScale={2}
          />
        </Group>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Breakpoint
          </Text>
          <Switch
            size="xs"
            checked={showBreakpoint}
            onChange={(e) => setShowBreakpoint(e.currentTarget.checked)}
            disabled={!config.breakpoint_col}
            label={config.breakpoint_col ? 'Mark the breakpoint' : 'No breakpoint column bound'}
          />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Labels
          </Text>
          <Switch
            size="xs"
            checked={showLabels}
            onChange={(e) => setShowLabels(e.currentTarget.checked)}
            label="Name each domain"
          />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Position axis
          </Text>
          <Switch
            size="xs"
            checked={showAxis}
            onChange={(e) => setShowAxis(e.currentTarget.checked)}
            label="Show coordinates"
          />
        </Stack>
        {hasRetained ? (
          <Text size="xs" c="dimmed">
            The filled part of each bar is the fraction of the domain the fusion keeps.
          </Text>
        ) : null}
      </Stack>
    ),
    [
      facets.length,
      topN,
      barHeight,
      showBreakpoint,
      showLabels,
      showAxis,
      hasRetained,
      config.breakpoint_col,
    ],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Fusion structure'}
      subtitle={(metadata as { description?: string; subtitle?: string }).description}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={
        rows && facets.length === 0 ? 'No fusion has a domain to draw' : undefined
      }
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <AdvancedVizPlot
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

export default FusionStructureRenderer;
