import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
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
  AdvancedVizKind,
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/**
 * The metagene heatmap that pairs with a `profile` curve: rows are regions,
 * columns are position offsets around a reference point (a TSS, a peak summit),
 * cells are the signal at that offset.
 *
 * Two properties drive every decision below:
 *
 * 1. The column order is POSITIONAL. Positions are sorted numerically and never
 *    clustered or reordered — a metagene column means "150 bp downstream of the
 *    reference", and permuting it destroys the only thing the plot says.
 * 2. A real deepTools matrix runs to 10^5 regions. Rows are therefore *binned*
 *    down to `max_rows` by averaging within consecutive bins of the sorted row
 *    order, never by taking a head: a head silently throws away every weak
 *    region, which is exactly the half a metagene is drawn to compare.
 */
type SortBy = 'signal' | 'none';

interface SignalMatrixConfig {
  region_id_col: string;
  position_col: string;
  value_col: string;
  group_col?: string | null;
  reference_position?: number;
  reference_label?: string | null;
  sort_by?: SortBy;
  max_rows?: number;
  colour_scale?: ColourScale;
  show_profile?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SignalMatrixConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/** Panels a `group_col` may open. Beyond this the bands are too short to read,
 *  so the extra groups are dropped and the count is surfaced in the controls. */
const MAX_PANELS = 6;
/** Above this many drawn rows the per-row tick labels are dropped: 2000 region
 *  ids in a 300 px band is a grey smear, not a label. */
const ROW_LABEL_LIMIT = 40;
/** Hard ceiling on the row-label margin, as a fraction of the tile's width.
 *  See TEMPLATE_BOTTLENECKS.md §14: Plotly sizes a label margin from the
 *  longest label and nothing clamps it against the tile, which once left a
 *  complex_heatmap with a 346 px margin in a 517 px tile and a NEGATIVE plot
 *  area — colour bar drawn, not one cell. Hence the clamp plus explicit
 *  `automargin: false` on every row axis, and truncation of the tick text to
 *  whatever the clamped margin actually affords (the full id stays in hover). */
const LABEL_MARGIN_FRACTION = 0.22;
/** Rough width of one tick character at the 9 px tick font used here. */
const LABEL_CHAR_PX = 6;
const MIN_LEFT_MARGIN = 44;
/** Paper-fraction height of the mean-profile panel, and the gap under it. */
const PROFILE_HEIGHT = 0.2;
const PANEL_GAP = 0.03;
/** Cell budget for the colour-range percentile sample. */
const RANGE_SAMPLE = 20000;

// Sent so the server applies this kind's reduction policy:
// `KIND_SAMPLING_POLICY` carries `signal_matrix: "none"`, because a sampled
// matrix loses whole regions rather than resolution.
const SIGNAL_MATRIX_VIZ_KIND: AdvancedVizKind = 'signal_matrix';

/** One drawn row: either a single region, or the average of a bin of them. */
interface DrawnRow {
  label: string;
  values: (number | null)[];
  regions: number;
}

/** One region's mean signal at every position (NaN where the region has no
 *  value for that offset), plus its total — the `signal` sort key. Typed
 *  rather than `(number | null)[]` because there is one of these per region and
 *  a real matrix has 10^5 of them. */
interface RegionRow {
  id: string;
  values: Float64Array;
  total: number;
}

interface Panel {
  key: string;
  rows: DrawnRow[];
  profile: (number | null)[];
  regions: number;
}

/**
 * Bin `regions` down to at most `maxRows` drawn rows by averaging within
 * consecutive bins of the incoming order.
 *
 * Averaging within a *signal-sorted* order is what makes the reduction
 * faithful: neighbours in that order carry near-identical profiles, so the bin
 * mean is the shape both of them had. Nulls are skipped per position rather
 * than counted as zero, so a region missing one offset does not drag the bin's
 * value toward the floor.
 */
function binRows(regions: RegionRow[], maxRows: number): DrawnRow[] {
  const nPos = regions.length > 0 ? regions[0].values.length : 0;
  const budget = Math.max(1, Math.floor(maxRows));
  const size = Math.max(1, Math.ceil(regions.length / budget));
  // Plotly wants nulls for the gaps, so the typed rows are widened here — on
  // the drawn rows only, which is at most `max_rows` of them.
  const widen = (values: Float64Array): (number | null)[] =>
    Array.from(values, (v) => (Number.isNaN(v) ? null : v));
  if (size === 1) {
    return regions.map((r) => ({ label: r.id, values: widen(r.values), regions: 1 }));
  }
  const out: DrawnRow[] = [];
  for (let start = 0; start < regions.length; start += size) {
    const bin = regions.slice(start, start + size);
    const values: (number | null)[] = new Array(nPos).fill(null);
    for (let p = 0; p < nPos; p++) {
      let sum = 0;
      let hits = 0;
      for (const region of bin) {
        const v = region.values[p];
        if (!Number.isNaN(v)) {
          sum += v;
          hits += 1;
        }
      }
      values[p] = hits > 0 ? sum / hits : null;
    }
    const first = bin[0].id;
    const last = bin[bin.length - 1].id;
    out.push({
      label: bin.length === 1 ? first : `${first} … ${last} (${bin.length})`,
      values,
      regions: bin.length,
    });
  }
  return out;
}

/** 2nd–98th percentile of `values`, so one saturated region does not flatten
 *  the whole matrix to the low end of the ramp. Falls back to the full range,
 *  then to a unit range for a constant matrix. */
function robustRange(values: number[]): [number, number] {
  if (values.length === 0) return [0, 1];
  const sorted = [...values].sort((a, b) => a - b);
  const lo = sorted[Math.floor((sorted.length - 1) * 0.02)];
  const hi = sorted[Math.ceil((sorted.length - 1) * 0.98)];
  if (hi > lo) return [lo, hi];
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  return max > min ? [min, max] : [min, min + 1];
}

/** Plotly axis identifiers: the first one is `yaxis` / `y`, never `yaxis1`. */
const axisKey = (i: number) => (i === 0 ? 'yaxis' : `yaxis${i + 1}`);
const axisRef = (i: number) => (i === 0 ? 'y' : `y${i + 1}`);

const truncate = (label: string, chars: number) =>
  label.length <= chars ? label : `${label.slice(0, Math.max(1, chars - 1))}…`;

const SignalMatrixRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as SignalMatrixConfig;

  const regionCol = config.region_id_col || 'region_id';
  const positionCol = config.position_col || 'position';
  const valueCol = config.value_col || 'value';
  const groupCol = config.group_col || null;
  // Read out as primitives so the memos below depend on values rather than on
  // the identity of a config object that is re-created whenever it is absent.
  const referencePosition = config.reference_position ?? 0;
  const referenceLabel = config.reference_label || null;

  // Tier-2 controls. All four are pure re-shapes of the frame already in hand,
  // so none of them refetches.
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(metadata, 'colour_scale', 'Viridis');
  const [maxRows, setMaxRows] = usePersistedVizControl<number>(metadata, 'max_rows', 2000);
  const [sortBy, setSortBy] = usePersistedVizControl<SortBy>(metadata, 'sort_by', 'signal');
  const [showProfile, setShowProfile] = usePersistedVizControl<boolean>(metadata, 'show_profile', true);

  const requiredCols = useMemo(
    () => [regionCol, positionCol, valueCol, ...(groupCol ? [groupCol] : [])],
    [regionCol, positionCol, valueCol, groupCol],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // This kind is served whole (sampling policy "none") because the renderer
  // aggregates its rows; past the no-sample ceiling the server samples anyway
  // and says so here, which turns the row means into estimates.
  const [estimated, setEstimated] = useState(false);

  // Tile width, measured rather than assumed, because the label-margin clamp
  // above is only meaningful against the real tile.
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [tileWidth, setTileWidth] = useState<number>(640);
  useEffect(() => {
    const el = boxRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width;
      if (!w || !Number.isFinite(w)) return;
      // Only react to real resizes: a margin change cannot move the container,
      // but a per-pixel setState would still churn the figure needlessly.
      setTileWidth((prev) => (Math.abs(prev - w) >= 8 ? w : prev));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Signal matrix: missing data binding');
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
      vizKind: SIGNAL_MATRIX_VIZ_KIND,
      roles: { region_id: regionCol, position: positionCol, value: valueCol },
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

  // Long format → one panel per group, each a binned matrix plus its mean
  // profile. Kept apart from the figure memo so a colour-scale flip does not
  // re-bin 10^5 regions.
  const matrix = useMemo(() => {
    if (!rows) return null;
    const regionRaw = rows[regionCol] || [];
    const positionRaw = rows[positionCol] || [];
    const valueRaw = rows[valueCol] || [];
    const groupRaw = groupCol ? rows[groupCol] || [] : null;
    const n = Math.min(regionRaw.length, positionRaw.length, valueRaw.length);
    if (n === 0) return null;

    // Columns: the observed offsets in numeric order. This is the only ordering
    // the matrix ever gets — no clustering, no reordering, per kind contract.
    const positionSet = new Set<number>();
    for (let i = 0; i < n; i++) {
      const p = Number(positionRaw[i]);
      if (Number.isFinite(p)) positionSet.add(p);
    }
    const positions = Array.from(positionSet).sort((a, b) => a - b);
    if (positions.length === 0) return null;
    const posIndex = new Map<number, number>(positions.map((p, i) => [p, i]));

    // Per group, per region: the running sum and hit count at every position.
    // Insertion order is the delivered order, which is what `sort_by: none`
    // means.
    interface Acc {
      sum: Float64Array;
      hits: Int32Array;
    }
    const byGroup = new Map<string, Map<string, Acc>>();
    const groupOrder: string[] = [];
    for (let i = 0; i < n; i++) {
      const p = posIndex.get(Number(positionRaw[i]));
      if (p === undefined) continue;
      const v = Number(valueRaw[i]);
      if (!Number.isFinite(v)) continue;
      const g = groupRaw ? String(groupRaw[i] ?? '') : '';
      let regions = byGroup.get(g);
      if (!regions) {
        regions = new Map<string, Acc>();
        byGroup.set(g, regions);
        groupOrder.push(g);
      }
      const id = String(regionRaw[i] ?? '');
      let acc = regions.get(id);
      if (!acc) {
        acc = {
          sum: new Float64Array(positions.length),
          hits: new Int32Array(positions.length),
        };
        regions.set(id, acc);
      }
      acc.sum[p] += v;
      acc.hits[p] += 1;
    }

    const keptGroups = groupOrder.slice(0, MAX_PANELS);
    const droppedGroups = groupOrder.length - keptGroups.length;
    // The row budget is shared across panels, so `max_rows` stays a bound on
    // what is drawn rather than a per-panel multiplier.
    const perPanel = Math.max(1, Math.floor(Math.max(1, maxRows) / Math.max(1, keptGroups.length)));

    const panels: Panel[] = [];
    let totalRegions = 0;
    for (const key of keptGroups) {
      const regions = byGroup.get(key);
      if (!regions) continue;
      const regionRows: RegionRow[] = [];
      for (const [id, acc] of regions) {
        // Divided in place: `acc.sum` becomes the region's mean vector, so a
        // 10^5-region frame allocates one typed array per region rather than
        // two, and a missing offset stays NaN instead of a boxed null.
        let total = 0;
        for (let p = 0; p < positions.length; p++) {
          if (acc.hits[p] > 0) {
            acc.sum[p] /= acc.hits[p];
            total += acc.sum[p];
          } else {
            acc.sum[p] = Number.NaN;
          }
        }
        regionRows.push({ id, values: acc.sum, total });
      }
      if (regionRows.length === 0) continue;
      // `none` needs no sort: a Map iterates in insertion order, which is the
      // order the frame delivered the regions in.
      if (sortBy === 'signal') {
        regionRows.sort((a, b) => b.total - a.total);
      }
      // The profile is the mean over every region in the panel, taken before
      // binning: binning is lossy for a row, exact for a column mean only if
      // the bins are equal-sized, and the last one never is.
      const profile: (number | null)[] = positions.map((_, p) => {
        let sum = 0;
        let hits = 0;
        for (const region of regionRows) {
          const v = region.values[p];
          if (!Number.isNaN(v)) {
            sum += v;
            hits += 1;
          }
        }
        return hits > 0 ? sum / hits : null;
      });
      totalRegions += regionRows.length;
      panels.push({
        key,
        rows: binRows(regionRows, perPanel),
        profile,
        regions: regionRows.length,
      });
    }
    if (panels.length === 0) return null;

    const drawnRows = panels.reduce((a, p) => a + p.rows.length, 0);
    const stride = Math.max(1, Math.ceil((drawnRows * positions.length) / RANGE_SAMPLE));
    const sample: number[] = [];
    let k = 0;
    for (const panel of panels) {
      for (const row of panel.rows) {
        for (const v of row.values) {
          if (v == null) continue;
          if (k % stride === 0) sample.push(v);
          k += 1;
        }
      }
    }
    const [zmin, zmax] = robustRange(sample);

    return {
      positions,
      panels,
      grouped: Boolean(groupCol) && panels.length > 1,
      droppedGroups,
      drawnRows,
      totalRegions,
      zmin,
      zmax,
    };
  }, [rows, regionCol, positionCol, valueCol, groupCol, sortBy, maxRows]);

  const figure = useMemo(() => {
    if (!matrix) return null;
    const { positions, panels, grouped, zmin, zmax } = matrix;
    const themeColors = plotlyThemeColors(isDark, theme);
    // Optional-chained: a theme whose primaryColor is not one of its own
    // colours would otherwise take the whole renderer down for a line colour.
    const accent = theme.colors[theme.primaryColor]?.[isDark ? 4 : 6];

    // Row labels only while they can be read; the margin they get is clamped to
    // a fraction of the measured tile (see LABEL_MARGIN_FRACTION) and the text
    // is truncated to fit it, so no binding can starve the plot area.
    const showRowLabels = matrix.drawnRows <= ROW_LABEL_LIMIT;
    const longest = panels.reduce(
      (a, p) => p.rows.reduce((b, r) => Math.max(b, r.label.length), a),
      0,
    );
    const marginCap = Math.max(24, Math.round(tileWidth * LABEL_MARGIN_FRACTION));
    const leftMargin = Math.min(
      showRowLabels ? Math.max(MIN_LEFT_MARGIN, longest * LABEL_CHAR_PX + 10) : MIN_LEFT_MARGIN,
      marginCap,
    );
    const labelChars = Math.max(3, Math.floor((leftMargin - 10) / LABEL_CHAR_PX));

    // Vertical bands: the profile on top, then one matrix band per panel, each
    // sized in proportion to the rows it draws.
    const profileBand = showProfile ? PROFILE_HEIGHT : 0;
    const matrixTop = showProfile ? 1 - profileBand - PANEL_GAP : 1;
    const available = Math.max(0.1, matrixTop - PANEL_GAP * (panels.length - 1));
    const rowTotal = panels.reduce((a, p) => a + Math.max(1, p.rows.length), 0);
    let cursor = matrixTop;
    const domains = panels.map((p) => {
      const top = cursor;
      const height = available * (Math.max(1, p.rows.length) / rowTotal);
      const bottom = Math.max(0, top - height);
      cursor = bottom - PANEL_GAP;
      return [bottom < top ? bottom : Math.max(0, top - 0.01), top] as [number, number];
    });

    const data: Record<string, unknown>[] = [];
    panels.forEach((panel, i) => {
      data.push({
        type: 'heatmap' as const,
        x: positions,
        y: panel.rows.map((r) => r.label),
        z: panel.rows.map((r) => r.values),
        xaxis: 'x',
        yaxis: axisRef(i),
        colorscale: colourScale,
        zmin,
        zmax,
        zsmooth: false,
        showscale: i === 0,
        colorbar:
          i === 0
            ? { thickness: 10, len: 0.75, title: { text: valueCol, side: 'right' as const } }
            : undefined,
        hovertemplate:
          `%{y}<br>${positionCol}: %{x}<br>${valueCol}: %{z:.3g}` +
          `<extra>${panel.key || ''}</extra>`,
      });
    });
    if (showProfile) {
      panels.forEach((panel) => {
        data.push({
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: positions,
          y: panel.profile,
          xaxis: 'x',
          yaxis: axisRef(panels.length),
          name: panel.key || 'mean',
          showlegend: grouped,
          line: { width: 2, ...(grouped ? {} : { color: accent }) },
          hovertemplate:
            `${positionCol}: %{x}<br>mean ${valueCol}: %{y:.3g}` +
            `<extra>${panel.key || ''}</extra>`,
        });
      });
    }

    // The reference point (a TSS at offset 0, usually) drawn through every
    // band, so the profile's peak and the matrix's stripe line up by eye.
    const reference = referencePosition;
    const withinRange =
      Number.isFinite(reference) &&
      reference >= positions[0] &&
      reference <= positions[positions.length - 1];
    const shapes = withinRange
      ? [
          {
            type: 'line' as const,
            xref: 'x' as const,
            yref: 'paper' as const,
            x0: reference,
            x1: reference,
            y0: 0,
            y1: 1,
            line: { color: themeColors.zeroLineColor, width: 1, dash: 'dot' as const },
          },
        ]
      : [];

    const annotations: Record<string, unknown>[] = [];
    if (withinRange && referenceLabel) {
      annotations.push({
        x: reference,
        xref: 'x' as const,
        y: 1,
        yref: 'paper' as const,
        yanchor: 'bottom' as const,
        text: referenceLabel,
        showarrow: false,
        font: { size: 10 },
      });
    }
    if (grouped) {
      panels.forEach((panel, i) => {
        annotations.push({
          x: 0,
          xref: 'paper' as const,
          xanchor: 'left' as const,
          y: domains[i][1],
          yref: 'paper' as const,
          yanchor: 'bottom' as const,
          text: `${panel.key} · ${panel.regions} regions`,
          showarrow: false,
          font: { size: 10 },
        });
      });
    }

    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      // `b` leaves room for the tick labels, the axis title and, when the panels
      // are grouped, the legend that sits under them.
      margin: {
        l: leftMargin,
        r: 16,
        t: annotations.length > 0 ? 22 : 12,
        b: grouped ? 78 : 46,
      },
      xaxis: {
        ...plotlyAxisOverrides(isDark, theme),
        title: { text: positionCol, standoff: 8 },
        // Anchored to the LAST panel, which is the bottom band: anchoring to
        // `y` (the first panel, drawn topmost) put the ticks and the title in
        // the gap under the top matrix, where they collided with the next
        // panel's title and left the figure with no axis at its foot.
        anchor: axisRef(panels.length - 1),
        zeroline: false,
        showgrid: false,
      },
      shapes,
      annotations,
      showlegend: grouped,
      // Below the axis rather than above it: the top band is the mean profile,
      // whose reference label already sits at the top of the paper.
      legend: {
        orientation: 'h' as const,
        x: 0,
        y: -0.06,
        yanchor: 'top' as const,
        font: { size: 10 },
      },
      hovermode: 'closest' as const,
      autosize: true,
    };
    panels.forEach((panel, i) => {
      layout[axisKey(i)] = {
        ...plotlyAxisOverrides(isDark, theme),
        domain: domains[i],
        anchor: 'x' as const,
        // Strongest signal on top: a categorical axis fills bottom-up.
        autorange: 'reversed' as const,
        showgrid: false,
        zeroline: false,
        // Never `automargin` on this axis — that is precisely the mechanism
        // that once collapsed a heatmap's plot area to a negative width.
        automargin: false,
        ...(showRowLabels
          ? {
              tickmode: 'array' as const,
              tickvals: panel.rows.map((r) => r.label),
              ticktext: panel.rows.map((r) => truncate(r.label, labelChars)),
              tickfont: { size: 9 },
            }
          : { showticklabels: false }),
      };
    });
    if (showProfile) {
      layout[axisKey(panels.length)] = {
        ...plotlyAxisOverrides(isDark, theme),
        domain: [1 - profileBand, 1] as [number, number],
        anchor: 'x' as const,
        showgrid: false,
        zeroline: false,
        automargin: false,
        tickfont: { size: 9 },
        title: { text: 'mean', standoff: 4, font: { size: 10 } },
      };
    }

    return { data, layout };
  }, [
    matrix,
    colourScale,
    showProfile,
    tileWidth,
    referencePosition,
    referenceLabel,
    positionCol,
    valueCol,
    isDark,
    theme,
  ]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Select
          size="xs"
          label="Colour scale"
          value={colourScale}
          onChange={(v) => v && setColourScale(v as ColourScale)}
          data={COLOUR_SCALES as unknown as string[]}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
        />
        <Select
          size="xs"
          label="Row order"
          description="Columns are positions and are never reordered"
          value={sortBy}
          onChange={(v) => v && setSortBy(v as SortBy)}
          data={[
            { value: 'signal', label: 'Total signal (strongest first)' },
            { value: 'none', label: 'As delivered' },
          ]}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
        />
        <NumberInput
          size="xs"
          label="Max rows"
          description="Regions are averaged into this many bins, never truncated"
          value={maxRows}
          onChange={(v) => {
            const next = typeof v === 'number' ? v : Number(v);
            if (Number.isFinite(next) && next >= 1) setMaxRows(Math.floor(next));
          }}
          min={1}
          max={20000}
          step={100}
          clampBehavior="strict"
        />
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Profile
          </Text>
          <Switch
            size="xs"
            checked={showProfile}
            onChange={(e) => setShowProfile(e.currentTarget.checked)}
            label="Mean profile above the matrix"
          />
        </Stack>
        {matrix ? (
          <Text size="xs" c="dimmed">
            {matrix.drawnRows} row{matrix.drawnRows === 1 ? '' : 's'} drawn from{' '}
            {matrix.totalRegions} region{matrix.totalRegions === 1 ? '' : 's'} ×{' '}
            {matrix.positions.length} positions
            {matrix.drawnRows < matrix.totalRegions ? ' (binned by averaging)' : ''}
            {matrix.droppedGroups > 0
              ? ` · ${matrix.droppedGroups} further group${
                  matrix.droppedGroups === 1 ? '' : 's'
                } not drawn`
              : ''}
          </Text>
        ) : null}
      </Stack>
    ),
    [colourScale, sortBy, maxRows, showProfile, matrix],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Signal matrix'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && !matrix ? 'No signal rows to draw' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      estimated={estimated}
    >
      <div ref={boxRef} style={{ width: '100%', height: '100%' }}>
        {figure ? (
          <Plot
            data={applyDataTheme(figure.data, isDark, theme) as any}
            layout={applyLayoutTheme(figure.layout, isDark, theme) as any}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
            config={{ displaylogo: false, responsive: true } as any}
          />
        ) : null}
      </div>
    </AdvancedVizFrame>
  );
};

export default SignalMatrixRenderer;
